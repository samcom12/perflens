"""
PerfLens Pipeline Orchestrator — wires all modules together.

Step 1: Scan       (Scanner)
Step 2: Profile    (Profiler, optional)
Step 3: Compiler   (Compiler feedback, optional)
Step 4: Optimize   (Engine — rules / local LLM / cloud LLM)
Step 5: Validate   (Validator, per iteration)
Step 6: Record     (Dashboard DB)
"""

from __future__ import annotations

import json
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from rich.console import Console
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
    backend: str = "rules"
    scan_findings: list[Finding] = field(default_factory=list)
    profile_data: Optional[ProfileData] = None
    compiler_hints: list[str] = field(default_factory=list)
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
        backend: str = "rules",
        # Backend kwargs
        ollama_model: str = "codellama:34b",
        ollama_host: str = "http://localhost:11434",
        compat_url: Optional[str] = None,
        compat_model: Optional[str] = None,
        compat_key: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.hw_profile      = hw_profile
        self.max_iterations  = max_iterations
        self.dry_run         = dry_run
        self.console         = console or Console()
        self.db_path         = db_path
        self.backend         = backend
        self._backend_kwargs = dict(
            ollama_model=ollama_model,
            ollama_host=ollama_host,
            compat_url=compat_url,
            compat_model=compat_model,
            compat_key=compat_key,
            api_key=api_key,
        )

    def run(
        self,
        source: Path,
        profile_report: Optional[Path] = None,
        profile_tool: str = "vtune",
        output: Optional[Path] = None,
        collect_compiler_feedback: bool = False,
        feedback_compiler: Optional[str] = None,
    ) -> PipelineRunResult:
        t_start = time.monotonic()
        result  = PipelineRunResult(source=source, hw_profile=self.hw_profile,
                                    backend=self.backend)
        c = self.console

        with Progress(SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
                      TimeElapsedColumn(), console=c, transient=True) as progress:

            task = progress.add_task("[cyan]Starting pipeline…", total=None)

            # ── Step 1: Scan ─────────────────────────────────────────────────
            progress.update(task, description="[cyan]Scanning source code…")
            try:
                from perflens.scanner.dispatcher import scan_file, detect_language
                lang     = detect_language(source)
                findings = scan_file(source, language=lang)
                result.scan_findings = findings
                progress.update(task, description=f"[cyan]Scan complete: {len(findings)} findings")
            except Exception as exc:
                result.error = f"Scanner failed: {exc}"
                return result

            # ── Step 2: Profile ───────────────────────────────────────────────
            if profile_report:
                progress.update(task, description="[cyan]Parsing profiler report…")
                try:
                    from perflens.profiler.dispatcher import parse_profile
                    pd = parse_profile(tool=profile_tool, report_path=profile_report, source=source)
                    result.profile_data = pd
                    progress.update(task, description=f"[cyan]Profile: {len(pd.hotspots)} hotspots")
                except Exception as exc:
                    c.print(f"[yellow]⚠ Profiler: {exc}[/yellow]")

            # ── Step 3: Compiler feedback (optional) ──────────────────────────
            if collect_compiler_feedback:
                progress.update(task, description="[cyan]Collecting compiler feedback…")
                try:
                    from perflens.compiler_feedback import collect_feedback
                    fb = collect_feedback(source, compiler=feedback_compiler)
                    result.compiler_hints = fb.to_scanner_hints()
                    progress.update(task, description=f"[cyan]Compiler: {len(result.compiler_hints)} hints")
                except Exception as exc:
                    c.print(f"[yellow]⚠ Compiler feedback: {exc}[/yellow]")

            # ── Step 4: Optimize ──────────────────────────────────────────────
            progress.update(task, description=f"[green]Optimizing with backend={self.backend}…")
            try:
                from perflens.optimizer.engine import OptimizationEngine
                engine = OptimizationEngine(
                    hw_profile=self.hw_profile,
                    max_iterations=self.max_iterations,
                    dry_run=self.dry_run,
                    backend=self.backend,
                    **self._backend_kwargs,
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

            # ── Step 5: Validate ──────────────────────────────────────────────
            if not self.dry_run:
                from perflens.validator.checker import PatchValidator
                validator = PatchValidator(console=c)

                for opt_r in opt_results:
                    if not opt_r.optimized_source:
                        continue
                    progress.update(task, description=f"[yellow]Validating iteration {opt_r.iteration}…")
                    patched_path = source.with_name(
                        f"{source.stem}.perflens_iter{opt_r.iteration}{source.suffix}"
                    )
                    patched_path.write_text(opt_r.optimized_source)
                    val_report = validator.validate(original=source, patched=patched_path)
                    result.validation_reports.append(val_report)

                    if val_report.passed:
                        result.best_iteration = opt_r.iteration
                        final_out = output or source.with_name(
                            f"{source.stem}_optimized_iter{opt_r.iteration}{source.suffix}"
                        )
                        shutil.copy(str(patched_path), str(final_out))
                        c.print(f"[green]✓ Optimized source → {final_out}[/green]")
                    patched_path.unlink(missing_ok=True)

        result.total_duration_s = time.monotonic() - t_start
        self._record_to_db(result)
        return result

    def print_summary(self, result: PipelineRunResult, console: Console) -> None:
        console.print(Rule("[bold]PerfLens Run Summary[/bold]"))

        if result.error:
            console.print(f"[bold red]Error:[/bold red] {result.error}")
            return

        from collections import Counter
        from perflens.scanner.models import Severity
        sev = Counter(f.severity for f in result.scan_findings)
        console.print(
            f"[bold cyan]Backend:[/bold cyan] {result.backend}  "
            f"[bold cyan]HW:[/bold cyan] {result.hw_profile}"
        )
        console.print(
            f"[bold cyan]Scan:[/bold cyan] {len(result.scan_findings)} findings — "
            f"[red]{sev.get(Severity.CRITICAL,0)} critical[/red]  "
            f"[orange1]{sev.get(Severity.HIGH,0)} high[/orange1]  "
            f"[yellow]{sev.get(Severity.MEDIUM,0)} medium[/yellow]"
        )
        if result.compiler_hints:
            console.print(f"[bold cyan]Compiler hints:[/bold cyan] {len(result.compiler_hints)}")

        for opt in result.optimization_results:
            status = "[green]✓[/green]" if opt.success else "[red]✗[/red]"
            console.print(
                f"{status} Iteration {opt.iteration}: "
                f"{len(opt.patches)} patches  tokens={opt.tokens_used}"
            )
            for p in opt.patches:
                console.print(
                    f"   → [cyan]{p.transform_kind.value}[/cyan]  "
                    f"L{p.start_line}–{p.end_line}  "
                    f"[green]{p.expected_speedup or '?'}[/green]"
                )

        for i, vr in enumerate(result.validation_reports):
            status = {
                "passed":     "[green]PASS[/green]",
                "failed":     "[red]FAIL[/red]",
                "unverified": "[yellow]UNVERIFIED[/yellow]",
            }.get(vr.verdict, "[red]FAIL[/red]")
            console.print(f"Validation iter {i+1}: {status}")

        console.print(
            f"\n[bold]Duration:[/bold] {result.total_duration_s:.1f}s  "
            f"best_iter={result.best_iteration}"
        )

    def _record_to_db(self, result: PipelineRunResult) -> None:
        try:
            import httpx
            for opt in result.optimization_results:
                if not opt.success:
                    continue
                hotspots = []
                if result.profile_data:
                    hotspots = [
                        {"function": h.function, "cpu_pct": h.cpu_time_pct,
                         "cpu_ms": h.cpu_time_ms}
                        for h in result.profile_data.top_hotspots(10)
                    ]
                httpx.post(
                    "http://localhost:8080/api/runs",
                    json={"label": f"{result.source.name} iter {opt.iteration}",
                          "source_file": str(result.source),
                          "hw_profile": self.hw_profile,
                          "iteration": opt.iteration,
                          "hotspots": hotspots},
                    timeout=2.0,
                )
        except Exception:
            pass
