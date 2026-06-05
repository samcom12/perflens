"""
PerfLens compiler feedback module.

Parses compiler optimization reports from GCC, Clang, and ICX to
surface vectorization misses, aliasing issues, and inlining failures.
The remarks are fed into the LLM prompt as additional context.

Usage::

    from perflens.compiler_feedback import collect_feedback

    report = collect_feedback(Path("solver.c"), compiler="gcc")
    report.print_summary(console)
    hints = report.to_scanner_hints()   # list[str] injected into LLM prompt
"""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Optional

from perflens.compiler_feedback.models import CompilerFeedbackReport, FeedbackKind, CompilerRemark


def collect_feedback(
    source: Path,
    compiler: Optional[str] = None,
    report_file: Optional[Path] = None,
    extra_flags: Optional[list[str]] = None,
) -> CompilerFeedbackReport:
    """
    Collect compiler optimization feedback for *source*.

    If *report_file* is provided, parse it directly.
    Otherwise, compile the source with the best available compiler and
    capture its optimization remarks.

    Compiler auto-detection order: icx → clang → gcc
    """
    # Detect compiler if not specified
    if compiler is None:
        for candidate in ("icx", "clang", "gcc"):
            if shutil.which(candidate):
                compiler = candidate
                break
        else:
            compiler = "gcc"   # fallback even if not found (returns empty report)

    compiler = compiler.lower()

    if compiler in ("gcc", "gfortran", "g++"):
        from perflens.compiler_feedback.gcc_parser import GCCFeedbackParser
        p = GCCFeedbackParser()
        if report_file:
            return p.parse_file(report_file, source)
        return p.compile_and_parse(source, extra_flags=extra_flags, compiler=compiler)

    elif compiler in ("clang", "clang++"):
        from perflens.compiler_feedback.clang_parser import ClangFeedbackParser
        p = ClangFeedbackParser()
        if report_file:
            return p.parse_file(report_file, source)
        return p.compile_and_parse(source, extra_flags=extra_flags, compiler=compiler)

    elif compiler in ("icx", "icpx", "ifort", "ifx"):
        from perflens.compiler_feedback.clang_parser import ICXFeedbackParser
        p = ICXFeedbackParser()
        if report_file:
            return p.parse_file(report_file, source)
        return p.compile_and_parse(source, extra_flags=extra_flags, compiler=compiler)

    else:
        return CompilerFeedbackReport(source=source, compiler=compiler)


__all__ = [
    "collect_feedback",
    "CompilerFeedbackReport",
    "CompilerRemark",
    "FeedbackKind",
]
