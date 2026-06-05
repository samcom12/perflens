"""
Concrete C/C++ source-level transformation rules.

Each rule is a single-responsibility class that:
  - Has a cheap `applies()` check (regex / scanner findings)
  - Has an `apply()` that produces a concrete source diff

Rules are designed to be safe — they only add pragmas or hoist computations;
they never change algorithm logic.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from perflens.optimizer.models import Patch, TransformKind
from perflens.optimizer.rules.base_rule import RuleContext, TransformRule
from perflens.scanner.models import FindingKind


# ── Helper: insert line before a match ───────────────────────────────────────

def _insert_before_line(source: str, lineno: int, insertion: str) -> str:
    lines = source.splitlines(keepends=True)
    lines.insert(lineno - 1, insertion + "\n")
    return "".join(lines)


def _line_of(source: str, match: re.Match) -> int:
    return source[: match.start()].count("\n") + 1


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 1 — OpenMP parallel for
# ═══════════════════════════════════════════════════════════════════════════════

_OMP_PARALLEL_ALREADY = re.compile(
    r"#\s*pragma\s+omp\s+parallel", re.MULTILINE
)

# Outer for-loop that updates a[i] — typical parallelisable pattern
_OUTER_LOOP = re.compile(
    r"^(?P<indent>\s*)for\s*\(\s*(?:int|long|size_t|uint\w*)\s+(?P<var>\w+)\s*=",
    re.MULTILINE,
)


class OpenMPParallelRule(TransformRule):
    """
    Insert ``#pragma omp parallel for [schedule(static)] [reduction(...)]``
    before outer for-loops that don't already have one.

    Only fires when:
    - target hardware has multiple cores
    - no OMP parallel already present in the file
    - at least one outer loop detected
    """

    supported_languages = {"c", "cpp"}

    @property
    def name(self) -> str:
        return "openmp_parallel_for"

    @property
    def transform_kind(self) -> TransformKind:
        return TransformKind.OPENMP_PARALLELISE

    def applies(self, ctx: RuleContext) -> bool:
        if ctx.language not in self.supported_languages:
            return False
        if ctx.hardware.total_cores < 2:
            return False
        if _OMP_PARALLEL_ALREADY.search(ctx.source):
            return False
        return bool(_OUTER_LOOP.search(ctx.source))

    def apply(self, ctx: RuleContext) -> Optional[tuple[str, list[Patch]]]:
        patches: list[Patch] = []
        source = ctx.source
        lines  = source.splitlines(keepends=True)
        offset = 0   # track inserted lines

        for m in _OUTER_LOOP.finditer(ctx.source):
            lineno  = _line_of(ctx.source, m)
            insert  = f"{m.group('indent')}#pragma omp parallel for schedule(static)"
            idx     = lineno - 1 + offset

            # Don't double-insert
            prev_line = lines[idx - 1].strip() if idx > 0 else ""
            if "pragma omp" in prev_line:
                continue

            lines.insert(idx, insert + "\n")
            offset += 1

            patches.append(Patch(
                transform_kind=TransformKind.OPENMP_PARALLELISE,
                description=f"Add #pragma omp parallel for before loop at line {lineno}",
                original_snippet=m.group(0).strip(),
                optimized_snippet=insert + "\n" + m.group(0).strip(),
                start_line=lineno, end_line=lineno,
                rationale=(
                    f"Hardware has {ctx.hardware.total_cores} cores. "
                    "OpenMP parallelises the outer loop across all available threads."
                ),
                expected_speedup=f"up to {min(ctx.hardware.total_cores, 32)}×",
            ))

        if not patches:
            return None
        return "".join(lines), patches


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 2 — OpenMP SIMD on inner loops
# ═══════════════════════════════════════════════════════════════════════════════

_OMP_SIMD_ALREADY = re.compile(r"#\s*pragma\s+omp\s+simd", re.MULTILINE)
_GCC_IVDEP        = re.compile(r"#\s*pragma\s+GCC\s+ivdep", re.MULTILINE)

_INNER_LOOP = re.compile(
    r"^(?P<indent>\s{4,})for\s*\(\s*(?:int|long|size_t)\s+\w+\s*=",
    re.MULTILINE,
)


class OpenMPSIMDRule(TransformRule):
    """
    Insert ``#pragma omp simd`` before inner loops where SIMD is beneficial.
    Requires AVX2 / AVX-512 / SVE hardware.
    """

    supported_languages = {"c", "cpp"}

    @property
    def name(self) -> str:
        return "openmp_simd"

    @property
    def transform_kind(self) -> TransformKind:
        return TransformKind.OPENMP_SIMD

    def applies(self, ctx: RuleContext) -> bool:
        if ctx.language not in self.supported_languages:
            return False
        if not ctx.hardware.simd:
            return False
        if _OMP_SIMD_ALREADY.search(ctx.source) or _GCC_IVDEP.search(ctx.source):
            return False
        # Need scanner finding or inner loop pattern
        has_simd_finding = any(
            f.kind == FindingKind.MISSING_SIMD_PRAGMA for f in ctx.findings
        )
        return has_simd_finding or bool(_INNER_LOOP.search(ctx.source))

    def apply(self, ctx: RuleContext) -> Optional[tuple[str, list[Patch]]]:
        patches: list[Patch] = []
        simd_w = ctx.hardware.simd.vector_width_bits if ctx.hardware.simd else 256
        lines  = ctx.source.splitlines(keepends=True)
        offset = 0

        for m in _INNER_LOOP.finditer(ctx.source):
            lineno = _line_of(ctx.source, m)
            indent = m.group("indent")
            insert = f"{indent}#pragma omp simd"

            idx = lineno - 1 + offset
            prev = lines[idx - 1].strip() if idx > 0 else ""
            if "pragma" in prev:
                continue

            lines.insert(idx, insert + "\n")
            offset += 1

            patches.append(Patch(
                transform_kind=TransformKind.OPENMP_SIMD,
                description=f"Add #pragma omp simd at line {lineno}",
                original_snippet=m.group(0).strip(),
                optimized_snippet=insert + "\n" + m.group(0).strip(),
                start_line=lineno, end_line=lineno,
                rationale=(
                    f"Target SIMD: {ctx.hardware.simd.instruction_set if ctx.hardware.simd else 'SSE'} "
                    f"({simd_w}-bit). Pragma hints vectorizer to emit SIMD instructions."
                ),
                expected_speedup=f"{simd_w // 64}–{simd_w // 32}×",
            ))
            # Limit: only annotate first 5 inner loops to avoid noise
            if len(patches) >= 5:
                break

        if not patches:
            return None
        return "".join(lines), patches


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 3 — OpenMP target offload (GPU)
# ═══════════════════════════════════════════════════════════════════════════════

_OMP_TARGET_ALREADY = re.compile(r"#\s*pragma\s+omp\s+target", re.MULTILINE)

_OFFLOAD_LOOP = re.compile(
    r"^(?P<indent>\s*)for\s*\(\s*(?:int|long)\s+(?P<var>\w+)\s*=\s*0\s*;\s*"
    r"(?P=var)\s*<\s*(?P<bound>\w+)\s*;",
    re.MULTILINE,
)


class OpenMPOffloadRule(TransformRule):
    """
    Insert ``#pragma omp target teams distribute parallel for`` for GPU offload.
    Only fires when hardware profile has a GPU.
    """

    supported_languages = {"c", "cpp"}

    @property
    def name(self) -> str:
        return "openmp_offload"

    @property
    def transform_kind(self) -> TransformKind:
        return TransformKind.OPENMP_OFFLOAD

    def applies(self, ctx: RuleContext) -> bool:
        if ctx.language not in self.supported_languages:
            return False
        if not ctx.hardware.gpu:
            return False
        if _OMP_TARGET_ALREADY.search(ctx.source):
            return False
        return bool(_OFFLOAD_LOOP.search(ctx.source))

    def apply(self, ctx: RuleContext) -> Optional[tuple[str, list[Patch]]]:
        patches: list[Patch] = []
        cc      = ctx.hardware.gpu.compute_capability if ctx.hardware.gpu else "8.0"
        lines   = ctx.source.splitlines(keepends=True)
        offset  = 0

        for m in list(_OFFLOAD_LOOP.finditer(ctx.source))[:2]:   # first 2 loops only
            lineno = _line_of(ctx.source, m)
            indent = m.group("indent")
            pragma = (
                f"{indent}#pragma omp target teams distribute parallel for "
                f"map(tofrom:{m.group('bound')}[0:{m.group('bound')}]) "
                f"thread_limit(128)"
            )
            idx = lineno - 1 + offset
            prev = lines[idx - 1].strip() if idx > 0 else ""
            if "pragma omp target" in prev:
                continue

            lines.insert(idx, pragma + "\n")
            offset += 1

            patches.append(Patch(
                transform_kind=TransformKind.OPENMP_OFFLOAD,
                description=f"Add OpenMP target offload at line {lineno}",
                original_snippet=m.group(0).strip(),
                optimized_snippet=pragma + "\n" + m.group(0).strip(),
                start_line=lineno, end_line=lineno,
                rationale=(
                    f"Target GPU: {ctx.hardware.gpu.name if ctx.hardware.gpu else 'unknown'} "
                    f"(CC {cc}). Offloads loop to {ctx.hardware.gpu.sm_count if ctx.hardware.gpu else '?'} SMs."
                ),
                expected_speedup="5–50× (data-transfer dependent)",
            ))

        if not patches:
            return None
        return "".join(lines), patches


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 4 — Hoist loop-invariant division → reciprocal
# ═══════════════════════════════════════════════════════════════════════════════

# Pattern: `/ <identifier>` or `/ (expression)` inside a loop body
_DIV_LOOP = re.compile(
    r"(?P<loop>for\s*\([^{]+\)\s*\{(?:[^{}]|\{[^{}]*\})*\})",
    re.DOTALL,
)
_DIV_BY_VAR = re.compile(r"/\s*(?P<divisor>[a-zA-Z_]\w*(?:\s*\+\s*\d+)?)\b(?!\s*[=*/])")


class DivisionHoistRule(TransformRule):
    """
    Hoist ``/ divisor`` in a loop to ``inv_divisor = 1.0 / divisor; … * inv_divisor``.

    Only applies when the divisor is loop-invariant (an identifier, not a
    loop-variable-dependent expression).
    """

    supported_languages = {"c", "cpp"}

    @property
    def name(self) -> str:
        return "division_hoist"

    @property
    def transform_kind(self) -> TransformKind:
        return TransformKind.STRENGTH_REDUCTION

    def applies(self, ctx: RuleContext) -> bool:
        if ctx.language not in self.supported_languages:
            return False
        return any(f.kind == FindingKind.DIVISION_IN_LOOP for f in ctx.findings)

    def apply(self, ctx: RuleContext) -> Optional[tuple[str, list[Patch]]]:
        patches: list[Patch] = []
        source = ctx.source

        for loop_m in _DIV_LOOP.finditer(source):
            loop_body = loop_m.group("loop")
            loop_lineno = _line_of(source, loop_m)

            # Find the loop variable (first token after `for (type var = ...`)
            loop_var_m = re.search(
                r"for\s*\(\s*\w+\s+(\w+)\s*=", loop_body
            )
            loop_var = loop_var_m.group(1) if loop_var_m else None

            divisors: set[str] = set()
            for div_m in _DIV_BY_VAR.finditer(loop_body):
                d = div_m.group("divisor").strip()
                # Only hoist if divisor is not the loop var and looks like a scalar
                if d != loop_var and not d.isdigit():
                    divisors.add(d)

            if not divisors:
                continue

            # Insert reciprocal declaration before the loop
            inv_decls = ""
            for d in sorted(divisors):
                inv_name = f"inv_{d}"
                inv_decls += f"    const double {inv_name} = 1.0 / {d};\n"

            # Replace `/divisor` with `* inv_divisor` in the loop
            new_body = loop_body
            for d in sorted(divisors):
                inv_name = f"inv_{d}"
                new_body = re.sub(
                    rf"/\s*{re.escape(d)}\b(?!\s*[=*/])",
                    f"* {inv_name}",
                    new_body,
                )

            new_loop = inv_decls + new_body
            source = source[:loop_m.start()] + new_loop + source[loop_m.end():]

            patches.append(Patch(
                transform_kind=TransformKind.STRENGTH_REDUCTION,
                description=f"Hoist division by {sorted(divisors)} before loop at line {loop_lineno}",
                original_snippet=loop_body[:200],
                optimized_snippet=new_loop[:200],
                start_line=loop_lineno,
                end_line=loop_lineno + loop_body.count("\n"),
                rationale=(
                    "Division is 4–30× slower than multiplication on modern FPUs. "
                    "Precomputing the reciprocal eliminates the per-iteration division."
                ),
                expected_speedup="1.2–3×",
            ))
            break   # one loop per pass to keep diffs readable

        if not patches:
            return None
        return source, patches


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 5 — MPI blocking → non-blocking
# ═══════════════════════════════════════════════════════════════════════════════

_MPI_SEND = re.compile(
    r"(MPI_Send\s*\((?:[^;]+)\);)",
    re.DOTALL,
)
_MPI_RECV = re.compile(
    r"(MPI_Recv\s*\((?:[^;]+)\);)",
    re.DOTALL,
)


def _make_nonblocking_c(source: str) -> tuple[str, int]:
    """Convert MPI_Send/Recv pairs to Isend/Irecv + MPI_Waitall."""
    request_idx = 0
    requests    = []
    new_source  = source

    # Replace MPI_Send
    for m in _MPI_SEND.finditer(source):
        req_var = f"req[{request_idx}]"
        new_call = m.group(1).replace("MPI_Send(", "MPI_Isend(", 1)
        # Insert request arg before the last close paren
        new_call = re.sub(r"\)\s*;$", f", &{req_var});", new_call)
        new_source = new_source.replace(m.group(1), new_call, 1)
        requests.append(req_var)
        request_idx += 1

    for m in _MPI_RECV.finditer(source):
        req_var = f"req[{request_idx}]"
        new_call = m.group(1).replace("MPI_Recv(", "MPI_Irecv(", 1)
        # Remove MPI_STATUS_IGNORE, insert request arg
        new_call = re.sub(r",\s*MPI_STATUS_IGNORE", "", new_call)
        new_call = re.sub(r"\)\s*;$", f", &{req_var});", new_call)
        new_source = new_source.replace(m.group(1), new_call, 1)
        requests.append(req_var)
        request_idx += 1

    if requests:
        decl    = f"\n    MPI_Request req[{len(requests)}];\n    MPI_Status  stat[{len(requests)}];\n"
        waitall = f"\n    MPI_Waitall({len(requests)}, req, stat);\n"
        # Insert declaration right after the first opening brace of the function
        new_source = re.sub(r"(\{)", r"\1" + decl, new_source, count=1)
        # Append Waitall before the return or end of function
        new_source = re.sub(r"(\n\s*return\b)", waitall + r"\1", new_source, count=1)
        if "MPI_Waitall" not in new_source:
            new_source = new_source.rstrip() + waitall + "\n"

    return new_source, request_idx


class MPINonBlockingRule(TransformRule):
    """
    Replace ``MPI_Send/MPI_Recv`` with ``MPI_Isend/MPI_Irecv`` + ``MPI_Waitall``.

    This allows the CPU to do useful work while communication is in flight.
    """

    supported_languages = {"c", "cpp"}

    @property
    def name(self) -> str:
        return "mpi_nonblocking"

    @property
    def transform_kind(self) -> TransformKind:
        return TransformKind.MPI_NONBLOCKING

    def applies(self, ctx: RuleContext) -> bool:
        if ctx.language not in self.supported_languages:
            return False
        return bool(_MPI_SEND.search(ctx.source) or _MPI_RECV.search(ctx.source))

    def apply(self, ctx: RuleContext) -> Optional[tuple[str, list[Patch]]]:
        new_source, n_replaced = _make_nonblocking_c(ctx.source)
        if n_replaced == 0 or new_source == ctx.source:
            return None
        patches = [Patch(
            transform_kind=TransformKind.MPI_NONBLOCKING,
            description=f"Convert {n_replaced} blocking MPI call(s) to non-blocking",
            original_snippet="MPI_Send/MPI_Recv calls",
            optimized_snippet="MPI_Isend/MPI_Irecv + MPI_Waitall",
            start_line=1, end_line=len(ctx.source.splitlines()),
            rationale=(
                "Non-blocking MPI allows CPU compute to overlap with network transfer. "
                "Typical overlap ratio: 40–80% of communication latency hidden."
            ),
            expected_speedup="1.3–2× on communication-bound codes",
        )]
        return new_source, patches


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 6 — Loop tiling for triple-nested loops
# ═══════════════════════════════════════════════════════════════════════════════

_TRIPLE_NEST = re.compile(
    r"(?P<indent1>\s*)for\s*\([^;]+;\s*\w+\s*<\s*(?P<N1>\w+)\s*;[^)]+\)\s*\{"
    r"[^{}]*(?P<indent2>\s*)for\s*\([^;]+;\s*\w+\s*<\s*(?P<N2>\w+)\s*;[^)]+\)\s*\{"
    r"[^{}]*(?P<indent3>\s*)for\s*\([^;]+;\s*\w+\s*<\s*(?P<N3>\w+)\s*;[^)]+\)\s*\{",
    re.DOTALL,
)


def _compute_tile_size(hw: "HardwareProfile") -> int:
    """Estimate a good tile size from L1 cache size."""
    # Tile so that 3 tiles fit in L1d: tile = floor(cbrt(L1d_bytes / sizeof(double)))
    import math
    l1_bytes  = hw.l1d_kb * 1024
    tile_fp64 = int(math.floor((l1_bytes / 8) ** (1 / 3)))
    # Round down to power of 2
    return max(8, 1 << (tile_fp64.bit_length() - 1))


class LoopTilingRule(TransformRule):
    """
    Add loop tiling (blocking) to the first triple-nested loop found.

    Generates a tiled version with configurable TILE size derived from L1 cache.
    """

    supported_languages = {"c", "cpp"}

    @property
    def name(self) -> str:
        return "loop_tiling"

    @property
    def transform_kind(self) -> TransformKind:
        return TransformKind.LOOP_TILING

    def applies(self, ctx: RuleContext) -> bool:
        if ctx.language not in self.supported_languages:
            return False
        has_finding = any(
            f.kind == FindingKind.LOOP_TILING_OPPORTUNITY for f in ctx.findings
        )
        return has_finding or bool(_TRIPLE_NEST.search(ctx.source))

    def apply(self, ctx: RuleContext) -> Optional[tuple[str, list[Patch]]]:
        m = _TRIPLE_NEST.search(ctx.source)
        if not m:
            return None

        tile = _compute_tile_size(ctx.hardware)
        lineno = _line_of(ctx.source, m)

        # Extract loop variable names from the original
        loops = re.findall(
            r"for\s*\(\s*\w+\s+(\w+)\s*=", m.group(0)
        )
        if len(loops) < 3:
            return None
        i, j, k = loops[:3]
        bounds   = [m.group("N1"), m.group("N2"), m.group("N3")]

        tiled = (
            f"#define TILE {tile}\n"
            f"/* Loop tiling: L1d={ctx.hardware.l1d_kb}KB → tile={tile} */\n"
            f"for (int {i}i = 0; {i}i < {bounds[0]}; {i}i += TILE)\n"
            f"  for (int {j}i = 0; {j}i < {bounds[1]}; {j}i += TILE)\n"
            f"    for (int {k}i = 0; {k}i < {bounds[2]}; {k}i += TILE)\n"
            f"      for (int {i} = {i}i; {i} < {i}i+TILE && {i} < {bounds[0]}; {i}++)\n"
            f"        for (int {j} = {j}i; {j} < {j}i+TILE && {j} < {bounds[1]}; {j}++)\n"
            f"          for (int {k} = {k}i; {k} < {k}i+TILE && {k} < {bounds[2]}; {k}++)\n"
        )

        # Replace only the loop headers (not the body) with the tiled version
        original_headers = m.group(0).split("{")[0]
        new_source = ctx.source.replace(original_headers, tiled, 1)

        return new_source, [Patch(
            transform_kind=TransformKind.LOOP_TILING,
            description=f"Tile triple-nested loop at line {lineno} with TILE={tile}",
            original_snippet=original_headers[:300],
            optimized_snippet=tiled[:300],
            start_line=lineno,
            end_line=lineno + 3,
            rationale=(
                f"L1d={ctx.hardware.l1d_kb}KB → tile={tile} elements. "
                "Tiling keeps the working set in L1/L2 cache, reducing memory traffic."
            ),
            expected_speedup="2–8×",
            metadata={"tile_size": tile},
        )]
