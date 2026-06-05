"""
Abstract base class for all PerfLens LLM backends.

All backends must implement `generate(system, messages, max_tokens) -> str`.
The engine selects a backend at construction time; the rest of the pipeline
is identical regardless of which backend is active.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BackendCapabilities:
    """What a backend can and cannot do."""
    name: str
    requires_api_key: bool
    supports_code_generation: bool = True
    max_context_tokens: int = 8192
    supports_streaming: bool = False
    local: bool = False          # True = runs entirely on the machine
    notes: str = ""


class LLMBackend(ABC):
    """
    All LLM backends implement this interface.

    The engine calls::

        text = backend.generate(
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": "..."}],
            max_tokens=8192,
        )
    """

    @property
    @abstractmethod
    def capabilities(self) -> BackendCapabilities:
        ...

    @abstractmethod
    def generate(
        self,
        system: str,
        messages: list[dict],
        max_tokens: int = 4096,
    ) -> str:
        """Generate a completion and return the raw text response."""
        ...

    def is_available(self) -> bool:
        """Quick sanity-check (ping the API, check the model file exists, etc.)."""
        return True

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}({self.capabilities.name})"
