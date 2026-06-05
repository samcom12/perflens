"""Abstract base class for all source-level transformation rules."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from perflens.hardware.models import HardwareProfile
from perflens.optimizer.models import Patch, TransformKind
from perflens.scanner.models import Finding


@dataclass
class RuleContext:
    """Everything a rule needs to decide whether and how to apply itself."""
    source: str              # full source text
    language: str            # c | cpp | fortran | python
    path: Path
    hardware: HardwareProfile
    findings: list[Finding]


class TransformRule(ABC):
    """
    A single source-level transformation.

    Rules are cheap to run (no LLM call) and operate by:
      1. Checking whether they apply to this source/language/hardware
      2. Applying regex or AST-level rewrites
      3. Returning a Patch describing what changed
    """

    # Subset of languages this rule supports
    supported_languages: set[str] = {"c", "cpp", "fortran", "python"}

    @property
    @abstractmethod
    def name(self) -> str:
        ...

    @property
    @abstractmethod
    def transform_kind(self) -> TransformKind:
        ...

    @abstractmethod
    def applies(self, ctx: RuleContext) -> bool:
        """Return True if this rule can improve the source."""
        ...

    @abstractmethod
    def apply(self, ctx: RuleContext) -> Optional[tuple[str, list[Patch]]]:
        """
        Apply the transformation.

        Returns:
            (new_source, patches) if the rule modified the code,
            None if nothing changed.
        """
        ...
