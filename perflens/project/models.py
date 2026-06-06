"""
Data models for whole-project analysis and optimization.

A HPC codebase is modelled as a ProjectGraph:
  - Nodes  : SourceFile (one per .c/.cpp/.f90/.py file)
  - Edges  : include / import / call dependencies between files
  - Context: per-file hotspot score, compiler feedback, scanner findings

The ProjectOptimizer uses these models to:
  1. Rank files by priority (hotspot × compiler-miss × scanner severity)
  2. Optimize in dependency order (leaves first, then callers)
  3. Validate after each batch
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional, Any

from rich.console import Console
from rich.table import Table
from rich import box


# ── Build system types ────────────────────────────────────────────────────────

class BuildSystem(str, Enum):
    CMAKE    = "cmake"
    MAKE     = "make"
    MESON    = "meson"
    AUTOCONF = "autoconf"
    SCONS    = "scons"
    BARE     = "bare"       # no build system — compile files directly
    PYTHON   = "python"     # pure-Python project (setup.py / pyproject.toml)


# ── Per-file models ───────────────────────────────────────────────────────────

@dataclass
class CompileCommand:
    """Compiler invocation for one source file (from compile_commands.json or inferred)."""
    file:      Path
    directory: Path
    command:   str
    arguments: list[str] = field(default_factory=list)

    @property
    def compiler(self) -> str:
        if self.arguments:
            return Path(self.arguments[0]).name
        return Path(self.command.split()[0]).name if self.command else "cc"

    @property
    def flags(self) -> list[str]:
        return self.arguments[1:] if len(self.arguments) > 1 else self.command.split()[1:]


@dataclass
class SourceFile:
    """One source file inside the project graph."""
    path:     Path
    language: str           # c | cpp | fortran | python

    # Dependency edges (populated by crawler)
    includes:    list[Path] = field(default_factory=list)  # files this one includes/imports
    included_by: list[Path] = field(default_factory=list)  # files that include this one

    # Compiler invocation
    compile_command: Optional[CompileCommand] = None

    # Analysis results (populated by pipeline steps)
    hotspot_pct:        float = 0.0   # % of total CPU time spent here
    hotspot_lines:      list[int] = field(default_factory=list)
    scanner_findings:   list[Any]  = field(default_factory=list)   # list[Finding]
    compiler_feedback:  Optional[Any] = None   # CompilerFeedbackReport
    optimized_source:   Optional[str] = None
    optimization_patches: list[Any] = field(default_factory=list)

    @property
    def is_header(self) -> bool:
        return self.path.suffix.lower() in (".h", ".hpp", ".hxx", ".h90", ".inc")

    @property
    def priority_score(self) -> float:
        """
        Combined priority score (0–100). Higher = optimize first.
        Weights:
          60% profiler hotspot (direct CPU attribution)
          25% compiler missed vectorizations
          15% scanner high/critical findings
        """
        from perflens.scanner.models import Severity
        prof_score = self.hotspot_pct * 0.60

        miss_count = 0
        if self.compiler_feedback:
            miss_count = len(self.compiler_feedback.missed_vectorization)
        compiler_score = min(miss_count * 2.0, 25.0)

        sev_weights = {Severity.CRITICAL: 3, Severity.HIGH: 2,
                       Severity.MEDIUM: 1, Severity.LOW: 0}
        scanner_score = min(
            sum(sev_weights.get(f.severity, 0) for f in self.scanner_findings) * 0.5,
            15.0,
        )
        return prof_score + compiler_score + scanner_score

    def to_dict(self) -> dict:
        return {
            "path":           str(self.path),
            "language":       self.language,
            "hotspot_pct":    self.hotspot_pct,
            "priority_score": self.priority_score,
            "includes":       [str(p) for p in self.includes],
            "findings":       len(self.scanner_findings),
            "compiler_misses": len(self.compiler_feedback.missed_vectorization)
                               if self.compiler_feedback else 0,
            "optimized":      self.optimized_source is not None,
        }


# ── Project graph ─────────────────────────────────────────────────────────────

@dataclass
class ProjectGraph:
    """Complete project model — all source files + their relationships."""
    root:         Path
    build_system: BuildSystem
    name:         str = ""

    # Core collections
    files: dict[Path, SourceFile] = field(default_factory=dict)
    compile_commands: dict[Path, CompileCommand] = field(default_factory=dict)

    # Build artefacts
    build_dir:    Optional[Path] = None
    binary_paths: list[Path] = field(default_factory=list)

    # Build metadata
    build_flags:  list[str] = field(default_factory=list)
    cmake_options: dict[str, str] = field(default_factory=dict)

    @property
    def source_files(self) -> list[SourceFile]:
        """Non-header source files only, sorted by priority (highest first)."""
        return sorted(
            [f for f in self.files.values() if not f.is_header],
            key=lambda f: f.priority_score,
            reverse=True,
        )

    @property
    def hotspot_files(self, top_n: int = 10) -> list[SourceFile]:
        return [f for f in self.source_files if f.hotspot_pct > 0][:top_n]

    def language_breakdown(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for sf in self.files.values():
            counts[sf.language] = counts.get(sf.language, 0) + 1
        return counts

    def total_lines(self) -> int:
        total = 0
        for sf in self.files.values():
            try:
                total += sf.path.read_text(errors="replace").count("\n")
            except OSError:
                pass
        return total

    def print_summary(self, console: Console) -> None:
        lang = self.language_breakdown()
        console.print(f"\n[bold cyan]Project:[/bold cyan] {self.name or self.root.name}")
        console.print(f"  Root        : {self.root}")
        console.print(f"  Build system: [yellow]{self.build_system.value}[/yellow]")
        console.print(f"  Source files: {len(self.source_files)}")
        console.print(f"  Languages   : " +
                      "  ".join(f"[cyan]{k}={v}[/cyan]" for k, v in sorted(lang.items())))
        console.print(f"  Total lines : {self.total_lines():,}")
        if self.build_dir:
            console.print(f"  Build dir   : {self.build_dir}")

    def print_file_table(self, console: Console, top_n: int = 20) -> None:
        table = Table(title="Project Files — Optimization Priority",
                      box=box.ROUNDED, show_lines=True)
        table.add_column("File",       width=35)
        table.add_column("Lang",       width=8)
        table.add_column("Hotspot%",   width=10, justify="right")
        table.add_column("Priority",   width=10, justify="right")
        table.add_column("Findings",   width=10, justify="right")
        table.add_column("Cmp Misses", width=11, justify="right")
        table.add_column("Optimized",  width=10, justify="center")

        for sf in self.source_files[:top_n]:
            miss = (len(sf.compiler_feedback.missed_vectorization)
                    if sf.compiler_feedback else "—")
            opt  = "[green]✓[/green]" if sf.optimized_source else "—"
            pct_color = ("red" if sf.hotspot_pct > 20
                         else "yellow" if sf.hotspot_pct > 5 else "dim")
            table.add_row(
                sf.path.name[:34],
                sf.language,
                f"[{pct_color}]{sf.hotspot_pct:.1f}%[/{pct_color}]",
                f"{sf.priority_score:.1f}",
                str(len(sf.scanner_findings)),
                str(miss),
                opt,
            )
        console.print(table)


# ── Optimization plan ─────────────────────────────────────────────────────────

@dataclass
class OptimizationPhase:
    """A batch of files to optimize together."""
    phase_id:  int
    files:     list[SourceFile]
    reason:    str
    backend:   str = "rules"

    @property
    def total_hotspot_pct(self) -> float:
        return sum(f.hotspot_pct for f in self.files)


@dataclass
class ProjectOptimizationPlan:
    """Ordered phases describing which files to optimize and why."""
    graph:   ProjectGraph
    phases:  list[OptimizationPhase] = field(default_factory=list)
    backend: str = "rules"

    @property
    def total_files(self) -> int:
        return sum(len(p.files) for p in self.phases)

    @property
    def covered_hotspot_pct(self) -> float:
        return sum(p.total_hotspot_pct for p in self.phases)

    def print_plan(self, console: Console) -> None:
        console.print(
            f"\n[bold]Optimization Plan[/bold]  "
            f"backend=[yellow]{self.backend}[/yellow]  "
            f"phases={len(self.phases)}  "
            f"files={self.total_files}  "
            f"coverage={self.covered_hotspot_pct:.1f}% CPU"
        )
        for phase in self.phases:
            console.print(
                f"\n  [cyan]Phase {phase.phase_id}[/cyan]  {phase.reason}"
            )
            for sf in phase.files:
                console.print(
                    f"    [white]{sf.path.name}[/white]  "
                    f"hotspot={sf.hotspot_pct:.1f}%  "
                    f"priority={sf.priority_score:.1f}"
                )


# ── Project-level results ─────────────────────────────────────────────────────

@dataclass
class ProjectOptimizationResult:
    """Result of running the full project optimization pipeline."""
    graph:             ProjectGraph
    plan:              Optional[ProjectOptimizationPlan] = None
    files_optimized:   int = 0
    files_validated:   int = 0
    files_failed:      int = 0
    total_patches:     int = 0
    total_duration_s:  float = 0.0
    error:             Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and self.files_optimized > 0

    def print_summary(self, console: Console) -> None:
        from rich.rule import Rule
        console.print(Rule("[bold]Project Optimization Summary[/bold]"))
        if self.error:
            console.print(f"[bold red]Error:[/bold red] {self.error}")
            return
        console.print(f"  Files optimized : [green]{self.files_optimized}[/green]")
        console.print(f"  Files validated : {self.files_validated}")
        console.print(f"  Files failed    : [red]{self.files_failed}[/red]")
        console.print(f"  Total patches   : {self.total_patches}")
        console.print(f"  Duration        : {self.total_duration_s:.1f}s")
