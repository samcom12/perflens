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
    # When True, a SKIP of this check means we could NOT establish correctness,
    # so the overall report must not be considered "passed" for a patch that
    # changes program semantics. This closes the silent-skip hole.
    critical: bool = False


@dataclass
class ValidationReport:
    original: Path
    patched: Path
    checks: list[CheckResult] = field(default_factory=list)
    numerical_diff_max: Optional[float] = None
    tolerance: float = 1e-6
    # Set by the validator: True if the patch is known to alter program
    # behaviour in a way that REQUIRES a numerical/test check to be trusted.
    semantics_may_change: bool = False
    # Set True once correctness was positively established (tests passed or
    # numerical diff within tolerance).
    correctness_verified: bool = False

    @property
    def passed(self) -> bool:
        # Any hard failure → fail.
        if any(c.status == CheckStatus.FAIL for c in self.checks):
            return False
        # A critical check that was skipped means we could not verify
        # something essential → fail closed (do NOT mark as passed).
        if any(c.critical and c.status == CheckStatus.SKIP for c in self.checks):
            return False
        # If the patch may change numerical results, correctness must have
        # been positively verified (tests or numerical diff), not just skipped.
        if self.semantics_may_change and not self.correctness_verified:
            return False
        return True

    @property
    def verdict(self) -> str:
        if self.passed:
            return "passed"
        if any(c.status == CheckStatus.FAIL for c in self.checks):
            return "failed"
        return "unverified"   # compiled but correctness could not be established

    def print(self, console: Console) -> None:
        _verdict_str = {
            "passed":     "[bold green]✓ PASSED[/bold green]",
            "failed":     "[bold red]✗ FAILED[/bold red]",
            "unverified": "[bold yellow]⚠ UNVERIFIED (correctness not established)[/bold yellow]",
        }[self.verdict]
        console.print(f"\nValidation: {_verdict_str}")

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
