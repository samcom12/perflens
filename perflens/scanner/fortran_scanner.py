"""
Fortran static analysis scanner.

Uses fparser2 when available for AST-level analysis; falls back to line-by-line
regex heuristics for common HPC anti-patterns.
"""

from __future__ import annotations

import re
from pathlib import Path

from perflens.scanner.models import Finding, FindingKind, Severity

try:
    from fparser.two.parser import ParserFactory
    from fparser.common.readfortran import FortranStringReader
    import fparser.two.Fortran2003 as F2003
    _FPARSER_AVAILABLE = True
except ImportError:
    _FPARSER_AVAILABLE = False


# ── Regex patterns specific to Fortran ──────────────────────────────────────

_FORTRAN_PATTERNS = [
    # IMPLICIT NONE missing
    (
        re.compile(r"^\s*SUBROUTINE|FUNCTION|PROGRAM", re.IGNORECASE | re.MULTILINE),
        re.compile(r"\bIMPLICIT\s+NONE\b", re.IGNORECASE),
        FindingKind.GENERAL,
        Severity.MEDIUM,
        "Missing IMPLICIT NONE in program unit — can mask type errors and inhibit optimization",
        "Add `IMPLICIT NONE` at the top of every program unit",
    ),
]

_LINE_PATTERNS: list[tuple[re.Pattern, FindingKind, Severity, str, str]] = [
    # Temp array copy (result of elemental ops on slices)
    (
        re.compile(r"=\s*\w+\s*\(\s*:\s*\)\s*\*\s*\w+\s*\(\s*:\s*\)"),
        FindingKind.FORTRAN_ARRAY_COPY,
        Severity.MEDIUM,
        "Array expression may generate a temporary copy — check for aliasing",
        "Use `!$OMP SIMD` or refactor into explicit loop to avoid temporaries",
    ),
    # Transcendental inside DO loop  (detected when we track DO depth)
    (
        re.compile(r"\b(SIN|COS|TAN|EXP|LOG|SQRT|ASIN|ACOS|ATAN2)\s*\(", re.IGNORECASE),
        FindingKind.TRANSCENDENTAL_IN_LOOP,
        Severity.HIGH,
        "Transcendental intrinsic — may be scalar unless compiler auto-vectorizes",
        "Use explicit DO SIMD pragma or rely on -ffast-math with gfortran -O3",
    ),
    # Blocking MPI
    (
        re.compile(r"\bMPI_SEND\b|\bMPI_RECV\b|\bMPI_BARRIER\b", re.IGNORECASE),
        FindingKind.MPI_SYNCHRONOUS_HOTSPOT,
        Severity.MEDIUM,
        "Synchronous MPI call — consider non-blocking alternatives",
        "Replace MPI_SEND/MPI_RECV with MPI_ISEND/MPI_IRECV and overlap computation",
    ),
    # COMMON block usage (inhibits aliasing analysis)
    (
        re.compile(r"^\s*COMMON\s*/", re.IGNORECASE | re.MULTILINE),
        FindingKind.GENERAL,
        Severity.LOW,
        "COMMON block usage — inhibits compiler aliasing analysis",
        "Replace COMMON blocks with MODULE variables and explicit INTENT attributes",
    ),
    # Missing INTENT attributes
    (
        re.compile(r"SUBROUTINE\s+\w+\s*\([^)]+\)", re.IGNORECASE),
        FindingKind.GENERAL,
        Severity.LOW,
        "Subroutine arguments missing INTENT — compiler cannot optimize call interface",
        "Add INTENT(IN), INTENT(OUT), or INTENT(INOUT) to all dummy arguments",
    ),
    # IO inside loop — WRITE/PRINT
    (
        re.compile(r"^\s*(WRITE|PRINT)\s*[\(*]", re.IGNORECASE | re.MULTILINE),
        FindingKind.IO_IN_LOOP,
        Severity.MEDIUM,
        "WRITE/PRINT statement (may be inside DO loop)",
        "Accumulate output arrays and write outside the loop",
    ),
]


class FortranScanner:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def scan(self, path: Path) -> list[Finding]:
        source = path.read_text(errors="replace")
        findings: list[Finding] = []

        findings.extend(self._line_scan(path, source))
        if _FPARSER_AVAILABLE:
            findings.extend(self._fparser_scan(path, source))
        elif self.verbose:
            print("[perflens] fparser2 not available — using line-scanner only")

        # Deduplicate
        seen: set[tuple[int, str]] = set()
        result = []
        for f in findings:
            key = (f.line, f.kind.value)
            if key not in seen:
                seen.add(key)
                result.append(f)
        return sorted(result, key=lambda f: f.line)

    # ── Line-by-line pass ──────────────────────────────────────────────────

    def _line_scan(self, path: Path, source: str) -> list[Finding]:
        findings: list[Finding] = []
        lines = source.splitlines()
        in_do_loop = False
        do_depth = 0

        for lineno, line in enumerate(lines, start=1):
            stripped = line.strip()

            # Track DO loop nesting
            if re.match(r"^\s*DO\b", line, re.IGNORECASE) and not re.match(r"^\s*ENDDO|END\s+DO", line, re.IGNORECASE):
                do_depth += 1
                in_do_loop = True
            if re.match(r"^\s*(ENDDO|END\s+DO)\b", line, re.IGNORECASE):
                do_depth = max(0, do_depth - 1)
                in_do_loop = do_depth > 0

            for pattern, kind, severity, message, suggestion in _LINE_PATTERNS:
                if pattern.search(line):
                    # Elevate severity when we're inside a DO loop
                    eff_severity = (
                        Severity.HIGH if in_do_loop and severity == Severity.MEDIUM else severity
                    )
                    ctx = lines[max(0, lineno - 2) : lineno + 2]
                    findings.append(Finding(
                        file=path, line=lineno, col=0,
                        kind=kind, severity=eff_severity,
                        message=f"[DO depth={do_depth}] {message}" if in_do_loop else message,
                        suggestion=suggestion,
                        context_lines=ctx,
                        metadata={"do_depth": do_depth},
                    ))
                    break  # one finding per line

            # Check for nested DO loops ≥ 3 deep → tiling opportunity
            if do_depth >= 3 and re.match(r"^\s*DO\b", line, re.IGNORECASE):
                findings.append(Finding(
                    file=path, line=lineno, col=0,
                    kind=FindingKind.LOOP_TILING_OPPORTUNITY,
                    severity=Severity.HIGH,
                    message=f"Triple-nested DO loop (depth={do_depth}) — loop tiling can improve cache reuse",
                    suggestion="Tile the two outermost loops with block size ≈ sqrt(L1_cache / sizeof(element))",
                    metadata={"do_depth": do_depth},
                ))

        return findings

    # ── fparser2 AST pass ─────────────────────────────────────────────────

    def _fparser_scan(self, path: Path, source: str) -> list[Finding]:
        findings: list[Finding] = []
        try:
            parser = ParserFactory().create(std="f2003")
            reader = FortranStringReader(source, ignore_comments=True)
            tree = parser(reader)
            self._walk_fparser(tree, path, findings)
        except Exception as exc:
            if self.verbose:
                print(f"[perflens] fparser2 parse error: {exc}")
        return findings

    def _walk_fparser(self, node, path: Path, findings: list[Finding]) -> None:
        if node is None:
            return
        # Detect subroutine/function without IMPLICIT NONE
        if isinstance(node, (F2003.Subroutine_Subprogram, F2003.Function_Subprogram)):
            body_str = str(node)
            if "IMPLICIT NONE" not in body_str.upper():
                # Try to get line number from first token
                lineno = getattr(getattr(node, "item", None), "span", (1, 1))[0]
                findings.append(Finding(
                    file=path, line=lineno, col=0,
                    kind=FindingKind.GENERAL,
                    severity=Severity.MEDIUM,
                    message="Program unit missing IMPLICIT NONE",
                    suggestion="Add `IMPLICIT NONE` immediately after the SUBROUTINE/FUNCTION statement",
                ))

        # Recurse
        for child in (getattr(node, "children", None) or []):
            self._walk_fparser(child, path, findings)
