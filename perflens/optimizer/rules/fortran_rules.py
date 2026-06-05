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
        lines   = ctx.source.splitlines(keepends=True)
        patches = []
        offset  = 0

        matches = list(_DO_LOOP.finditer(ctx.source))[:3]   # first 3 loops only

        for m in matches:
            lineno = ctx.source[: m.start()].count("\n") + 1
            indent = m.group("indent")
            idx    = lineno - 1 + offset

            # Don't duplicate
            prev = lines[idx - 1].strip() if idx > 0 else ""
            if "!$OMP" in prev.upper():
                continue

            pragma = f"{indent}!$OMP PARALLEL DO SCHEDULE(STATIC)\n"
            lines.insert(idx, pragma)
            offset += 1

            # Find matching ENDDO/END DO and insert END PARALLEL DO
            depth = 1
            for j in range(idx + 1, len(lines)):
                if re.match(r"^\s*DO\b", lines[j], re.IGNORECASE):
                    depth += 1
                if re.match(r"^\s*(?:ENDDO|END\s+DO)\b", lines[j], re.IGNORECASE):
                    depth -= 1
                    if depth == 0:
                        lines.insert(j + 1, f"{indent}!$OMP END PARALLEL DO\n")
                        offset += 1
                        break

            patches.append(Patch(
                transform_kind=TransformKind.OPENMP_PARALLELISE,
                description=f"Add !$OMP PARALLEL DO at line {lineno}",
                original_snippet=m.group(0),
                optimized_snippet=pragma + m.group(0),
                start_line=lineno, end_line=lineno,
                rationale=(
                    f"Target: {ctx.hardware.total_cores} cores. "
                    "OpenMP parallelises the DO loop across all available threads."
                ),
                expected_speedup=f"up to {min(ctx.hardware.total_cores, 32)}×",
            ))

        if not patches:
            return None
        return "".join(lines), patches


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
        n = 0
        source, ns = _F_MPI_SEND.subn(
            lambda m: m.group(0)
                .replace("MPI_SEND", "MPI_ISEND", 1)
                .rstrip(")")
                + f", req({n+1}, err)",
            source,
        )
        n += ns
        source, nr = _F_MPI_RECV.subn(
            lambda m: m.group(0)
                .replace("MPI_RECV", "MPI_IRECV", 1)
                .replace("MPI_STATUS_IGNORE", "")
                .rstrip(")")
                + f", req({n+1}, err)",
            source,
        )
        n += nr
        if n == 0:
            return None

        # Add request declaration and waitall (best-effort, before END PROGRAM/SUBROUTINE)
        decl    = f"    INTEGER :: req({n}), err({n})\n"
        waitall = f"    CALL MPI_WAITALL({n}, req, MPI_STATUSES_IGNORE, err)\n"
        source  = re.sub(r"(IMPLICIT NONE\n)", r"\1" + decl, source, count=1, flags=re.IGNORECASE)
        source  = re.sub(
            r"(\n\s*(?:END\s+PROGRAM|END\s+SUBROUTINE|END\s+FUNCTION))",
            waitall + r"\1",
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
