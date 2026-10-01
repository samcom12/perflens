"""Data models for compiler optimization feedback."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich import box

from perflens.source_regions import find_loop_regions


class FeedbackKind(str, Enum):
    VECTORIZED          = "vectorized"
    NOT_VECTORIZED      = "not_vectorized"
    INLINED             = "inlined"
    NOT_INLINED         = "not_inlined"
    LOOP_DISTRIBUTED    = "loop_distributed"
    LOOP_UNROLLED       = "loop_unrolled"
    AUTO_PARALLELIZED   = "auto_parallelized"
    ALIAS_CHECK         = "alias_check"        # loop not vectorized due to aliasing
    DEPENDENCY          = "dependency"         # carried loop dependency
    GENERAL             = "general"


@dataclass
class CompilerRemark:
    """One diagnostic line from a compiler optimization report."""
    source_file: Optional[str]
    line: int
    col: int
    kind: FeedbackKind
    compiler: str          # "gcc" | "clang" | "icx"
    pass_name: str         # e.g. "loop-vectorize", "inline"
    message: str
    hotspot: bool = False  # True if this line is a profiler hotspot

    def to_dict(self) -> dict:
        return {
            "file": self.source_file,
            "line": self.line,
            "col": self.col,
            "kind": self.kind.value,
            "compiler": self.compiler,
            "pass": self.pass_name,
            "message": self.message,
            "hotspot": self.hotspot,
        }


@dataclass
class CompilerFeedbackReport:
    """Aggregated compiler feedback for one source file."""
    source: Path
    compiler: str
    flags_used: list[str] = field(default_factory=list)
    remarks: list[CompilerRemark] = field(default_factory=list)

    @property
    def vectorized_loops(self) -> list[CompilerRemark]:
        return [r for r in self.remarks if r.kind == FeedbackKind.VECTORIZED]

    @property
    def missed_vectorization(self) -> list[CompilerRemark]:
        return [r for r in self.remarks if r.kind == FeedbackKind.NOT_VECTORIZED]

    @property
    def missed_vectorization_count(self) -> int:
        try:
            source_text = self.source.read_text(errors="replace")
        except OSError:
            source_text = ""
        regions = find_loop_regions(source_text)
        keys: set[tuple[Optional[str], int, int]] = set()
        for remark in self.missed_vectorization:
            containing = [
                region for region in regions
                if region.header_line <= remark.line <= source_text.count(
                    "\n", 0, region.end_offset
                ) + 1
            ]
            if containing:
                region = min(containing, key=lambda item: item.end_offset - item.start_offset)
                keys.add((remark.source_file, region.header_line, region.header_col))
            else:
                keys.add((remark.source_file, remark.line, remark.col))
        return len(keys)

    @property
    def alias_failures(self) -> list[CompilerRemark]:
        return [r for r in self.remarks if r.kind == FeedbackKind.ALIAS_CHECK]

    def to_scanner_hints(self) -> list[str]:
        """Translate compiler remarks into hints for the LLM prompt."""
        hints: list[str] = []
        for r in self.missed_vectorization[:10]:
            hints.append(
                f"Line {r.line}: NOT vectorized ({r.pass_name}) — {r.message}"
            )
        for r in self.alias_failures[:5]:
            hints.append(
                f"Line {r.line}: aliasing prevents vectorization — "
                "add restrict / __restrict__ keyword"
            )
        return hints

    def print_summary(self, console: Console) -> None:
        vok  = len(self.vectorized_loops)
        vmiss = self.missed_vectorization_count
        console.print(
            f"\n[bold cyan]Compiler Feedback[/bold cyan] ({self.compiler})\n"
            f"  Vectorized loops   : [green]{vok}[/green]\n"
            f"  Missed vectorization: [red]{vmiss}[/red]\n"
            f"  Aliasing failures  : [yellow]{len(self.alias_failures)}[/yellow]"
        )
        if vmiss > 0:
            table = Table(title="Missed Vectorization", box=box.SIMPLE)
            table.add_column("Line", width=6, justify="right")
            table.add_column("Pass", width=18)
            table.add_column("Reason")
            for r in self.missed_vectorization[:15]:
                table.add_row(str(r.line), r.pass_name, r.message[:80])
            console.print(table)
