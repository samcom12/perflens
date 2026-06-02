"""Data models for profiler output."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Any

from rich.console import Console
from rich.table import Table
from rich import box


@dataclass
class Hotspot:
    """A single hot function / loop region from profiler output."""
    function: str
    module: str
    source_file: Optional[str]
    start_line: int
    cpu_time_pct: float        # % of total CPU time
    cpu_time_ms: float         # absolute ms
    cpi: Optional[float]       # Cycles per instruction
    llc_miss_rate: Optional[float]  # L3 cache miss rate (0–1)
    mem_bound_pct: Optional[float]  # Memory-bound % from Top-Down
    compute_bound_pct: Optional[float]
    vectorization_pct: Optional[float]  # % of time in vector instructions
    gflops: Optional[float]    # measured GFLOP/s for this region
    arithmetic_intensity: Optional[float]  # FLOP/byte for roofline
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if not k.startswith("_")}


@dataclass
class RooflinePoint:
    """A single data point on the roofline model."""
    label: str
    arithmetic_intensity: float   # FLOP/byte
    achieved_gflops: float
    peak_gflops: Optional[float] = None
    peak_bandwidth_gbs: Optional[float] = None


@dataclass
class ProfileData:
    """Aggregated profile data from one profiler run."""
    tool: str                  # "vtune" | "hpctoolkit"
    source: Optional[Path]
    report_path: Optional[Path]
    total_time_ms: float
    hotspots: list[Hotspot] = field(default_factory=list)
    roofline_points: list[RooflinePoint] = field(default_factory=list)
    raw_metadata: dict[str, Any] = field(default_factory=dict)

    def top_hotspots(self, n: int = 10) -> list[Hotspot]:
        return sorted(self.hotspots, key=lambda h: h.cpu_time_pct, reverse=True)[:n]

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "source": str(self.source) if self.source else None,
            "report_path": str(self.report_path) if self.report_path else None,
            "total_time_ms": self.total_time_ms,
            "hotspots": [h.to_dict() for h in self.hotspots],
            "roofline_points": [r.__dict__ for r in self.roofline_points],
            "raw_metadata": self.raw_metadata,
        }

    def print_summary(self, console: Console, top_n: int = 10) -> None:
        console.print(f"\n[bold]Profile Summary[/bold] ({self.tool.upper()})")
        console.print(f"  Total time: [cyan]{self.total_time_ms:.1f} ms[/cyan]")
        console.print(f"  Hotspots:   {len(self.hotspots)}")

        if not self.hotspots:
            console.print("[dim]  No hotspot data available.[/dim]")
            return

        table = Table(title=f"Top {top_n} Hotspots", box=box.ROUNDED, show_lines=True)
        table.add_column("Rank",        width=5,  justify="right")
        table.add_column("Function",    width=35)
        table.add_column("CPU %",       width=8,  justify="right")
        table.add_column("Time (ms)",   width=10, justify="right")
        table.add_column("CPI",         width=6,  justify="right")
        table.add_column("LLC Miss%",   width=10, justify="right")
        table.add_column("Mem-Bound%",  width=11, justify="right")
        table.add_column("Vec%",        width=6,  justify="right")
        table.add_column("AI (F/B)",    width=10, justify="right")

        for rank, h in enumerate(self.top_hotspots(top_n), 1):
            pct_color = "red" if h.cpu_time_pct > 20 else "yellow" if h.cpu_time_pct > 5 else "green"
            table.add_row(
                str(rank),
                h.function[:34],
                f"[{pct_color}]{h.cpu_time_pct:.1f}%[/{pct_color}]",
                f"{h.cpu_time_ms:.1f}",
                f"{h.cpi:.2f}"       if h.cpi       is not None else "—",
                f"{h.llc_miss_rate*100:.1f}%" if h.llc_miss_rate is not None else "—",
                f"{h.mem_bound_pct:.1f}%"     if h.mem_bound_pct is not None else "—",
                f"{h.vectorization_pct:.1f}%" if h.vectorization_pct is not None else "—",
                f"{h.arithmetic_intensity:.2f}" if h.arithmetic_intensity is not None else "—",
            )
        console.print(table)
