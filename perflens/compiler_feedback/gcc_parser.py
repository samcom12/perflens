"""
GCC Optimization Report Parser.

GCC emits per-loop vectorization / missed-optimization remarks via:
    gcc -O3 -fopt-info-vec-missed -fopt-info-vec-optimized solver.c

Output lines look like:
    solver.c:42:5: optimized: loop vectorized using 32-byte vectors
    solver.c:87:9: missed: couldn't vectorize loop
    solver.c:87:9: note: not vectorized: multiple loop exits.
    solver.c:100:5: optimized: loop unrolled 4 times

We also parse `-fopt-info-loop` and `-fopt-info-inline` output.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from perflens.compiler_feedback.models import (
    CompilerFeedbackReport,
    CompilerRemark,
    FeedbackKind,
)

# ── Pattern matching for GCC opt-info lines ───────────────────────────────────

# file.c:LINE:COL: [optimized|missed|note]: message
_GCC_LINE = re.compile(
    r"^(?P<file>[^:]+):(?P<line>\d+):(?P<col>\d+):\s+"
    r"(?P<level>optimized|missed|note):\s+(?P<msg>.+)$"
)

_PASS_KEYWORDS: dict[str, FeedbackKind] = {
    "loop vectorized":           FeedbackKind.VECTORIZED,
    "vectorized using":          FeedbackKind.VECTORIZED,
    "couldn't vectorize":        FeedbackKind.NOT_VECTORIZED,
    "not vectorized":            FeedbackKind.NOT_VECTORIZED,
    "loop unrolled":             FeedbackKind.LOOP_UNROLLED,
    "loop distributed":          FeedbackKind.LOOP_DISTRIBUTED,
    "inlined":                   FeedbackKind.INLINED,
    "not inlined":               FeedbackKind.NOT_INLINED,
    "multiple loop exits":       FeedbackKind.DEPENDENCY,
    "data dependence":           FeedbackKind.DEPENDENCY,
    "alias":                     FeedbackKind.ALIAS_CHECK,
    "restrict":                  FeedbackKind.ALIAS_CHECK,
    "auto-parallelization":      FeedbackKind.AUTO_PARALLELIZED,
}


def _classify(msg: str, level: str) -> tuple[FeedbackKind, str]:
    msg_lower = msg.lower()
    for keyword, kind in _PASS_KEYWORDS.items():
        if keyword in msg_lower:
            return kind, keyword.replace(" ", "-")
    if level == "optimized":
        return FeedbackKind.VECTORIZED, "general-opt"
    if level == "missed":
        return FeedbackKind.NOT_VECTORIZED, "general-missed"
    return FeedbackKind.GENERAL, "note"


class GCCFeedbackParser:
    """
    Parse GCC -fopt-info output (text format).

    Can either:
    a) Parse an existing log file (``parse_file``)
    b) Compile the source with GCC in a temp dir and capture remarks (``compile_and_parse``)
    """

    def parse_file(self, path: Path, source: Path) -> CompilerFeedbackReport:
        text = path.read_text(errors="replace")
        return self._parse_text(text, source=source)

    def compile_and_parse(
        self,
        source: Path,
        extra_flags: Optional[list[str]] = None,
        compiler: str = "gcc",
    ) -> CompilerFeedbackReport:
        """Compile *source* with GCC and capture opt-info remarks."""
        if not shutil.which(compiler):
            return CompilerFeedbackReport(source=source, compiler=compiler)

        flags = [
            "-O3", "-march=native", "-fopenmp",
            "-fopt-info-vec-optimized",
            "-fopt-info-vec-missed",
            "-fopt-info-loop",
        ] + (extra_flags or [])

        with tempfile.NamedTemporaryFile(suffix=".o", delete=True) as obj:
            cmd = [compiler] + flags + ["-c", str(source), "-o", obj.name]
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=60
                )
                # GCC writes opt-info to stderr
                feedback_text = proc.stderr
            except subprocess.TimeoutExpired:
                return CompilerFeedbackReport(source=source, compiler=compiler)

        report = self._parse_text(feedback_text, source=source)
        report.flags_used = flags
        return report

    def _parse_text(self, text: str, source: Path) -> CompilerFeedbackReport:
        remarks: list[CompilerRemark] = []

        for raw_line in text.splitlines():
            m = _GCC_LINE.match(raw_line.strip())
            if not m:
                continue
            kind, pass_name = _classify(m.group("msg"), m.group("level"))
            remarks.append(CompilerRemark(
                source_file=m.group("file"),
                line=int(m.group("line")),
                col=int(m.group("col")),
                kind=kind,
                compiler="gcc",
                pass_name=pass_name,
                message=m.group("msg").strip(),
            ))

        return CompilerFeedbackReport(
            source=source,
            compiler="gcc",
            remarks=sorted(remarks, key=lambda r: r.line),
        )
