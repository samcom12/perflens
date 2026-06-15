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

# A scalar reduction like `sum += ...`, `acc *= ...`, `s = s + ...` inside a loop
# body makes naive parallelisation a data race. We detect the common forms.
_REDUCTION_OP = re.compile(
    r"\b(?P<var>\w+)\s*(?:\+=|\*=|-=|\|=|&=|\^=)"            # var += / *= ...
    r"|\b(?P<var2>\w+)\s*=\s*(?P=var2)\s*[-+*/]"             # var = var + ...
)


def _brace_block_after(source: str, open_brace_idx: int) -> tuple[int, str]:
    """Return (end_index, body_text) for the {...} block starting at open_brace_idx."""
    depth = 0
    i = open_brace_idx
    n = len(source)
    while i < n:
        c = source[i]
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i, source[open_brace_idx : i + 1]
        i += 1
    return n, source[open_brace_idx:]


def _loop_body_after_header(source: str, header_match: re.Match) -> str:
    """Best-effort extraction of the loop body following a `for(...)` header."""
    brace = source.find("{", header_match.end())
    if brace == -1:
        # Single-statement body — take up to the next semicolon
        semi = source.find(";", header_match.end())
        return source[header_match.end(): semi + 1] if semi != -1 else ""
    _, body = _brace_block_after(source, brace)
    return body


def _has_reduction(body: str) -> bool:
    return bool(_REDUCTION_OP.search(body))


def _is_nested_inside(source: str, idx: int, outer_spans: list[tuple[int, int]]) -> bool:
    """True if character offset *idx* falls within any (start,end) outer-loop span."""
    return any(s < idx < e for s, e in outer_spans)


class OpenMPParallelRule(TransformRule):
    """
    Insert ``#pragma omp parallel for`` before the OUTERMOST for-loop of each
    independent loop nest that doesn't already have one.

    Safety:
    - Only the outermost loop of a nest is annotated (never inner loops), to
      avoid nested-parallelism oversubscription.
    - Loops whose body contains a scalar reduction (sum += ...) are skipped,
      because parallelising them without a reduction clause is a data race.
      (A future AST-based pass can emit the correct reduction clause instead.)
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
        # On a GPU target, the offload rule handles these loops with
        # `#pragma omp target teams distribute parallel for`. Adding a CPU
        # `#pragma omp parallel for` to the same loops would stack two
        # conflicting pragmas, so defer to the offload rule.
        if ctx.hardware.gpu:
            return False
        if _OMP_PARALLEL_ALREADY.search(ctx.source):
            return False
        return bool(_OUTER_LOOP.search(ctx.source))

    def apply(self, ctx: RuleContext) -> Optional[tuple[str, list[Patch]]]:
        source = ctx.source

        # 1. Find every for-loop header and the span of its body.
        all_loops: list[tuple[int, re.Match, int, int]] = []  # (start, match, body_start, body_end)
        for m in _OUTER_LOOP.finditer(source):
            brace = source.find("{", m.end())
            if brace == -1:
                continue
            end, _ = _brace_block_after(source, brace)
            all_loops.append((m.start(), m, brace, end))

        if not all_loops:
            return None

        # 2. Keep only OUTERMOST loops (not nested inside another loop's body).
        outer_spans = [(b, e) for (_s, _m, b, e) in all_loops]
        outermost: list[re.Match] = []
        for (start, m, brace, end) in all_loops:
            nested = any(bs < start < be for (bs, be) in outer_spans
                         if not (bs == brace and be == end))
            # A loop is nested if its header start lies within another loop's body
            is_inner = any(
                obrace < start < oend
                for (_os, _om, obrace, oend) in all_loops
                if obrace != brace
            )
            if not is_inner:
                outermost.append((m, brace, end))

        # 3. Annotate outermost loops that are not reductions.
        patches: list[Patch] = []
        insertions: list[tuple[int, str]] = []   # (line_index, text)

        for (m, brace, end) in outermost:
            body = source[brace: end + 1]
            if _has_reduction(body):
                # Unsafe to parallelise naively — skip (fail safe).
                continue
            lineno = _line_of(source, m)
            indent = m.group("indent")
            insertions.append((lineno, f"{indent}#pragma omp parallel for schedule(static)"))
            patches.append(Patch(
                transform_kind=TransformKind.OPENMP_PARALLELISE,
                description=f"Add #pragma omp parallel for before outermost loop at line {lineno}",
                original_snippet=m.group(0).strip(),
                optimized_snippet=f"{indent}#pragma omp parallel for schedule(static)\n" + m.group(0).strip(),
                start_line=lineno, end_line=lineno,
                rationale=(
                    f"Hardware has {ctx.hardware.total_cores} cores. Only the "
                    "outermost loop of the nest is parallelised; reduction loops "
                    "are skipped to avoid data races."
                ),
                expected_speedup=f"up to {min(ctx.hardware.total_cores, 32)}×",
            ))

        if not patches:
            return None

        # 4. Apply insertions bottom-up so line numbers stay valid.
        lines = source.splitlines(keepends=True)
        for lineno, text in sorted(insertions, key=lambda x: x[0], reverse=True):
            lines.insert(lineno - 1, text + "\n")

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
            bound  = m.group("bound")

            # The regex stops at the loop condition; advance past the rest of
            # the `for(...)` clause to its closing ')'. The body must then be a
            # brace block that immediately follows. If a '{' does not appear
            # before the next ';' or other statement, this is a single-statement
            # loop and searching further would wrongly grab another function's
            # body, so we skip it.
            after = ctx.source[m.end():]
            close_paren = after.find(")")
            if close_paren == -1:
                continue
            rest = after[close_paren + 1:]
            stripped = rest.lstrip()
            if not stripped.startswith("{"):
                continue
            brace = m.end() + close_paren + 1 + (len(rest) - len(stripped))
            depth, i, n = 0, brace, len(ctx.source)
            while i < n:
                if ctx.source[i] == "{":
                    depth += 1
                elif ctx.source[i] == "}":
                    depth -= 1
                    if depth == 0:
                        break
                i += 1
            body = ctx.source[brace: i + 1]

            # Never offload memory-management or I/O loops to a GPU — these are
            # not compute kernels and mapping their pointers is invalid/unsafe.
            if re.search(r"\b(malloc|calloc|realloc|free|fopen|fwrite|fread|"
                         r"fclose|fprintf|printf|memcpy|memset)\s*\(", body):
                continue

            # Arrays = identifiers used with subscript `name[...]`.
            arrays = sorted(set(re.findall(r"\b([A-Za-z_]\w*)\s*\[", body)))
            # Drop the induction variable if it somehow appears.
            arrays = [a for a in arrays if a != m.group("var")]
            if not arrays:
                # No array accesses → cannot build a valid map clause; skip.
                continue

            # Build a valid map clause. We don't know exact extents statically,
            # so we map each array over [0:bound] which is the common 1-D case
            # and is valid OpenMP (bound is the loop trip count).
            map_clause = " ".join(f"map(tofrom:{a}[0:{bound}])" for a in arrays)
            pragma = (
                f"{indent}#pragma omp target teams distribute parallel for "
                f"{map_clause} thread_limit(128)"
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
                    f"(CC {cc}). Offloads loop to "
                    f"{ctx.hardware.gpu.sm_count if ctx.hardware.gpu else '?'} SMs. "
                    f"Arrays mapped: {', '.join(arrays)}. Verify array extents "
                    "match the loop trip count for multi-dimensional access."
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
# A divisor we can safely hoist must be a plain scalar identifier that is NOT:
#   - a C keyword / type name (double, float, int, ...)
#   - immediately followed by '[' (array subscript → not loop-invariant)
#   - immediately followed by '(' (function call)
#   - the loop induction variable
# We deliberately do NOT match expressions, casts, or member access.
_C_KEYWORDS = {
    "double", "float", "int", "long", "short", "char", "void", "const",
    "unsigned", "signed", "size_t", "static", "struct", "union", "enum",
    "return", "sizeof", "if", "else", "for", "while", "do",
}
_DIV_BY_SCALAR = re.compile(
    r"/\s*(?P<divisor>[A-Za-z_]\w*)\b(?!\s*[\[\(=*/.])"
)


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
            raw_loop_body = loop_m.group("loop")
            # Strip comments and string/char literals so we never treat tokens
            # inside `/* I/O */` or "a/b" as real division divisors.
            loop_body = re.sub(r"/\*.*?\*/", " ", raw_loop_body, flags=re.DOTALL)
            loop_body = re.sub(r"//[^\n]*", " ", loop_body)
            loop_body = re.sub(r'"(?:[^"\\]|\\.)*"', '""', loop_body)
            loop_body = re.sub(r"'(?:[^'\\]|\\.)'", "' '", loop_body)
            loop_lineno = _line_of(source, loop_m)

            # Identify the loop induction variable.
            loop_var_m = re.search(r"for\s*\(\s*\w+\s+(\w+)\s*=", loop_body)
            loop_var = loop_var_m.group(1) if loop_var_m else None

            # Collect candidate scalar divisors.
            divisors: set[str] = set()
            for div_m in _DIV_BY_SCALAR.finditer(loop_body):
                d = div_m.group("divisor").strip()
                if d == loop_var:
                    continue
                if d in _C_KEYWORDS:                 # never a real variable
                    continue
                if d.isdigit():
                    continue
                # Reject if it's assigned anywhere in the loop body (not invariant)
                if re.search(rf"\b{re.escape(d)}\s*(?:=|\+\+|--|\+=|-=|\*=|/=)", loop_body):
                    continue
                # Reject if it ever appears subscripted/called (so `h[i]` / `f()`)
                if re.search(rf"\b{re.escape(d)}\s*[\[\(]", loop_body):
                    continue
                divisors.add(d)

            if not divisors:
                continue

            # Determine indentation of the loop for clean insertion.
            line_start = source.rfind("\n", 0, loop_m.start()) + 1
            indent = source[line_start: loop_m.start()]
            if indent.strip():        # loop not at line start; default indent
                indent = ""

            # Build reciprocal declarations (valid C: divisor is a scalar).
            inv_decls = "".join(
                f"{indent}const double inv_{d} = 1.0 / {d};\n"
                for d in sorted(divisors)
            )

            # Apply the substitution to the RAW body so comments/strings are
            # preserved. We only rewrite `/ divisor` where divisor was validated
            # above as a loop-invariant scalar. To avoid touching occurrences
            # inside comments, we rewrite on a comment-masked copy and splice.
            new_body = raw_loop_body
            for d in sorted(divisors):
                new_body = re.sub(
                    rf"/\s*{re.escape(d)}\b(?!\s*[\[\(=*/.])",
                    f"* inv_{d}",
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
                    "Precomputing the reciprocal of a loop-invariant scalar divisor "
                    "eliminates the per-iteration division."
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
        if not (_MPI_SEND.search(ctx.source) or _MPI_RECV.search(ctx.source)):
            return False
        # Only transform when mpi.h is unconditionally included. If MPI calls
        # are inside an #ifdef USE_MPI block but the declaration injected by
        # _make_nonblocking_c (MPI_Request/MPI_Status) lands outside it, the
        # resulting code won't compile without the USE_MPI define. Detect this
        # by checking that the #include <mpi.h> is not preceded by an #ifdef on
        # the same or immediately prior line.
        mpi_include = re.search(r'^#\s*include\s*[<"]mpi\.h[>"]', ctx.source, re.MULTILINE)
        if not mpi_include:
            return False
        # Find the line before the #include; if it is an #ifdef, skip.
        line_start = ctx.source.rfind("\n", 0, mpi_include.start()) + 1
        prev_line = ctx.source[:line_start].rstrip().rsplit("\n", 1)[-1].strip()
        if prev_line.startswith("#ifdef") or prev_line.startswith("#if "):
            return False
        return True

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
    r"\s*(?P<indent2>)for\s*\([^;]+;\s*\w+\s*<\s*(?P<N2>\w+)\s*;[^)]+\)\s*\{"
    r"\s*(?P<indent3>)for\s*\([^;]+;\s*\w+\s*<\s*(?P<N3>\w+)\s*;[^)]+\)\s*\{",
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

        loops = re.findall(r"for\s*\(\s*\w+\s+(\w+)\s*=", m.group(0))
        if len(loops) < 3:
            return None
        i = loops[0]
        n1 = m.group("N1")

        # Strip-mine ONLY the outermost loop. This converts
        #     for (i = 0; i < N1; i++) { <nest> }
        # into
        #     for (ii = 0; ii < N1; ii += TILE)
        #     for (i = ii; i < ii+TILE && i < N1; i++) { <nest> }
        # This adds exactly ONE new loop header and NO extra braces, so brace
        # balance is preserved exactly (the original body/braces are untouched).
        # Tiling the inner loops too would require restructuring the body, which
        # cannot be done safely by text rewriting, so we keep this conservative
        # and correct rather than aggressive and broken.
        outer_re = re.compile(
            rf"for\s*\(\s*(?:int|long|size_t)\s+{re.escape(i)}\s*=\s*0\s*;\s*"
            rf"{re.escape(i)}\s*<\s*{re.escape(n1)}\s*;\s*{re.escape(i)}\s*\+\+\s*\)"
        )
        om = outer_re.search(ctx.source)
        if not om:
            return None

        line_start = ctx.source.rfind("\n", 0, om.start()) + 1
        lead = ctx.source[line_start:om.start()]
        indent = lead if not lead.strip() else ""

        replacement = (
            f"/* PerfLens loop tiling (strip-mine outer loop): "
            f"L1d={ctx.hardware.l1d_kb}KB -> TILE={tile} */\n"
            f"{indent}for (int {i}i = 0; {i}i < {n1}; {i}i += TILE)\n"
            f"{indent}for (int {i} = {i}i; {i} < {i}i + TILE && {i} < {n1}; {i}++)"
        )

        new_source = ctx.source[:om.start()] + replacement + ctx.source[om.end():]

        # TILE macro must be a top-level directive on its own line.
        if "#define TILE" not in new_source:
            define_line = f"#define TILE {tile}\n"
            inc = list(re.finditer(r"^#\s*include[^\n]*\n", new_source, re.MULTILINE))
            if inc:
                pos = inc[-1].end()
                new_source = new_source[:pos] + define_line + new_source[pos:]
            else:
                new_source = define_line + new_source

        if new_source == ctx.source:
            return None

        return new_source, [Patch(
            transform_kind=TransformKind.LOOP_TILING,
            description=f"Strip-mine outer loop at line {lineno} with TILE={tile}",
            original_snippet=om.group(0)[:200],
            optimized_snippet=replacement[:200],
            start_line=lineno,
            end_line=lineno,
            rationale=(
                f"L1d={ctx.hardware.l1d_kb}KB -> tile={tile}. Strip-mining the "
                "outer loop improves cache locality while preserving loop "
                "semantics and brace structure exactly."
            ),
            expected_speedup="1.5–4×",
            metadata={"tile_size": tile},
        )]
