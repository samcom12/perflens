"""
Backend registry — create a backend from a string name.

Supported backend strings::

    "anthropic"         Anthropic Claude (requires API key)
    "ollama"            Local Ollama server (no key)
    "ollama:llama3:8b"  Ollama with specific model
    "openai-compat"     OpenAI-compatible server (local or remote)
    "groq"              Groq cloud (free tier, fast)
    "together"          Together AI
    "openrouter"        OpenRouter
    "lmstudio"          LM Studio local server
    "llamacpp"          llama.cpp server
    "vllm"              vLLM local server
    "rules"             Rule-based engine (ZERO LLM, no key needed)
"""

from __future__ import annotations

from typing import Optional

from perflens.optimizer.backends.base import LLMBackend


def create_backend(
    name: str = "rules",
    *,
    # Ollama options
    ollama_model: str = "codellama:34b",
    ollama_host: str = "http://localhost:11434",
    # OpenAI-compat options
    compat_url: Optional[str]   = None,
    compat_model: Optional[str] = None,
    compat_key: Optional[str]   = None,
    # Anthropic options
    anthropic_model: str = "claude-opus-4-5",
    api_key: Optional[str] = None,
) -> LLMBackend:
    """
    Resolve *name* to a concrete backend instance.

    The ``rules`` backend requires no LLM at all and works offline.
    """
    n = name.lower().strip()

    # ── Rule-based (no LLM) ────────────────────────────────────────────────
    if n == "rules":
        from perflens.optimizer.rules.rule_engine import RuleEngineBackend
        return RuleEngineBackend()

    # ── Anthropic ──────────────────────────────────────────────────────────
    if n in ("anthropic", "claude"):
        from perflens.optimizer.backends.anthropic_backend import AnthropicBackend
        return AnthropicBackend(model=anthropic_model, api_key=api_key)

    # ── Ollama with optional model suffix: "ollama:codellama:34b" ──────────
    if n.startswith("ollama"):
        parts = name.split(":", 1)
        model = parts[1] if len(parts) > 1 else ollama_model
        from perflens.optimizer.backends.ollama_backend import OllamaBackend
        return OllamaBackend(model=model, host=ollama_host)

    # ── Named OpenAI-compat presets ───────────────────────────────────────
    _PRESETS = ("groq", "together", "openrouter", "fireworks",
                "cerebras", "lmstudio", "llamacpp", "vllm")
    if n in _PRESETS:
        from perflens.optimizer.backends.openai_compat_backend import OpenAICompatBackend
        return OpenAICompatBackend(preset=n, model=compat_model, api_key=compat_key)

    # ── Generic OpenAI-compat (arbitrary URL) ─────────────────────────────
    if n in ("openai-compat", "openai_compat", "compat"):
        from perflens.optimizer.backends.openai_compat_backend import OpenAICompatBackend
        return OpenAICompatBackend(
            base_url=compat_url,
            model=compat_model,
            api_key=compat_key,
        )

    raise ValueError(
        f"Unknown backend '{name}'. Valid options:\n"
        "  rules           — no LLM, no key (default)\n"
        "  ollama          — local Ollama server\n"
        "  ollama:<model>  — Ollama with specific model\n"
        "  anthropic       — Anthropic Claude API\n"
        "  groq            — Groq cloud (fast, free tier)\n"
        "  lmstudio        — LM Studio local\n"
        "  llamacpp        — llama.cpp server\n"
        "  vllm            — vLLM local server\n"
        "  openai-compat   — any OpenAI-compatible endpoint\n"
    )


def list_backends() -> list[dict]:
    """Return availability info for all known backends."""
    from perflens.optimizer.backends.ollama_backend import OllamaBackend
    from perflens.optimizer.backends.openai_compat_backend import OpenAICompatBackend, KNOWN_ENDPOINTS
    from perflens.optimizer.rules.rule_engine import RuleEngineBackend

    results = []

    # Rules (always available)
    rb = RuleEngineBackend()
    results.append({
        "name": "rules",
        "available": True,
        "requires_key": False,
        "local": True,
        "notes": rb.capabilities.notes,
    })

    # Ollama
    ob = OllamaBackend()
    results.append({
        "name": "ollama",
        "available": ob.is_available(),
        "requires_key": False,
        "local": True,
        "notes": f"Server at {ob.host} — pulled models: {ob.list_local_models()}",
    })

    # OpenAI-compat presets
    for preset_name, (url, env_key, default_model) in KNOWN_ENDPOINTS.items():
        import os
        key = os.environ.get(env_key, "") if env_key else "local"
        local = url.startswith("http://localhost")
        cb = OpenAICompatBackend(preset=preset_name)
        results.append({
            "name": preset_name,
            "available": cb.is_available(),
            "requires_key": bool(env_key),
            "local": local,
            "notes": f"{url}  model={default_model}",
        })

    # Anthropic
    import os
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    results.append({
        "name": "anthropic",
        "available": has_key,
        "requires_key": True,
        "local": False,
        "notes": "Requires ANTHROPIC_API_KEY env var",
    })

    return results
