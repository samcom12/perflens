"""
Ollama backend — calls a locally-running Ollama server (http://localhost:11434).

No API key required. Install: https://ollama.com/download
Recommended models for HPC code:
  ollama pull codellama:34b          # best for C/C++/Fortran
  ollama pull deepseek-coder:33b     # strong on C/Python
  ollama pull llama3:70b             # strong general reasoning
  ollama pull mistral:7b             # fast, lightweight

Usage::

    perflens optimize solver.c --backend ollama --ollama-model codellama:34b
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Optional

from perflens.optimizer.backends.base import BackendCapabilities, LLMBackend

_DEFAULT_HOST  = "http://localhost:11434"
_DEFAULT_MODEL = "codellama:34b"

# Models known to work well for HPC code optimization
RECOMMENDED_MODELS = [
    ("codellama:34b",       "Best for C/C++/Fortran, large context"),
    ("deepseek-coder:33b",  "Strong on C/Python/structured output"),
    ("llama3:70b",          "Best reasoning, slower"),
    ("llama3:8b",           "Fast, good for quick passes"),
    ("mistral:7b",          "Lightweight, low VRAM"),
    ("qwen2.5-coder:32b",   "Strong on code generation"),
    ("phi4:14b",            "Good quality/speed trade-off"),
]


class OllamaBackend(LLMBackend):
    """
    Backend for locally-running Ollama instances.
    No API key needed — runs entirely on your hardware.

    Args:
        model:   Ollama model tag, e.g. ``codellama:34b``
        host:    Ollama server URL (default ``http://localhost:11434``)
        timeout: HTTP timeout in seconds (default 300s for large models)
        num_ctx: Context window size override (default: model default)
        temperature: Sampling temperature (default 0.1 for deterministic code)
    """

    def __init__(
        self,
        model: str = _DEFAULT_MODEL,
        host: str = _DEFAULT_HOST,
        timeout: int = 300,
        num_ctx: Optional[int] = None,
        temperature: float = 0.1,
    ):
        self.model       = model
        self.host        = host.rstrip("/")
        self.timeout     = timeout
        self.num_ctx     = num_ctx
        self.temperature = temperature

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            name=f"ollama/{self.model}",
            requires_api_key=False,
            supports_code_generation=True,
            max_context_tokens=self.num_ctx or 8192,
            local=True,
            notes=f"Local Ollama at {self.host}. No API key needed.",
        )

    def is_available(self) -> bool:
        """Check if Ollama server is reachable and model is pulled."""
        try:
            req = urllib.request.Request(f"{self.host}/api/tags")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
            pulled = [m["name"] for m in data.get("models", [])]
            # Accept both "codellama:34b" and "codellama" (latest tag)
            base = self.model.split(":")[0]
            return any(self.model == p or base == p.split(":")[0] for p in pulled)
        except Exception:
            return False

    def generate(self, system: str, messages: list[dict], max_tokens: int = 4096) -> str:
        """
        Use the Ollama /api/chat endpoint with OpenAI-style message format.
        Falls back to /api/generate if chat endpoint is unavailable.
        """
        payload = {
            "model":  self.model,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": max_tokens,
            },
            "messages": [{"role": "system", "content": system}] + messages,
        }
        if self.num_ctx:
            payload["options"]["num_ctx"] = self.num_ctx

        body = json.dumps(payload).encode()
        req  = urllib.request.Request(
            f"{self.host}/api/chat",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read())
            return result.get("message", {}).get("content", "")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                # Older Ollama: fall back to /api/generate
                return self._generate_legacy(system, messages, max_tokens)
            raise RuntimeError(
                f"Ollama API error {e.code}: {e.read().decode()}\n"
                f"Make sure the model is pulled: ollama pull {self.model}"
            )
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Cannot reach Ollama at {self.host}: {e.reason}\n"
                "Start Ollama: ollama serve"
            )

    def _generate_legacy(
        self, system: str, messages: list[dict], max_tokens: int
    ) -> str:
        """Fallback to /api/generate for older Ollama versions."""
        # Combine system + messages into a single prompt
        prompt_parts = [f"<<SYS>>\n{system}\n<</SYS>>\n"]
        for m in messages:
            role    = m.get("role", "user")
            content = m.get("content", "")
            if role == "user":
                prompt_parts.append(f"[INST] {content} [/INST]")
            elif role == "assistant":
                prompt_parts.append(content)
        prompt = "\n".join(prompt_parts)

        payload = {
            "model":  self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
                "num_predict": max_tokens,
            },
        }
        body = json.dumps(payload).encode()
        req  = urllib.request.Request(
            f"{self.host}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            result = json.loads(resp.read())
        return result.get("response", "")

    def list_local_models(self) -> list[str]:
        """Return list of models currently pulled in this Ollama instance."""
        try:
            req = urllib.request.Request(f"{self.host}/api/tags")
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []
