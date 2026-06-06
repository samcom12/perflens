"""
Project Pipeline — end-to-end whole-codebase optimization workflow.

Steps:
  1. Crawl    — discover all source files and dependency graph
  2. Build    — compile project, collecting per-file compiler reports
  3. Profile  — optional: run binary + parse VTune/HPCToolkit output
  4. Scan     — static analysis on every source file (parallel)
  5. Plan     — build optimization plan (priority-ordered phases)
  6. Optimize — apply rule engine + LLM to each phase
  7. Validate — compile-check + test after each phase
  8. Report   — rich terminal summary + dashboard DB records
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import (
    Progress, SpinnerColumn, TextColumn,
    BarColumn, MofNCompleteColumn, TimeElapsedColumn,
)
from rich.rule import Rule

from perflens.project.models import (
    ProjectGraph, ProjectOptimizationPlan, ProjectOptimizationResult,
)


class ProjectPipeline:
    """
    Full project optimization pipeline.

    Args:
        root:             Project root directory
        hw_profile:       Hardware target (auto | a100 | intel_spr | …)
        backend:          Optimizer backend (rules | ollama | anthropic | …)
        build:            Whether to run the project build step
        profile_binary:   Path to binary to profile (optional)
        profile_tool:     vtune | hpctoolkit
        profile_report:   Pre-existing profiler report file
        top_hotspot_n:    How many hotspot files to optimize first
        validate:         Run validation after each phase
        apply_patches:    Copy validated patches back into source tree
        dry_run:          Show plan without modifying any files
        max_workers:      Threads for parallel scanning (default: 4)
        console:          Rich Console
    """

    def __init__(
        self,
        root: Path,
        hw_profile: str = "auto",
        backend: str = "rules",
        build: bool = True,
        profile_binary: Optional[Path] = None,
        profile_tool: str = "vtune",
        profile_report: Optional[Path] = None,
        top_hotspot_n: int = 10,
        validate: bool = True,
        apply_patches: bool = False,
        dry_run: bool = False,
        max_workers: int = 4,
        console: Optional[Console] = None,
        # Backend kwargs forwarded
        ollama_model: str = "codellama:34b",
        ollama_host:  str = "http://localhost:11434",
        compat_url: Optional[str]   = None,
        compat_model: Optional[str] = None,
        compat_key: Optional[str]   = None,
        api_key: Optional[str]      = None,
    ):
        self.root            = root
        self.hw_profile      = hw_profile
        self.backend         = backend
        self.build           = build
        self.profile_binary  = profile_binary
        self.profile_tool    = profile_tool
        self.profile_report  = profile_report
        self.top_hotspot_n   = top_hotspot_n
        self.validate        = validate
        self.apply_patches   = apply_patches
        self.dry_run         = dry_run
        self.max_workers     = max_workers
        self.console         = console or Console()
        self._backend_kwargs = dict(
            ollama_model=ollama_model, ollama_host=ollama_host,
            compat_url=compat_url, compat_model=compat_model,
            compat_key=compat_key, api_key=api_key,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self) -> ProjectOptimizationResult:
        t0     = time.monotonic()
        c      = self.console

        c.print(Rule(f"[bold cyan]PerfLens Project Pipeline[/bold cyan]"))
        c.print(f"  Root    : [white]{self.root}[/white]")
        c.print(f"  Backend : [yellow]{self.backend}[/yellow]")
        c.print(f"  HW      : [cyan]{self.hw_profile}[/cyan]")

        # ── Resolve hardware ─────────────────────────────────────────────────
        hardware = self._resolve_hardware()
        c.print(f"  Target  : {hardware.name}")

        # ── Step 1: Crawl ────────────────────────────────────────────────────
        c.print(Rule("[1/7] Crawling project…"))
        graph = self._step_crawl()
        graph.print_summary(c)

        # ── Step 2: Build + compiler feedback ────────────────────────────────
        if self.build:
            c.print(Rule("[2/7] Building project + collecting compiler reports…"))
            self._step_build(graph, hardware)
        else:
            c.print("[dim][2/7] Build skipped (--no-build)[/dim]")
            # Still collect compiler feedback without rebuilding
            c.print("[dim]      Collecting compiler feedback without rebuild…[/dim]")
            self._step_compiler_feedback_only(graph, hardware)

        # ── Step 3: Profile ──────────────────────────────────────────────────
        if self.profile_binary or self.profile_report:
            c.print(Rule("[3/7] Profiling…"))
            self._step_profile(graph)
        else:
            c.print("[dim][3/7] Profile skipped (no --binary or --profile)[/dim]")

        # ── Step 4: Scan ─────────────────────────────────────────────────────
        c.print(Rule("[4/7] Static analysis (parallel)…"))
        self._step_scan(graph)

        # ── Step 5: Plan ─────────────────────────────────────────────────────
        c.print(Rule("[5/7] Building optimization plan…"))
        plan = self._step_plan(graph)
        plan.print_plan(c)
        graph.print_file_table(c)

        if self.dry_run:
            c.print("[yellow]Dry run — stopping before optimization.[/yellow]")
            result = ProjectOptimizationResult(graph=graph, plan=plan)
            result.total_duration_s = time.monotonic() - t0
            return result

        # ── Step 6: Optimize ─────────────────────────────────────────────────
        c.print(Rule(f"[6/7] Optimizing (backend={self.backend})…"))
        result = self._step_optimize(graph, plan, hardware)

        # ── Step 7: Apply patches ─────────────────────────────────────────────
        if self.apply_patches and not self.dry_run:
            c.print(Rule("[7/7] Applying validated patches…"))
            from perflens.optimizer.project_optimizer import ProjectOptimizer
            optimizer = ProjectOptimizer(plan=plan, hardware=hardware,
                                         backend=self.backend, console=c,
                                         **self._backend_kwargs)
            n = optimizer.apply_patches(backup=True)
            c.print(f"[green]  {n} file(s) updated in source tree[/green]")
        else:
            c.print(
                f"[dim][7/7] Patches in {graph.root / 'perflens_patches'} "
                f"(run with --apply to write back)[/dim]"
            )

        result.total_duration_s = time.monotonic() - t0
        result.print_summary(c)
        self._record_to_dashboard(result)
        return result

    # ── Pipeline steps ────────────────────────────────────────────────────────

    def _resolve_hardware(self):
        from perflens.hardware.database import HardwareDatabase
        from perflens.hardware.detector import detect_hardware
        db = HardwareDatabase()
        if self.hw_profile == "auto":
            return detect_hardware()
        hw = db.get(self.hw_profile)
        if hw is None:
            raise ValueError(f"Unknown hw profile: {self.hw_profile}")
        return hw

    def _step_crawl(self) -> ProjectGraph:
        from perflens.project.crawler import ProjectCrawler
        crawler = ProjectCrawler(root=self.root)
        graph   = crawler.crawl()
        self.console.print(
            f"  Found {len(graph.files)} files  "
            f"({len(graph.source_files)} source, "
            f"{len(graph.files) - len(graph.source_files)} headers)"
        )
        return graph

    def _step_build(self, graph: ProjectGraph, hardware) -> None:
        from perflens.project.build_system import BuildDriver
        driver = BuildDriver(graph=graph, hardware=hardware)
        ok     = driver.build()
        c_ok   = sum(1 for sf in graph.files.values() if sf.compiler_feedback)
        status = "[green]✓[/green]" if ok else "[yellow]partial[/yellow]"
        self.console.print(
            f"  Build: {status}  "
            f"compile commands: {len(graph.compile_commands)}  "
            f"compiler reports: {c_ok} files"
        )

    def _step_compiler_feedback_only(self, graph: ProjectGraph, hardware) -> None:
        from perflens.project.build_system import BuildDriver
        driver = BuildDriver(graph=graph, hardware=hardware)
        driver.collect_compiler_feedback_only()
        c_ok = sum(1 for sf in graph.files.values() if sf.compiler_feedback)
        self.console.print(f"  Compiler feedback collected for {c_ok} files")

    def _step_profile(self, graph: ProjectGraph) -> None:
        """Run profiler and map hotspot % back to source files."""
        from perflens.profiler.dispatcher import parse_profile

        # Use pre-existing report if provided
        report_path = self.profile_report
        if not report_path and self.profile_binary:
            report_path = self._run_profiler(self.profile_binary)

        if not report_path:
            return

        try:
            pd = parse_profile(tool=self.profile_tool, report_path=report_path)
        except Exception as exc:
            self.console.print(f"[yellow]Profile parse error: {exc}[/yellow]")
            return

        # Map hotspot function → source file
        for hotspot in pd.hotspots:
            src_file = hotspot.source_file
            if not src_file:
                continue
            # Try to find matching SourceFile
            src_path = Path(src_file)
            if src_path in graph.files:
                graph.files[src_path].hotspot_pct += hotspot.cpu_time_pct
                if hotspot.start_line:
                    graph.files[src_path].hotspot_lines.append(hotspot.start_line)
            else:
                # Match by filename
                for sf_path, sf in graph.files.items():
                    if sf_path.name == src_path.name:
                        sf.hotspot_pct += hotspot.cpu_time_pct
                        if hotspot.start_line:
                            sf.hotspot_lines.append(hotspot.start_line)
                        break

        n_hot = sum(1 for sf in graph.files.values() if sf.hotspot_pct > 0)
        self.console.print(
            f"  Profile: {len(pd.hotspots)} hotspots → {n_hot} files attributed  "
            f"total_time={pd.total_time_ms:.0f}ms"
        )

    def _run_profiler(self, binary: Path) -> Optional[Path]:
        """Run the binary under VTune and export CSV. Returns report path."""
        import shutil as sh, subprocess
        vtune = sh.which("vtune")
        if not vtune:
            self.console.print("[yellow]vtune not found — skipping profile run[/yellow]")
            return None
        result_dir = self.root / "vtune_perflens"
        out_csv    = result_dir / "hotspots.csv"
        try:
            subprocess.run(
                [vtune, "-collect", "hotspots",
                 "-result-dir", str(result_dir), "--", str(binary)],
                capture_output=True, timeout=300,
            )
            subprocess.run(
                [vtune, "-report", "hotspots", "-r", str(result_dir),
                 "-format", "csv", "-report-output", str(out_csv)],
                capture_output=True, timeout=60,
            )
            return out_csv if out_csv.exists() else None
        except Exception:
            return None

    def _step_scan(self, graph: ProjectGraph) -> None:
        """Parallel static analysis of all source files."""
        from perflens.scanner.dispatcher import scan_file, detect_language

        to_scan = [sf for sf in graph.files.values()
                   if not sf.is_header]

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(), MofNCompleteColumn(), TimeElapsedColumn(),
            console=self.console, transient=True,
        ) as progress:
            task = progress.add_task("Scanning…", total=len(to_scan))

            def _scan_one(sf):
                try:
                    lang = detect_language(sf.path)
                    sf.scanner_findings = scan_file(sf.path, language=lang)
                except Exception:
                    sf.scanner_findings = []
                progress.advance(task)

            with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
                futures = [pool.submit(_scan_one, sf) for sf in to_scan]
                for f in as_completed(futures):
                    f.result()

        total_findings = sum(len(sf.scanner_findings) for sf in to_scan)
        self.console.print(
            f"  Scanned {len(to_scan)} files → {total_findings} total findings"
        )

    def _step_plan(self, graph: ProjectGraph) -> ProjectOptimizationPlan:
        from perflens.optimizer.project_optimizer import build_optimization_plan
        return build_optimization_plan(
            graph=graph,
            backend=self.backend,
            top_hotspot_n=self.top_hotspot_n,
        )

    def _step_optimize(
        self,
        graph: ProjectGraph,
        plan: ProjectOptimizationPlan,
        hardware,
    ) -> ProjectOptimizationResult:
        from perflens.optimizer.project_optimizer import ProjectOptimizer
        optimizer = ProjectOptimizer(
            plan=plan,
            hardware=hardware,
            backend=self.backend,
            validate_each_phase=self.validate,
            dry_run=self.dry_run,
            console=self.console,
            **self._backend_kwargs,
        )
        return optimizer.run()

    # ── Dashboard recording ───────────────────────────────────────────────────

    def _record_to_dashboard(self, result: ProjectOptimizationResult) -> None:
        try:
            import httpx
            hotspots = [
                {"function": sf.path.name,
                 "cpu_pct":  sf.hotspot_pct,
                 "cpu_ms":   sf.hotspot_pct * 10}
                for sf in result.graph.source_files[:10]
                if sf.hotspot_pct > 0
            ]
            httpx.post(
                "http://localhost:8080/api/runs",
                json={
                    "label":       f"project:{result.graph.name}",
                    "source_file": str(result.graph.root),
                    "hw_profile":  self.hw_profile,
                    "iteration":   result.files_optimized,
                    "hotspots":    hotspots,
                },
                timeout=2.0,
            )
        except Exception:
            pass
