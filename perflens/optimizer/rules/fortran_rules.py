"""
Fortran source-level transformation rules.
"""

from __future__ import annotations

import re
from typing import Optional

from perflens.optimizer.models import Patch, TransformKind
from perflens.optimizer.rules.base_rule import RuleContext, TransformRule
from perflens.scanner.models import FindingKind


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 1 — Add IMPLICIT NONE to subroutines missing it
# ═══════════════════════════════════════════════════════════════════════════════

_SUB_FUNC = re.compile(
    r"^(?P<indent>[ \t]*)(?P<kw>SUBROUTINE|FUNCTION)\s+(?P<name>\w+)\s*"
    r"(?:\([^)]*\))?",
    re.IGNORECASE | re.MULTILINE,
)
_IMPLICIT_NONE = re.compile(r"^\s*IMPLICIT\s+NONE", re.IGNORECASE | re.MULTILINE)


class ImplicitNoneRule(TransformRule):
    """
    Insert ``IMPLICIT NONE`` after each SUBROUTINE/FUNCTION declaration
    that lacks it.  This is required for compiler type-safety analysis
    and enables better auto-vectorisation.
    """

    supported_languages = {"fortran"}

    @property
    def name(self) -> str:
        return "implicit_none"

    @property
    def transform_kind(self) -> TransformKind:
        return TransformKind.GENERAL

    def applies(self, ctx: RuleContext) -> bool:
        if ctx.language != "fortran":
            return False
        return bool(_SUB_FUNC.search(ctx.source)) and not _IMPLICIT_NONE.search(ctx.source)

    def apply(self, ctx: RuleContext) -> Optional[tuple[str, list[Patch]]]:
        lines   = ctx.source.splitlines(keepends=True)
        patches = []
        offset  = 0

        for m in _SUB_FUNC.finditer(ctx.source):
            lineno = ctx.source[: m.start()].count("\n") + 1
            indent = m.group("indent")

            # Look ahead to see if IMPLICIT NONE is already within 5 lines
            snippet = "".join(lines[lineno - 1 : lineno + 5])
            if re.search(r"IMPLICIT\s+NONE", snippet, re.IGNORECASE):
                continue

            insert = f"{indent}  IMPLICIT NONE\n"
            idx    = lineno + offset          # insert after the subroutine line
            lines.insert(idx, insert)
            offset += 1

            patches.append(Patch(
                transform_kind=TransformKind.GENERAL,
                description=f"Add IMPLICIT NONE to {m.group('kw')} {m.group('name')}",
                original_snippet=m.group(0),
                optimized_snippet=m.group(0) + "\n" + insert,
                start_line=lineno, end_line=lineno,
                rationale=(
                    "IMPLICIT NONE prevents undeclared variables and allows the "
                    "compiler to perform full type analysis, enabling better "
                    "vectorisation and inlining."
                ),
                expected_speedup="1.0–1.3× (compiler quality improvement)",
            ))

        if not patches:
            return None
        return "".join(lines), patches


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 2 — Add !$OMP PARALLEL DO to innermost DO loops
# ═══════════════════════════════════════════════════════════════════════════════

_DO_LOOP = re.compile(
    r"^(?P<indent>[ \t]*)DO\s+(?P<var>\w+)\s*=\s*(?P<lo>\S+)\s*,\s*(?P<hi>\S+)",
    re.IGNORECASE | re.MULTILINE,
)
_OMP_DO_ALREADY = re.compile(r"!\$OMP\s+PARALLEL\s+DO", re.IGNORECASE | re.MULTILINE)


class FortranOpenMPDoRule(TransformRule):
    """
    Insert ``!$OMP PARALLEL DO SCHEDULE(STATIC)`` before parallelisable DO loops.
    Also inserts ``!$OMP END PARALLEL DO`` after the ENDDO.
    """

    supported_languages = {"fortran"}

    @property
    def name(self) -> str:
        return "fortran_openmp_do"

    @property
    def transform_kind(self) -> TransformKind:
        return TransformKind.OPENMP_PARALLELISE

    def applies(self, ctx: RuleContext) -> bool:
        if ctx.language != "fortran":
            return False
        if ctx.hardware.total_cores < 2:
            return False
        if _OMP_DO_ALREADY.search(ctx.source):
            return False
        return bool(_DO_LOOP.search(ctx.source))

    def apply(self, ctx: RuleContext) -> Optional[tuple[str, list[Patch]]]:
        src_lines = ctx.source.splitlines()

        # 1. Compute, for every DO line, its matching END DO line and nesting depth.
        do_stack: list[int] = []
        match_end: dict[int, int] = {}     # do_line_idx -> enddo_line_idx
        depth_of:  dict[int, int] = {}     # do_line_idx -> nesting depth (0=outermost)

        for i, line in enumerate(src_lines):
            if re.match(r"^\s*DO\s+\w+\s*=", line, re.IGNORECASE):
                depth_of[i] = len(do_stack)
                do_stack.append(i)
            elif re.match(r"^\s*(?:ENDDO|END\s+DO)\b", line, re.IGNORECASE):
                if do_stack:
                    open_i = do_stack.pop()
                    match_end[open_i] = i

        # 2. Keep only OUTERMOST loops (depth 0) that have a matched END DO.
        outermost = [i for i in sorted(match_end) if depth_of.get(i) == 0]
        if not outermost:
            return None

        # 3. Build insertion list (pragma before DO, END PARALLEL DO after ENDDO).
        #    Limit to first 3 independent nests to keep diffs readable.
        inserts: dict[int, list[str]] = {}    # line_idx -> lines to insert BEFORE it
        after:   dict[int, list[str]] = {}    # line_idx -> lines to insert AFTER it
        patches = []

        for do_i in outermost[:3]:
            indent = re.match(r"^(\s*)", src_lines[do_i]).group(1)
            end_i  = match_end[do_i]
            inserts.setdefault(do_i, []).append(f"{indent}!$OMP PARALLEL DO SCHEDULE(STATIC)")
            after.setdefault(end_i, []).append(f"{indent}!$OMP END PARALLEL DO")
            lineno = do_i + 1
            patches.append(Patch(
                transform_kind=TransformKind.OPENMP_PARALLELISE,
                description=f"Add !$OMP PARALLEL DO at line {lineno}",
                original_snippet=src_lines[do_i].strip(),
                optimized_snippet=f"!$OMP PARALLEL DO SCHEDULE(STATIC)\n{src_lines[do_i].strip()}",
                start_line=lineno, end_line=match_end[do_i] + 1,
                rationale=(
                    f"Target: {ctx.hardware.total_cores} cores. Only the outermost "
                    "DO loop of the nest is parallelised, with a correctly paired "
                    "!$OMP END PARALLEL DO."
                ),
                expected_speedup=f"up to {min(ctx.hardware.total_cores, 32)}×",
            ))

        # 4. Rebuild the source with insertions, preserving order.
        out: list[str] = []
        for i, line in enumerate(src_lines):
            for pre in inserts.get(i, []):
                out.append(pre)
            out.append(line)
            for post in after.get(i, []):
                out.append(post)

        result = "\n".join(out)
        if ctx.source.endswith("\n"):
            result += "\n"
        return result, patches


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 3 — Add !$OMP SIMD to innermost DO loops
# ═══════════════════════════════════════════════════════════════════════════════

_OMP_SIMD_F = re.compile(r"!\$OMP\s+SIMD", re.IGNORECASE | re.MULTILINE)

# Match innermost DO (indented more than 4 spaces — a rough heuristic)
_INNER_DO = re.compile(
    r"^(?P<indent>[ \t]{4,})DO\s+\w+\s*=",
    re.IGNORECASE | re.MULTILINE,
)


class FortranOpenMPSIMDRule(TransformRule):
    """Add ``!$OMP SIMD`` before inner DO loops to hint the vectoriser."""

    supported_languages = {"fortran"}

    @property
    def name(self) -> str:
        return "fortran_omp_simd"

    @property
    def transform_kind(self) -> TransformKind:
        return TransformKind.OPENMP_SIMD

    def applies(self, ctx: RuleContext) -> bool:
        if ctx.language != "fortran":
            return False
        if _OMP_SIMD_F.search(ctx.source):
            return False
        return bool(ctx.hardware.simd) and bool(_INNER_DO.search(ctx.source))

    def apply(self, ctx: RuleContext) -> Optional[tuple[str, list[Patch]]]:
        lines   = ctx.source.splitlines(keepends=True)
        patches = []
        offset  = 0

        for m in list(_INNER_DO.finditer(ctx.source))[:4]:
            lineno = ctx.source[: m.start()].count("\n") + 1
            indent = m.group("indent")
            idx    = lineno - 1 + offset
            prev   = lines[idx - 1].strip() if idx > 0 else ""
            if "!$OMP" in prev.upper():
                continue
            pragma = f"{indent}!$OMP SIMD\n"
            lines.insert(idx, pragma)
            offset += 1
            patches.append(Patch(
                transform_kind=TransformKind.OPENMP_SIMD,
                description=f"Add !$OMP SIMD at inner DO loop line {lineno}",
                original_snippet=m.group(0),
                optimized_snippet=pragma + m.group(0),
                start_line=lineno, end_line=lineno,
                rationale=(
                    f"SIMD: {ctx.hardware.simd.instruction_set if ctx.hardware.simd else 'SSE'}. "
                    "Directive hints the vectoriser to generate SIMD instructions."
                ),
                expected_speedup="2–8×",
            ))

        if not patches:
            return None
        return "".join(lines), patches


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 4 — Fortran MPI blocking → non-blocking
# ═══════════════════════════════════════════════════════════════════════════════

_F_MPI_SEND = re.compile(r"CALL\s+MPI_SEND\s*\([^)]+\)", re.IGNORECASE)
_F_MPI_RECV = re.compile(r"CALL\s+MPI_RECV\s*\([^)]+\)", re.IGNORECASE)


class FortranMPINonBlockingRule(TransformRule):
    """Convert Fortran MPI_SEND/MPI_RECV to MPI_ISEND/MPI_IRECV + MPI_WAITALL."""

    supported_languages = {"fortran"}

    @property
    def name(self) -> str:
        return "fortran_mpi_nonblocking"

    @property
    def transform_kind(self) -> TransformKind:
        return TransformKind.MPI_NONBLOCKING

    def applies(self, ctx: RuleContext) -> bool:
        return ctx.language == "fortran" and (
            bool(_F_MPI_SEND.search(ctx.source)) or
            bool(_F_MPI_RECV.search(ctx.source))
        )

    def apply(self, ctx: RuleContext) -> Optional[tuple[str, list[Patch]]]:
        source = ctx.source

        # Count sends and recvs first (needed for array sizes).
        ns = len(_F_MPI_SEND.findall(source))
        nr = len(_F_MPI_RECV.findall(source))
        n  = ns + nr
        if n == 0:
            return None

        # Convert MPI_SEND → MPI_ISEND with request args.
        req_idx = [0]   # list to allow mutation inside lambda

        def _send_repl(m: re.Match) -> str:
            req_idx[0] += 1
            return (m.group(0)
                    .replace("MPI_SEND", "MPI_ISEND", 1)
                    .rstrip(")")
                    + f", req({req_idx[0]}), err)")

        def _recv_repl(m: re.Match) -> str:
            req_idx[0] += 1
            return (m.group(0)
                    .replace("MPI_RECV", "MPI_IRECV", 1)
                    .replace("MPI_STATUS_IGNORE", "")
                    .rstrip(")")
                    + f", req({req_idx[0]}), err)")

        source = _F_MPI_SEND.sub(_send_repl, source)
        source = _F_MPI_RECV.sub(_recv_repl, source)

        # Insert INTEGER declarations after the FIRST *code-level* IMPLICIT NONE
        # (i.e. not one that appears only inside a comment or string).
        decl    = f"    INTEGER :: req({n}), err({n})\n"
        waitall = f"\n    CALL MPI_WAITALL({n}, req, MPI_STATUSES_IGNORE, err)\n"

        # Find IMPLICIT NONE that is a real statement (not in a comment: line
        # must not start with ! before the keyword on the same source line).
        impl_re = re.compile(r"^(?P<indent>[ \t]*)IMPLICIT\s+NONE[ \t]*$",
                             re.IGNORECASE | re.MULTILINE)
        impl_m = None
        for m in impl_re.finditer(source):
            # Check the line doesn't start with a comment marker
            line_start = source.rfind("\n", 0, m.start()) + 1
            prefix = source[line_start: m.start()]
            if "!" not in prefix:
                impl_m = m
                break

        if impl_m:
            pos = impl_m.end()
            source = source[:pos] + "\n" + decl + source[pos:]
        else:
            # No IMPLICIT NONE found — prepend to subroutine/program body
            first_sub = re.search(
                r"^([ \t]*(?:SUBROUTINE|PROGRAM|FUNCTION)\s+\w+[^\n]*\n)",
                source, re.IGNORECASE | re.MULTILINE,
            )
            if first_sub:
                pos = first_sub.end()
                source = source[:pos] + decl + source[pos:]

        # Insert MPI_WAITALL before the last END SUBROUTINE/PROGRAM/FUNCTION.
        # Use a newline prefix so it is always on its own line, not appended to
        # whatever precedes the END statement (e.g. an !$OMP END PARALLEL DO).
        # Also add USE mpi in the same scope if it isn't already there, because
        # MPI_STATUSES_IGNORE requires it to be defined.
        use_mpi_line = "    USE mpi\n"
        waitall_line = f"    CALL MPI_WAITALL({n}, req, MPI_STATUSES_IGNORE, err)\n"

        # Find the PROGRAM/SUBROUTINE block that contains the END we're targeting.
        end_m = re.search(
            r"\n([ \t]*)(?:END\s+PROGRAM|END\s+SUBROUTINE|END\s+FUNCTION)\b",
            source, flags=re.IGNORECASE,
        )
        if end_m:
            # Check if USE mpi is already present in the surrounding block.
            block_start = max(0, end_m.start() - 2000)
            block = source[block_start: end_m.start()]
            if not re.search(r"^\s*USE\s+mpi\b", block, re.IGNORECASE | re.MULTILINE):
                # Find the subroutine/program header to inject USE mpi after it.
                header_m = re.search(
                    r"(^[ \t]*(?:PROGRAM|SUBROUTINE|FUNCTION)\s+\w+[^\n]*\n)",
                    source[block_start:], re.IGNORECASE | re.MULTILINE,
                )
                if header_m:
                    ins_pos = block_start + header_m.end()
                    source = source[:ins_pos] + use_mpi_line + source[ins_pos:]
                    # Re-find end_m after insertion
                    end_m = re.search(
                        r"\n([ \t]*)(?:END\s+PROGRAM|END\s+SUBROUTINE|END\s+FUNCTION)\b",
                        source, flags=re.IGNORECASE,
                    )

        source = re.sub(
            r"(\n)([ \t]*(?:END\s+PROGRAM|END\s+SUBROUTINE|END\s+FUNCTION)\b)",
            "\n" + waitall_line + r"\1\2",
            source, count=1, flags=re.IGNORECASE,
        )

        return source, [Patch(
            transform_kind=TransformKind.MPI_NONBLOCKING,
            description=f"Convert {n} Fortran MPI blocking calls to non-blocking",
            original_snippet="CALL MPI_SEND/MPI_RECV",
            optimized_snippet="CALL MPI_ISEND/MPI_IRECV + MPI_WAITALL",
            start_line=1, end_line=len(source.splitlines()),
            rationale=(
                "Non-blocking MPI enables overlapping communication with computation. "
                "Critical for scaling beyond 8 MPI ranks."
            ),
            expected_speedup="1.3–3× on communication-bound kernels",
        )]
