"""Dispatch scan requests to the appropriate language scanner."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from perflens.scanner.models import Finding

_EXT_MAP = {
    ".c":    "c",
    ".h":    "c",
    ".cpp":  "cpp",
    ".cxx":  "cpp",
    ".cc":   "cpp",
    ".hpp":  "cpp",
    ".f":    "fortran",
    ".f90":  "fortran",
    ".f95":  "fortran",
    ".f03":  "fortran",
    ".f08":  "fortran",
    ".for":  "fortran",
    ".py":   "python",
}


def detect_language(path: Path) -> str:
    return _EXT_MAP.get(path.suffix.lower(), "unknown")


def scan_file(
    source: Path,
    language: Optional[str] = None,
    verbose: bool = False,
) -> list[Finding]:
    """Route *source* to the correct scanner and return findings."""

    if not source.exists():
        raise FileNotFoundError(f"Source not found: {source}")

    lang = language or detect_language(source)

    if lang in ("c", "cpp"):
        from perflens.scanner.clang_scanner import ClangScanner
        return ClangScanner(verbose=verbose).scan(source, language=lang)

    elif lang == "fortran":
        from perflens.scanner.fortran_scanner import FortranScanner
        return FortranScanner(verbose=verbose).scan(source)

    elif lang == "python":
        from perflens.scanner.python_scanner import PythonScanner
        return PythonScanner(verbose=verbose).scan(source)

    else:
        raise ValueError(f"Unsupported language '{lang}' for file: {source}")
