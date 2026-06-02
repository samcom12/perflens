"""Rich terminal report for scanner findings."""

from __future__ import annotations

from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table
from rich import box

from perflens.scanner.models import Finding, Severity

_SEVERITY_COLOR = {
    Severity.CRITICAL: "bold red",
    Severity.HIGH:     "red",
    Severity.MEDIUM:   "yellow",
    Severity.LOW:      "cyan",
    Severity.INFO:     "dim",
}

_SEVERITY_ICON = {
    Severity.CRITICAL: "🔴",
    Severity.HIGH:     "🟠",
    Severity.MEDIUM:   "🟡",
    Severity.LOW:      "🔵",
    Severity.INFO:     "⚪",
}


def print_findings(findings: list[Finding], console: Console) -> None:
    if not findings:
        console.print("[bold green]✓ No optimization opportunities found.[/bold green]")
        return

    # Summary table
    table = Table(title="PerfLens Scan Results", box=box.ROUNDED, show_lines=True)
    table.add_column("Line",     style="dim", width=6)
    table.add_column("Severity", width=10)
    table.add_column("Kind",     width=28)
    table.add_column("Message")

    for f in sorted(findings, key=lambda x: (x.severity.value, x.line)):
        color = _SEVERITY_COLOR[f.severity]
        icon  = _SEVERITY_ICON[f.severity]
        table.add_row(
            str(f.line),
            f"[{color}]{icon} {f.severity.value.upper()}[/{color}]",
            f.kind.value.replace("_", " "),
            f.message,
        )

    console.print(table)
    console.print()

    # Detail cards
    for i, f in enumerate(findings, 1):
        color = _SEVERITY_COLOR[f.severity]
        icon  = _SEVERITY_ICON[f.severity]
        console.rule(f"[{color}]{icon} Finding {i}/{len(findings)} — {f.location}[/{color}]")
        console.print(f"[bold]Message:[/bold]    {f.message}")
        console.print(f"[bold]Suggestion:[/bold] [green]{f.suggestion}[/green]")
        if f.context_lines:
            code = "\n".join(f.context_lines)
            ext = f.file.suffix.lstrip(".")
            lang_map = {"c": "c", "cpp": "cpp", "cxx": "cpp", "f90": "fortran",
                        "f": "fortran", "py": "python"}
            lang = lang_map.get(ext, "text")
            console.print(Syntax(code, lang, line_numbers=True,
                                  start_line=max(1, f.line - 1), theme="monokai"))
        console.print()

    # Stats footer
    from collections import Counter
    counts = Counter(f.severity for f in findings)
    parts = [f"[{_SEVERITY_COLOR[s]}]{_SEVERITY_ICON[s]} {counts[s]} {s.value}[/{_SEVERITY_COLOR[s]}]"
             for s in Severity if counts[s] > 0]
    console.print("Summary: " + "  ".join(parts))
