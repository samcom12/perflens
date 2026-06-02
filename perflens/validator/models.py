"""Validation report models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich import box


class CheckStatus(str, Enum):
    PASS    = "pass"
    FAIL    = "fail"
    SKIP    = "skip"
    WARNING = "warning"


@dataclass
class CheckResult:
    name: str
    status: CheckStatus
    message: str = ""
    stdout: str = ""
    stderr: str = ""
    duration_s: float = 0.0


@dataclass
class ValidationReport:
    original: Path
    patched: Path
    checks: list[CheckResult] = field(default_factory=list)
    numerical_diff_max: Optional[float] = None
    tolerance: float = 1e-6

    @property
    def passed(self) -> bool:
        return all(c.status in (CheckStatus.PASS, CheckStatus.SKIP, CheckStatus.WARNING)
                   for c in self.checks)

    def print(self, console: Console) -> None:
        overall = "[bold green]✓ PASSED[/bold green]" if self.passed else "[bold red]✗ FAILED[/bold red]"
        console.print(f"\nValidation: {overall}")

        table = Table(title="Validation Checks", box=box.ROUNDED, show_lines=True)
        table.add_column("Check",    width=28)
        table.add_column("Status",   width=10)
        table.add_column("Duration", width=10, justify="right")
        table.add_column("Details")

        _colors = {
            CheckStatus.PASS:    "green",
            CheckStatus.FAIL:    "red",
            CheckStatus.SKIP:    "dim",
            CheckStatus.WARNING: "yellow",
        }
        _icons = {
            CheckStatus.PASS:    "✓",
            CheckStatus.FAIL:    "✗",
            CheckStatus.SKIP:    "—",
            CheckStatus.WARNING: "⚠",
        }

        for c in self.checks:
            col = _colors[c.status]
            icon = _icons[c.status]
            details = c.message
            if c.stderr and c.status == CheckStatus.FAIL:
                details += f"\n{c.stderr[:200]}"
            table.add_row(
                c.name,
                f"[{col}]{icon} {c.status.value.upper()}[/{col}]",
                f"{c.duration_s:.2f}s",
                details,
            )

        console.print(table)

        if self.numerical_diff_max is not None:
            tol_ok = self.numerical_diff_max <= self.tolerance
            diff_color = "green" if tol_ok else "red"
            console.print(
                f"\nMax numerical diff: [{diff_color}]{self.numerical_diff_max:.2e}[/{diff_color}]"
                f"  (tolerance={self.tolerance:.1e})"
            )
