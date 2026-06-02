"""
PerfLens Pipeline Orchestrator

Runs the full optimization workflow:
  1. Static analysis  (Scanner)
  2. Profile parsing  (Profiler, optional)
  3. LLM optimization (Engine, iterative)
  4. Patch validation (Validator, per iteration)
  5. Benchmark record (Dashboard DB)
  6. Summary report   (Rich terminal)
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.rule import Rule

from perflens.optimizer.models import OptimizationResult
from perflens.profiler.models import ProfileData
from perflens.scanner.models import Finding
from perflens.validator.models import ValidationReport


@dataclass
class PipelineRunResult:
    source: Path
    hw_profile: str
    scan_findings: list[Finding] = field(default_factory=list)
    profile_data: Optional[ProfileData] = None
    optimization_results: list[OptimizationResult] = field(default_factory=list)
    validation_reports: list[ValidationReport] = field(default_factory=list)
    best_iteration: int = 0
    best_speedup: Optional[float] = None
    total_duration_s: float = 0.0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and bool(self.optimization_results)


class PerfLensPipeline:
    def __init__(
        self,
        hw_profile: str = "auto",
        max_iterations: int = 3,
        dry_run: bool = False,
        console: Optional[Console] = None,
        db_path: Optional[Path] = None,
    ):
        self.hw_profile     = hw_profile
        self.max_iterations = max_iterations
        self.dry_run        = dry_run
        self.console        = console or Console()
        self.db_path        = db_path

    # ── Public API ────────────────────────────────────────────────────────────

    def run(
        self,
        source: Path,
        profile_report: Optional[Path] = None,
        profile_tool: str = "vtune",
        output: Optional[Path] = None,
    ) -> PipelineRunResult:
        t_start = time.monotonic()
        result = PipelineRunResult(source=source, hw_profile=self.hw_profile)
        c = self.console

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=c,
            transient=True,
        ) as progress:

            # ── Step 1: Scan ─────────────────────────────────────────────────
            task = progress.add_task("[cyan]Scanning source code…", total=None)
            try:
                from perflens.scanner.dispatcher import scan_file, detect_language
                lang = detect_language(source)
                findings = scan_file(source, language=lang)
                result.scan_findings = findings
                progress.update(task, description=f"[cyan]Scan: {len(findings)} findings")
            except Exception as exc:
                result.error = f"Scanner failed: {exc}"
                return result

            # ── Step 2: Profile ───────────────────────────────────────────────
            if profile_report:
                progress.update(task, description="[cyan]Parsing profiler report…")
                try:
                    from perflens.profiler.dispatcher import parse_profile
                    profile_data = parse_profile(
                        tool=profile_tool,
                        report_path=profile_report,
                        source=source,
                    )
                    result.profile_data = profile_data
                    progress.update(task, description=f"[cyan]Profile: {len(profile_data.hotspots)} hotspots")
                except Exception as exc:
                    c.print(f"[yellow]⚠ Profiler parse failed: {exc}[/yellow]")

            # ── Step 3: Optimize (iterative) ──────────────────────────────────
            progress.update(task, description="[green]Running LLM optimizer…")
            try:
                from perflens.optimizer.engine import OptimizationEngine
                engine = OptimizationEngine(
                    hw_profile=self.hw_profile,
                    max_iterations=self.max_iterations,
                    dry_run=self.dry_run,
                )
                opt_results = engine.optimize(
                    source=source,
                    profile_data=result.profile_data,
                    findings=findings,
                )
                result.optimization_results = opt_results
            except Exception as exc:
                result.error = f"Optimizer failed: {exc}"
                return result

            # ── Step 4: Validate each iteration's patch ───────────────────────
            if not self.dry_run:
                from perflens.validator.checker import PatchValidator
                validator = PatchValidator(console=c)

                for i, opt_r in enumerate(opt_results):
                    if not opt_r.optimized_source:
                        continue

                    progress.update(task, description=f"[yellow]Validating iteration {i+1}…")

                    # Write patched file to temp location
                    patched_path = source.with_suffix(f".perflens_iter{opt_r.iteration}{source.suffix}")
                    patched_path.write_text(opt_r.optimized_source)

                    val_report = validator.validate(
                        original=source,
                        patched=patched_path,
                    )
                    result.validation_reports.append(val_report)

                    if val_report.passed:
                        result.best_iteration = opt_r.iteration
                        # Write final output
                        if output:
                            shutil.copy(str(patched_path), str(output))
                        else:
                            # Default: <stem>.optimized.<ext>
                            default_out = source.with_name(
                                source.stem + f"_optimized_iter{opt_r.iteration}" + source.suffix
                            )
                            shutil.copy(str(patched_path), str(default_out))
                            c.print(f"[green]✓ Optimized source written: {default_out}[/green]")

                    # Clean up temp file
                    patched_path.unlink(missing_ok=True)

        result.total_duration_s = time.monotonic() - t_start

        # ── Step 5: Record to dashboard DB ────────────────────────────────────
        self._record_to_db(result)

        return result

    # ── Reporting ─────────────────────────────────────────────────────────────

    def print_summary(self, result: PipelineRunResult, console: Console) -> None:
        console.print(Rule("[bold]PerfLens Run Summary[/bold]"))

        if result.error:
            console.print(f"[bold red]Pipeline error:[/bold red] {result.error}")
            return

        # Scan summary
        from collections import Counter
        from perflens.scanner.models import Severity
        sev_counts = Counter(f.severity for f in result.scan_findings)
        console.print(
            f"\n[bold cyan]Scan:[/bold cyan] {len(result.scan_findings)} findings — "
            + "  ".join(f"[red]{sev_counts.get(Severity.CRITICAL,0)} critical[/red]"
                        f"  [orange1]{sev_counts.get(Severity.HIGH,0)} high[/orange1]"
                        f"  [yellow]{sev_counts.get(Severity.MEDIUM,0)} medium[/yellow]"
                        f"  [cyan]{sev_counts.get(Severity.LOW,0)} low[/cyan]".split("  "))
        )

        # Profile summary
        if result.profile_data:
            pd = result.profile_data
            console.print(
                f"[bold cyan]Profile:[/bold cyan] {len(pd.hotspots)} hotspots"
                f"  total_time={pd.total_time_ms:.0f}ms"
            )

        # Optimization iterations
        for opt in result.optimization_results:
            status = "✓" if opt.success else "✗"
            color  = "green" if opt.success else "red"
            console.print(
                f"[{color}]{status} Iteration {opt.iteration}:[/{color}]"
                f"  {len(opt.patches)} patches proposed"
                f"  tokens={opt.tokens_used}"
                + (f"  [red]{opt.error}[/red]" if opt.error else "")
            )
            for p in opt.patches:
                console.print(
                    f"    → [{p.transform_kind.value}] L{p.start_line}–{p.end_line}"
                    f"  expected {p.expected_speedup or '?'}"
                )

        # Validation
        for i, vr in enumerate(result.validation_reports):
            status = "[bold green]PASS[/bold green]" if vr.passed else "[bold red]FAIL[/bold red]"
            console.print(f"Validation iter {i+1}: {status}")

        console.print(
            f"\n[bold]Duration:[/bold] {result.total_duration_s:.1f}s"
            f"  best_iteration={result.best_iteration}"
        )

    # ── DB recording ──────────────────────────────────────────────────────────

    def _record_to_db(self, result: PipelineRunResult) -> None:
        """Persist run results to the benchmark SQLite DB (best-effort)."""
        try:
            import httpx
            for opt in result.optimization_results:
                if not opt.success:
                    continue
                hotspots = []
                if result.profile_data:
                    hotspots = [
                        {
                            "function": h.function,
                            "cpu_pct": h.cpu_time_pct,
                            "cpu_ms": h.cpu_time_ms,
                            "ai": h.arithmetic_intensity,
                            "gflops": h.gflops,
                        }
                        for h in result.profile_data.top_hotspots(10)
                    ]
                payload = {
                    "label": f"{result.source.name} iter {opt.iteration}",
                    "source_file": str(result.source),
                    "hw_profile": self.hw_profile,
                    "iteration": opt.iteration,
                    "runtime_ms": None,
                    "speedup": result.best_speedup,
                    "hotspots": hotspots,
                }
                # Try to POST to local dashboard if running
                httpx.post("http://localhost:8080/api/runs", json=payload, timeout=2.0)
        except Exception:
            pass   # Dashboard may not be running; that's OK
