"""
PerfLens CLI — top-level command dispatcher.

Commands:
    perflens scan      <file>           Static analysis
    perflens profile   <file>           Parse profiler report
    perflens optimize  <file>           Full pipeline (scan → optimize → validate)
    perflens validate  <orig> <patch>   Validate a patched file
    perflens dashboard                  Launch benchmark dashboard
    perflens backends                   List available LLM backends
    perflens hw detect                  Auto-detect hardware
    perflens hw list                    List all hardware profiles
    perflens hw show   <id>             Show one profile
    perflens autotune  <file>           Empirically tune tile size / threads
    perflens compiler  <file>           Collect compiler optimization feedback
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from perflens import __version__

app = typer.Typer(
    name="perflens",
    help="🔬 PerfLens — Automated HPC Code Optimization Framework",
    add_completion=False,
    rich_markup_mode="rich",
)
console = Console()

hw_app      = typer.Typer(help="Hardware database commands")
project_app = typer.Typer(help="Whole-project optimization workflow")
app.add_typer(hw_app,      name="hw")
app.add_typer(project_app, name="project")


# ─────────────────────────────────────────────────────────────────────────────
# perflens scan
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def scan(
    source: Path = typer.Argument(..., help="Source file or directory to scan"),
    language: Optional[str] = typer.Option(None, "--lang", "-l"),
    output: Optional[Path]  = typer.Option(None, "--output", "-o"),
    verbose: bool           = typer.Option(False, "--verbose", "-v"),
):
    """[bold cyan]Static analysis[/bold cyan] — detect optimization opportunities."""
    from perflens.scanner.dispatcher import scan_file
    console.print(Panel(f"[bold]PerfLens Scanner[/bold]  v{__version__}", style="cyan"))
    findings = scan_file(source, language=language, verbose=verbose)
    if output:
        import json
        output.write_text(json.dumps([f.to_dict() for f in findings], indent=2))
        console.print(f"[green]Findings → {output}[/green]")
    else:
        from perflens.scanner.report import print_findings
        print_findings(findings, console)


# ─────────────────────────────────────────────────────────────────────────────
# perflens profile
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def profile(
    source: Path           = typer.Argument(...),
    tool: str              = typer.Option("vtune", "--tool", "-t"),
    report: Optional[Path] = typer.Option(None, "--report", "-r"),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
):
    """[bold cyan]Profile parsing[/bold cyan] — extract hotspot data."""
    from perflens.profiler.dispatcher import parse_profile
    console.print(Panel(f"[bold]PerfLens Profiler[/bold] [{tool.upper()}]", style="cyan"))
    pd = parse_profile(tool=tool, report_path=report, source=source)
    pd.print_summary(console)
    if output:
        import json
        output.write_text(json.dumps(pd.to_dict(), indent=2))
        console.print(f"[green]Profile → {output}[/green]")


# ─────────────────────────────────────────────────────────────────────────────
# perflens optimize
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def optimize(
    source: Path            = typer.Argument(..., help="Source file to optimize"),
    hw: str                 = typer.Option("auto", "--hw"),
    backend: str            = typer.Option("rules",
        "--backend", "-b",
        help="Backend: rules | ollama | ollama:<model> | groq | lmstudio | "
             "llamacpp | vllm | openai-compat | anthropic"),
    profile_report: Optional[Path] = typer.Option(None, "--profile", "-p"),
    profile_tool: str       = typer.Option("vtune", "--profile-tool"),
    output: Optional[Path]  = typer.Option(None, "--output", "-o"),
    dry_run: bool           = typer.Option(False, "--dry-run"),
    max_iterations: int     = typer.Option(3, "--iterations", "-n"),
    # Backend-specific
    ollama_model: str       = typer.Option("codellama:34b", "--ollama-model"),
    ollama_host: str        = typer.Option("http://localhost:11434", "--ollama-host"),
    compat_url: Optional[str]   = typer.Option(None, "--compat-url"),
    compat_model: Optional[str] = typer.Option(None, "--compat-model"),
    compat_key: Optional[str]   = typer.Option(None, "--compat-key"),
    # Compiler feedback
    compiler_feedback: bool = typer.Option(False, "--compiler-feedback", "-cf",
        help="Collect GCC/Clang/ICX optimization remarks before optimizing"),
    feedback_compiler: str  = typer.Option("auto", "--feedback-compiler"),
):
    """[bold green]Full optimization pipeline[/bold green] — no API key needed with --backend rules."""
    from perflens.pipeline.orchestrator import PerfLensPipeline

    console.print(Panel(
        Text.from_markup(
            f"[bold green]PerfLens Optimizer[/bold green]  "
            f"hw=[cyan]{hw}[/cyan]  backend=[yellow]{backend}[/yellow]  "
            f"file=[white]{source}[/white]"
        ),
        style="green",
    ))

    pipeline = PerfLensPipeline(
        hw_profile=hw,
        max_iterations=max_iterations,
        dry_run=dry_run,
        console=console,
        backend=backend,
        ollama_model=ollama_model,
        ollama_host=ollama_host,
        compat_url=compat_url,
        compat_model=compat_model,
        compat_key=compat_key,
    )
    result = pipeline.run(
        source=source,
        profile_report=profile_report,
        profile_tool=profile_tool,
        output=output,
        collect_compiler_feedback=compiler_feedback,
        feedback_compiler=None if feedback_compiler == "auto" else feedback_compiler,
    )
    pipeline.print_summary(result, console)


# ─────────────────────────────────────────────────────────────────────────────
# perflens validate
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def validate(
    original: Path          = typer.Argument(...),
    patched: Path           = typer.Argument(...),
    test_dir: Optional[Path] = typer.Option(None, "--tests", "-t"),
    tolerance: float         = typer.Option(1e-6, "--tol"),
):
    """[bold yellow]Patch validation[/bold yellow] — compile, test, numerical diff."""
    from perflens.validator.checker import PatchValidator
    console.print(Panel("[bold]PerfLens Validator[/bold]", style="yellow"))
    report = PatchValidator(tolerance=tolerance, console=console).validate(
        original=original, patched=patched, test_dir=test_dir
    )
    report.print(console)
    sys.exit(0 if report.passed else 1)


# ─────────────────────────────────────────────────────────────────────────────
# perflens dashboard
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def dashboard(
    port: int              = typer.Option(8080, "--port", "-p"),
    host: str              = typer.Option("0.0.0.0", "--host"),
    db: Optional[Path]     = typer.Option(None, "--db"),
):
    """[bold magenta]Benchmark dashboard[/bold magenta] — Plotly/FastAPI web UI."""
    import uvicorn
    from perflens.dashboard.app import create_app
    console.print(Panel(f"[bold]PerfLens Dashboard[/bold]  http://{host}:{port}", style="magenta"))
    uvicorn.run(create_app(db_path=db), host=host, port=port, log_level="info")


# ─────────────────────────────────────────────────────────────────────────────
# perflens backends  (NEW)
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def backends():
    """[bold]List all available optimization backends[/bold] with availability status."""
    from perflens.optimizer.backends.registry import list_backends

    console.print(Panel("[bold]PerfLens Backends[/bold]", style="cyan"))
    rows = list_backends()

    table = Table(box=box.ROUNDED, show_lines=True)
    table.add_column("Backend",     width=16, style="bold")
    table.add_column("Available",   width=11, justify="center")
    table.add_column("Needs Key",   width=11, justify="center")
    table.add_column("Local",       width=7,  justify="center")
    table.add_column("Notes")

    for r in rows:
        avail = "[green]✓[/green]" if r["available"] else "[red]✗[/red]"
        key   = "[red]yes[/red]"   if r["requires_key"] else "[green]no[/green]"
        local = "[cyan]yes[/cyan]" if r["local"] else "cloud"
        table.add_row(r["name"], avail, key, local, r["notes"][:70])

    console.print(table)
    console.print()
    console.print("[dim]Usage examples:[/dim]")
    console.print("  perflens optimize solver.c [bold]--backend rules[/bold]          # zero LLM, no key")
    console.print("  perflens optimize solver.c [bold]--backend ollama[/bold]         # local Ollama")
    console.print("  perflens optimize solver.c [bold]--backend ollama:llama3:8b[/bold]")
    console.print("  perflens optimize solver.c [bold]--backend groq[/bold]           # free tier, fast")
    console.print("  perflens optimize solver.c [bold]--backend lmstudio[/bold]       # LM Studio local")
    console.print("  perflens optimize solver.c [bold]--backend anthropic[/bold]      # Claude API")


# ─────────────────────────────────────────────────────────────────────────────
# perflens autotune  (NEW)
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def autotune(
    source: Path          = typer.Argument(..., help="Source file (must have #define TILE)"),
    hw: str               = typer.Option("auto", "--hw"),
    driver: Optional[Path] = typer.Option(None, "--driver", "-d",
        help="Binary/script that exercises the kernel"),
    param: str            = typer.Option("tile", "--param",
        help="Parameter to tune: tile | threads"),
    tiles: str            = typer.Option("", "--tiles",
        help="Comma-separated tile sizes, e.g. 8,16,32,64,128"),
    threads: str          = typer.Option("", "--threads",
        help="Comma-separated thread counts, e.g. 1,2,4,8,16"),
    output: Optional[Path] = typer.Option(None, "--output", "-o",
        help="Write best config to this JSON file"),
):
    """[bold]Empirically tune tile size or thread count[/bold] — no API key needed."""
    from perflens.hardware.database import HardwareDatabase
    from perflens.hardware.detector import detect_hardware
    from perflens.autotuner.tile_tuner import TileSearchTuner

    console.print(Panel(f"[bold]PerfLens Auto-Tuner[/bold]  param={param}", style="cyan"))

    db_hw = HardwareDatabase()
    hardware = detect_hardware() if hw == "auto" else db_hw.get(hw)
    if hardware is None:
        console.print(f"[red]Unknown hw profile '{hw}'[/red]")
        raise typer.Exit(1)

    tuner = TileSearchTuner(source=source, hardware=hardware,
                            driver=driver, console=console)

    if param == "tile":
        tile_list = [int(t) for t in tiles.split(",") if t.strip()] or None
        result = tuner.run(tile_candidates=tile_list)
    elif param == "threads":
        thr_list = [int(t) for t in threads.split(",") if t.strip()] or None
        result = tuner.sweep_threads(thread_counts=thr_list)
    else:
        console.print(f"[red]Unknown param '{param}' — use tile or threads[/red]")
        raise typer.Exit(1)

    console.print(result.summary())

    if output and result.best.run_ok:
        import json
        output.write_text(json.dumps({
            "param": param,
            "best_value": result.best.tile_size or result.best.thread_count,
            "runtime_ms": result.best.runtime_ms,
            "speedup": result.best.speedup,
            "all_points": [
                {"value": p.tile_size or p.thread_count,
                 "runtime_ms": p.runtime_ms, "speedup": p.speedup}
                for p in result.all_points if p.run_ok
            ],
        }, indent=2))
        console.print(f"[green]Tune result → {output}[/green]")


# ─────────────────────────────────────────────────────────────────────────────
# perflens compiler  (NEW)
# ─────────────────────────────────────────────────────────────────────────────

@app.command()
def compiler(
    source: Path            = typer.Argument(..., help="Source file to compile and analyse"),
    comp: str               = typer.Option("auto", "--compiler", "-c",
        help="Compiler: auto | gcc | clang | icx"),
    report_file: Optional[Path] = typer.Option(None, "--report", "-r",
        help="Parse an existing opt-info file instead of compiling"),
    output: Optional[Path]  = typer.Option(None, "--output", "-o"),
):
    """[bold]Collect compiler optimization feedback[/bold] — missed vectorizations, aliasing issues."""
    from perflens.compiler_feedback import collect_feedback

    console.print(Panel(f"[bold]PerfLens Compiler Feedback[/bold]  ({comp})", style="cyan"))
    fb = collect_feedback(
        source=source,
        compiler=None if comp == "auto" else comp,
        report_file=report_file,
    )
    fb.print_summary(console)

    hints = fb.to_scanner_hints()
    if hints:
        console.print("\n[bold]Hints for optimizer:[/bold]")
        for h in hints:
            console.print(f"  [yellow]•[/yellow] {h}")

    if output:
        import json
        output.write_text(json.dumps(
            {"source": str(source),
             "compiler": fb.compiler,
             "remarks": [r.to_dict() for r in fb.remarks]},
            indent=2,
        ))
        console.print(f"[green]Feedback → {output}[/green]")


# ─────────────────────────────────────────────────────────────────────────────
# perflens hw
# ─────────────────────────────────────────────────────────────────────────────

@hw_app.command("detect")
def hw_detect():
    """Auto-detect current hardware."""
    from perflens.hardware.detector import detect_hardware
    detect_hardware().print_summary(console)


@hw_app.command("list")
def hw_list():
    """List all built-in hardware profiles."""
    from perflens.hardware.database import HardwareDatabase
    HardwareDatabase().print_all(console)


@hw_app.command("show")
def hw_show(profile_id: str = typer.Argument(...)):
    """Show detailed hardware profile."""
    from perflens.hardware.database import HardwareDatabase
    hw = HardwareDatabase().get(profile_id)
    if hw is None:
        console.print(f"[red]Unknown profile: {profile_id}[/red]")
        raise typer.Exit(1)
    hw.print_full(console)


# ─────────────────────────────────────────────────────────────────────────────
# perflens project  — whole-codebase workflow
# ─────────────────────────────────────────────────────────────────────────────

@project_app.command("scan")
def project_scan(
    root: Path = typer.Argument(..., help="Project root directory"),
    output: Optional[Path] = typer.Option(None, "--output", "-o",
        help="Write project graph JSON here"),
    extensions: str = typer.Option("", "--ext",
        help="Comma-separated extensions to include, e.g. .c,.cpp"),
    show_deps: bool = typer.Option(False, "--deps", help="Show dependency table"),
):
    """[bold cyan]Crawl a project directory[/bold cyan] — discover all source files and dependencies."""
    from perflens.project.crawler import ProjectCrawler

    console.print(Panel(f"[bold]PerfLens Project Scan[/bold]  {root}", style="cyan"))

    ext_set = {e.strip() for e in extensions.split(",") if e.strip()} or None
    crawler = ProjectCrawler(root=root, extensions=ext_set)
    graph   = crawler.crawl()
    graph.print_summary(console)

    if show_deps:
        from perflens.project.dependency_graph import DependencyGraph
        dg = DependencyGraph(graph)
        shared = dg.shared_headers()
        if shared:
            console.print(f"\n[bold]Shared headers ({len(shared)}):[/bold]")
            for h in shared[:10]:
                callers = len(dg._in.get(h, set()))
                console.print(f"  [cyan]{h.name}[/cyan] — included by {callers} files")

    if output:
        import json
        data = {
            "root":         str(graph.root),
            "build_system": graph.build_system.value,
            "files":        [sf.to_dict() for sf in graph.source_files],
        }
        output.write_text(json.dumps(data, indent=2))
        console.print(f"[green]Graph → {output}[/green]")


@project_app.command("build")
def project_build(
    root: Path = typer.Argument(..., help="Project root directory"),
    hw: str    = typer.Option("auto", "--hw"),
    jobs: int  = typer.Option(0, "--jobs", "-j", help="Parallel build jobs (0=auto)"),
    no_build: bool = typer.Option(False, "--no-build",
        help="Skip compilation, only collect compiler feedback"),
    output: Optional[Path] = typer.Option(None, "--output", "-o"),
):
    """[bold cyan]Build project[/bold cyan] and collect compiler optimisation reports automatically."""
    from perflens.project.crawler import ProjectCrawler
    from perflens.project.build_system import BuildDriver
    from perflens.hardware.database import HardwareDatabase
    from perflens.hardware.detector import detect_hardware

    console.print(Panel(f"[bold]PerfLens Project Build[/bold]  {root}", style="cyan"))

    db_hw    = HardwareDatabase()
    hardware = detect_hardware() if hw == "auto" else db_hw.get(hw)
    if hardware is None:
        console.print(f"[red]Unknown hw profile '{hw}'[/red]"); raise typer.Exit(1)

    graph  = ProjectCrawler(root=root).crawl()
    driver = BuildDriver(graph=graph, hardware=hardware, jobs=jobs)

    if no_build:
        console.print("[dim]Collecting compiler feedback without rebuild…[/dim]")
        driver.collect_compiler_feedback_only()
    else:
        ok = driver.build()
        status = "[green]✓ Build succeeded[/green]" if ok else "[red]✗ Build failed[/red]"
        console.print(status)

    c_ok = sum(1 for sf in graph.files.values() if sf.compiler_feedback)
    console.print(f"  Compiler reports attached: {c_ok} files")

    for sf in sorted(graph.source_files, key=lambda s: s.priority_score, reverse=True)[:5]:
        if sf.compiler_feedback:
            fb   = sf.compiler_feedback
            miss = len(fb.missed_vectorization)
            vec  = len(fb.vectorized_loops)
            console.print(f"  [cyan]{sf.path.name}[/cyan]  "
                          f"vec={vec}  missed={miss}")

    if output:
        import json
        output.write_text(json.dumps(
            {"files": [sf.to_dict() for sf in graph.source_files]}, indent=2))
        console.print(f"[green]Report → {output}[/green]")


@project_app.command("optimize")
def project_optimize(
    root: Path = typer.Argument(..., help="Project root directory"),
    hw: str    = typer.Option("auto", "--hw"),
    backend: str = typer.Option("rules", "--backend", "-b",
        help="rules | ollama | ollama:<model> | groq | anthropic | …"),
    no_build:  bool = typer.Option(False, "--no-build"),
    binary:    Optional[Path] = typer.Option(None, "--binary",
        help="Built executable to profile"),
    profile_report: Optional[Path] = typer.Option(None, "--profile", "-p"),
    profile_tool:   str = typer.Option("vtune", "--profile-tool"),
    top_n:     int  = typer.Option(10, "--top-n",
        help="Number of hotspot files to prioritise"),
    validate:  bool = typer.Option(True, "--validate/--no-validate"),
    apply:     bool = typer.Option(False, "--apply",
        help="Copy patches back into source tree after validation"),
    dry_run:   bool = typer.Option(False, "--dry-run"),
    jobs:      int  = typer.Option(0, "--jobs", "-j"),
    # Backend-specific
    ollama_model:  str = typer.Option("codellama:34b", "--ollama-model"),
    ollama_host:   str = typer.Option("http://localhost:11434", "--ollama-host"),
    compat_url:    Optional[str] = typer.Option(None, "--compat-url"),
    compat_model:  Optional[str] = typer.Option(None, "--compat-model"),
    compat_key:    Optional[str] = typer.Option(None, "--compat-key"),
):
    """[bold green]Full project optimization pipeline[/bold green] — crawl → build → profile → scan → optimize → validate."""
    from perflens.pipeline.project_pipeline import ProjectPipeline

    console.print(Panel(
        f"[bold green]PerfLens Project Optimize[/bold green]  "
        f"root=[white]{root}[/white]  "
        f"backend=[yellow]{backend}[/yellow]  "
        f"hw=[cyan]{hw}[/cyan]",
        style="green",
    ))

    pipeline = ProjectPipeline(
        root=root,
        hw_profile=hw,
        backend=backend,
        build=not no_build,
        profile_binary=binary,
        profile_tool=profile_tool,
        profile_report=profile_report,
        top_hotspot_n=top_n,
        validate=validate,
        apply_patches=apply,
        dry_run=dry_run,
        console=console,
        ollama_model=ollama_model,
        ollama_host=ollama_host,
        compat_url=compat_url,
        compat_model=compat_model,
        compat_key=compat_key,
    )
    result = pipeline.run()
    raise typer.Exit(0 if result.success else 1)


@project_app.command("status")
def project_status(
    root: Path = typer.Argument(..., help="Project root directory"),
    patch_dir: Optional[Path] = typer.Option(None, "--patch-dir"),
):
    """[bold]Show optimization status[/bold] — which files have patches ready."""
    from perflens.project.crawler import ProjectCrawler
    from rich.table import Table
    from rich import box as rbox

    graph     = ProjectCrawler(root=root).crawl()
    pd        = patch_dir or (root / "perflens_patches")

    table = Table(title=f"Patch Status — {root.name}", box=rbox.ROUNDED)
    table.add_column("File",    width=35)
    table.add_column("Lang",    width=7)
    table.add_column("Patched", width=9, justify="center")
    table.add_column("Patch path")

    patched = 0
    for sf in graph.source_files:
        rel         = sf.path.relative_to(root)
        patch_path  = pd / rel
        has_patch   = patch_path.exists()
        if has_patch:
            patched += 1
        table.add_row(
            sf.path.name[:34],
            sf.language,
            "[green]✓[/green]" if has_patch else "—",
            str(patch_path) if has_patch else "",
        )

    console.print(table)
    console.print(f"\nTotal: {patched}/{len(graph.source_files)} files patched")
    console.print(f"Patch dir: {pd}")


@project_app.command("diff")
def project_diff(
    root: Path = typer.Argument(..., help="Project root directory"),
    patch_dir: Optional[Path] = typer.Option(None, "--patch-dir"),
    file_filter: str = typer.Option("", "--file",
        help="Only show diff for files matching this name"),
):
    """[bold]Show unified diff[/bold] between original and patched files."""
    import difflib
    from perflens.project.crawler import ProjectCrawler

    graph = ProjectCrawler(root=root).crawl()
    pd    = patch_dir or (root / "perflens_patches")

    if not pd.exists():
        console.print(f"[yellow]No patch directory at {pd}[/yellow]")
        raise typer.Exit(0)

    found = 0
    for sf in graph.source_files:
        if file_filter and file_filter not in sf.path.name:
            continue
        rel        = sf.path.relative_to(root)
        patch_path = pd / rel
        if not patch_path.exists():
            continue

        orig   = sf.path.read_text(errors="replace").splitlines(keepends=True)
        patched = patch_path.read_text(errors="replace").splitlines(keepends=True)
        diff    = list(difflib.unified_diff(
            orig, patched,
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
            n=3,
        ))
        if diff:
            found += 1
            changed = sum(1 for l in diff if l.startswith(("+", "-"))
                          and not l.startswith(("+++", "---")))
            console.print(f"\n[bold cyan]{'─'*60}[/bold cyan]")
            console.print(f"[bold]{rel}[/bold]  "
                          f"[green]+{sum(1 for l in diff if l.startswith('+') and not l.startswith('+++'))}[/green]"
                          f"[red] -{sum(1 for l in diff if l.startswith('-') and not l.startswith('---'))}[/red]"
                          f"  ({changed} lines changed)")
            from rich.syntax import Syntax
            console.print(Syntax("".join(diff[:120]), "diff",
                                 theme="monokai", line_numbers=False))

    if found == 0:
        console.print("[dim]No diffs found.[/dim]")



    if value:
        console.print(f"perflens {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", callback=_version_callback, is_eager=True),
):
    """🔬 PerfLens — Automated HPC Code Optimization Framework"""


if __name__ == "__main__":
    app()
