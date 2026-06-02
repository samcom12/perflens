"""PerfLens static analysis scanner — Clang AST + language-specific parsers."""

from perflens.scanner.models import Finding, FindingKind, Severity
from perflens.scanner.dispatcher import scan_file

__all__ = ["scan_file", "Finding", "FindingKind", "Severity"]
