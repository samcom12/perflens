"""Anthropic Claude API backend — requires ANTHROPIC_API_KEY."""

from __future__ import annotations

import os
from typing import Optional

from perflens.optimizer.backends.base import BackendCapabilities, LLMBackend

_DEFAULT_MODEL = "claude-opus-4-5"


class AnthropicBackend(LLMBackend):
    """
    Calls the Anthropic Messages API.
    Requires: ``export ANTHROPIC_API_KEY=sk-ant-...``
    """

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        api_key: Optional[str] = None,
    ):
        self.model   = model
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            name=f"anthropic/{self.model}",
            requires_api_key=True,
            supports_code_generation=True,
            max_context_tokens=200_000,
            local=False,
            notes="Best quality. Requires ANTHROPIC_API_KEY.",
        )

    def is_available(self) -> bool:
        return bool(self.api_key)

    def generate(self, system: str, messages: list[dict], max_tokens: int = 8192) -> str:
        if not self.api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY not set. "
                "Either export it or switch to a key-free backend:\n"
                "  perflens optimize <file> --backend ollama\n"
                "  perflens optimize <file> --backend rules"
            )
        try:
            import anthropic
        except ImportError:
            raise ImportError("pip install anthropic")

        client   = anthropic.Anthropic(api_key=self.api_key)
        response = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=messages,
        )
        return "".join(b.text for b in response.content if hasattr(b, "text"))
