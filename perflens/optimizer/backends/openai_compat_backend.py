"""
OpenAI-compatible backend.

Works with ANY server that speaks the OpenAI Chat Completions API:
  - vLLM:            vllm serve deepseek-ai/deepseek-coder-33b-instruct
  - LM Studio:       http://localhost:1234/v1
  - llama.cpp:       llama-server --port 8080
  - Together AI:     https://api.together.xyz/v1   (paid, no self-host needed)
  - Groq:            https://api.groq.com/openai/v1  (fast, free tier)
  - OpenRouter:      https://openrouter.ai/api/v1
  - Fireworks AI:    https://api.fireworks.ai/inference/v1
  - Cerebras:        https://api.cerebras.ai/v1

Usage::

    # Local vLLM (no key)
    perflens optimize solver.c --backend openai-compat \\
        --compat-url http://localhost:8000/v1 \\
        --compat-model deepseek-ai/deepseek-coder-33b-instruct

    # Groq (free tier, fast)
    export GROQ_API_KEY=gsk_...
    perflens optimize solver.c --backend openai-compat \\
        --compat-url https://api.groq.com/openai/v1 \\
        --compat-key $GROQ_API_KEY \\
        --compat-model llama3-70b-8192
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Optional

from perflens.optimizer.backends.base import BackendCapabilities, LLMBackend

# Well-known free/cheap public endpoints
KNOWN_ENDPOINTS = {
    "groq":      ("https://api.groq.com/openai/v1",         "GROQ_API_KEY",      "llama3-70b-8192"),
    "together":  ("https://api.together.xyz/v1",             "TOGETHER_API_KEY",  "codellama/CodeLlama-34b-Instruct-hf"),
    "openrouter":("https://openrouter.ai/api/v1",            "OPENROUTER_API_KEY","deepseek/deepseek-coder-33b-instruct"),
    "fireworks": ("https://api.fireworks.ai/inference/v1",   "FIREWORKS_API_KEY", "accounts/fireworks/models/deepseek-coder-v2-instruct"),
    "cerebras":  ("https://api.cerebras.ai/v1",              "CEREBRAS_API_KEY",  "llama3.1-70b"),
    "lmstudio":  ("http://localhost:1234/v1",                 None,                "local-model"),
    "llamacpp":  ("http://localhost:8080/v1",                 None,                "local-model"),
    "vllm":      ("http://localhost:8000/v1",                 None,                "local-model"),
}


class OpenAICompatBackend(LLMBackend):
    """
    Calls any OpenAI-compatible /chat/completions endpoint.

    Args:
        model:       Model identifier string
        base_url:    API base URL ending with /v1
        api_key:     Optional API key (or set via env var)
        timeout:     Request timeout in seconds
        temperature: Sampling temperature (0.1 = near-deterministic)
        preset:      Use a named preset from KNOWN_ENDPOINTS
                     (groq | together | openrouter | lmstudio | llamacpp | vllm)
    """

    def __init__(
        self,
        model: Optional[str]   = None,
        base_url: Optional[str] = None,
        api_key: Optional[str]  = None,
        timeout: int            = 300,
        temperature: float      = 0.1,
        preset: Optional[str]   = None,
    ):
        if preset and preset in KNOWN_ENDPOINTS:
            url, env_key, default_model = KNOWN_ENDPOINTS[preset]
            self.base_url = base_url or url
            self.model    = model    or default_model
            self.api_key  = api_key  or (os.environ.get(env_key, "") if env_key else "local")
        else:
            self.base_url = base_url or "http://localhost:8000/v1"
            self.model    = model    or "local-model"
            self.api_key  = api_key  or "local"

        self.timeout     = timeout
        self.temperature = temperature
        self._preset     = preset

    @property
    def capabilities(self) -> BackendCapabilities:
        local = self.base_url.startswith("http://localhost") or \
                self.base_url.startswith("http://127.")
        needs_key = self.api_key not in (None, "local", "")
        return BackendCapabilities(
            name=f"openai-compat/{self.model}",
            requires_api_key=needs_key,
            supports_code_generation=True,
            max_context_tokens=8192,
            local=local,
            notes=f"OpenAI-compatible at {self.base_url}",
        )

    def is_available(self) -> bool:
        try:
            req = urllib.request.Request(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            with urllib.request.urlopen(req, timeout=4):
                return True
        except Exception:
            return False

    def generate(self, system: str, messages: list[dict], max_tokens: int = 4096) -> str:
        payload = {
            "model":      self.model,
            "max_tokens": max_tokens,
            "temperature": self.temperature,
            "messages":   [{"role": "system", "content": system}] + messages,
        }
        body    = json.dumps(payload).encode()
        headers = {
            "Content-Type":  "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        req = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=body,
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                result = json.loads(resp.read())
            return result["choices"][0]["message"]["content"]
        except urllib.error.HTTPError as e:
            err = e.read().decode()
            raise RuntimeError(f"OpenAI-compat API error {e.code}: {err}")
        except urllib.error.URLError as e:
            raise RuntimeError(
                f"Cannot reach {self.base_url}: {e.reason}\n"
                "For local vLLM: vllm serve <model>\n"
                "For LM Studio: start the server in the LM Studio app"
            )
