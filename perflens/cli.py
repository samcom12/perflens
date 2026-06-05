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

hw_app = typer.Typer(help="Hardware database commands")
app.add_typer(hw_app, name="hw")


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

def _version_callback(value: bool):
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
