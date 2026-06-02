"""
PerfLens CLI — top-level command dispatcher.

Usage:
    perflens scan <file>
    perflens profile --tool vtune --report report.csv <file>
    perflens optimize <file> --hw a100
    perflens validate <original> <patched>
    perflens dashboard [--port 8080]
    perflens hw detect
    perflens hw list
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from perflens import __version__

app = typer.Typer(
    name="perflens",
    help="🔬 PerfLens — Automated HPC Code Optimization Framework",
    add_completion=False,
    rich_markup_mode="rich",
)

console = Console()

# ──────────────────────────────────────────────────────────────────────────────
# Sub-command groups
# ──────────────────────────────────────────────────────────────────────────────

hw_app = typer.Typer(help="Hardware database commands")
app.add_typer(hw_app, name="hw")


# ──────────────────────────────────────────────────────────────────────────────
# perflens scan
# ──────────────────────────────────────────────────────────────────────────────

@app.command()
def scan(
    source: Path = typer.Argument(..., help="Source file or directory to scan"),
    language: Optional[str] = typer.Option(None, "--lang", "-l", help="Force language (c/cpp/fortran/python)"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Write findings JSON to this path"),
    verbose: bool = typer.Option(False, "--verbose", "-v"),
):
    """[bold cyan]Static analysis[/bold cyan] — detect optimization opportunities via Clang AST / language parsers."""
    from perflens.scanner.dispatcher import scan_file

    console.print(Panel(f"[bold]PerfLens Scanner[/bold]  v{__version__}", style="cyan"))
    findings = scan_file(source, language=language, verbose=verbose)

    if output:
        import json
        output.write_text(json.dumps([f.to_dict() for f in findings], indent=2))
        console.print(f"[green]Findings written to {output}[/green]")
    else:
        from perflens.scanner.report import print_findings
        print_findings(findings, console)


# ──────────────────────────────────────────────────────────────────────────────
# perflens profile
# ──────────────────────────────────────────────────────────────────────────────

@app.command()
def profile(
    source: Path = typer.Argument(..., help="Source file being profiled"),
    tool: str = typer.Option("vtune", "--tool", "-t", help="Profiling tool: vtune | hpctoolkit"),
    report: Optional[Path] = typer.Option(None, "--report", "-r", help="Path to profiler report (CSV/XML/database)"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Write profile summary JSON"),
):
    """[bold cyan]Profile parsing[/bold cyan] — extract hotspot data from VTune or HPCToolkit reports."""
    from perflens.profiler.dispatcher import parse_profile

    console.print(Panel(f"[bold]PerfLens Profiler[/bold] [{tool.upper()}]", style="cyan"))
    profile_data = parse_profile(tool=tool, report_path=report, source=source)
    profile_data.print_summary(console)

    if output:
        import json
        output.write_text(json.dumps(profile_data.to_dict(), indent=2))
        console.print(f"[green]Profile summary written to {output}[/green]")


# ──────────────────────────────────────────────────────────────────────────────
# perflens optimize
# ──────────────────────────────────────────────────────────────────────────────

@app.command()
def optimize(
    source: Path = typer.Argument(..., help="Source file to optimize"),
    hw: str = typer.Option("auto", "--hw", help="Hardware profile ID (e.g. a100, intel_spr)"),
    profile_report: Optional[Path] = typer.Option(None, "--profile", "-p", help="Optional profiler report"),
    profile_tool: str = typer.Option("vtune", "--profile-tool"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="Write optimized source here"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print proposed patches without applying"),
    max_iterations: int = typer.Option(3, "--iterations", "-n", help="Max LLM optimization rounds"),
):
    """[bold green]Full optimization pipeline[/bold green] — scan → profile → LLM transform → validate."""
    from perflens.pipeline.orchestrator import PerfLensPipeline

    console.print(Panel(
        Text.from_markup(f"[bold green]PerfLens Optimizer[/bold green]  target=[cyan]{hw}[/cyan]  file=[yellow]{source}[/yellow]"),
        style="green",
    ))

    pipeline = PerfLensPipeline(
        hw_profile=hw,
        max_iterations=max_iterations,
        dry_run=dry_run,
        console=console,
    )
    result = pipeline.run(
        source=source,
        profile_report=profile_report,
        profile_tool=profile_tool,
        output=output,
    )
    pipeline.print_summary(result, console)


# ──────────────────────────────────────────────────────────────────────────────
# perflens validate
# ──────────────────────────────────────────────────────────────────────────────

@app.command()
def validate(
    original: Path = typer.Argument(..., help="Original source file"),
    patched: Path = typer.Argument(..., help="Patched source file"),
    test_dir: Optional[Path] = typer.Option(None, "--tests", "-t", help="Test suite directory"),
    tolerance: float = typer.Option(1e-6, "--tol", help="Numerical diff tolerance"),
):
    """[bold yellow]Patch validation[/bold yellow] — compile, run tests, numerical diff, regression gate."""
    from perflens.validator.checker import PatchValidator

    console.print(Panel("[bold]PerfLens Validator[/bold]", style="yellow"))
    validator = PatchValidator(tolerance=tolerance, console=console)
    report = validator.validate(original=original, patched=patched, test_dir=test_dir)
    report.print(console)
    sys.exit(0 if report.passed else 1)


# ──────────────────────────────────────────────────────────────────────────────
# perflens dashboard
# ──────────────────────────────────────────────────────────────────────────────

@app.command()
def dashboard(
    port: int = typer.Option(8080, "--port", "-p"),
    host: str = typer.Option("0.0.0.0", "--host"),
    db: Optional[Path] = typer.Option(None, "--db", help="Path to benchmark results SQLite DB"),
):
    """[bold magenta]Benchmark dashboard[/bold magenta] — launch Plotly/FastAPI web UI."""
    import uvicorn
    from perflens.dashboard.app import create_app

    console.print(Panel(f"[bold]PerfLens Dashboard[/bold]  http://{host}:{port}", style="magenta"))
    web_app = create_app(db_path=db)
    uvicorn.run(web_app, host=host, port=port, log_level="info")


# ──────────────────────────────────────────────────────────────────────────────
# perflens hw
# ──────────────────────────────────────────────────────────────────────────────

@hw_app.command("detect")
def hw_detect():
    """Auto-detect current hardware and print matching profile."""
    from perflens.hardware.detector import detect_hardware
    hw = detect_hardware()
    hw.print_summary(console)


@hw_app.command("list")
def hw_list():
    """List all built-in hardware profiles."""
    from perflens.hardware.database import HardwareDatabase
    db = HardwareDatabase()
    db.print_all(console)


@hw_app.command("show")
def hw_show(profile_id: str = typer.Argument(..., help="Hardware profile ID")):
    """Show detailed hardware profile."""
    from perflens.hardware.database import HardwareDatabase
    db = HardwareDatabase()
    hw = db.get(profile_id)
    if hw is None:
        console.print(f"[red]Unknown profile: {profile_id}[/red]")
        raise typer.Exit(1)
    hw.print_full(console)


# ──────────────────────────────────────────────────────────────────────────────

def version_callback(value: bool):
    if value:
        console.print(f"perflens {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", callback=version_callback, is_eager=True),
):
    """🔬 PerfLens — Automated HPC Code Optimization Framework"""


if __name__ == "__main__":
    app()
