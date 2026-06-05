"""
LLM Optimization Engine — multi-backend, iterative source transformation.

Supported backends (--backend flag):
  rules           Zero-LLM rule engine (no key needed, default)
  ollama          Local Ollama server (no key needed)
  ollama:<model>  Ollama with a specific model
  lmstudio        LM Studio local server (no key)
  llamacpp        llama.cpp local server (no key)
  vllm            vLLM local server (no key)
  groq            Groq cloud (free tier, no Anthropic key)
  anthropic       Anthropic Claude API (requires ANTHROPIC_API_KEY)
"""

from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Optional

from perflens.hardware.database import HardwareDatabase
from perflens.hardware.detector import detect_hardware
from perflens.hardware.models import HardwareProfile
from perflens.optimizer.backends.base import LLMBackend
from perflens.optimizer.backends.registry import create_backend
from perflens.optimizer.models import OptimizationResult, Patch, TransformKind
from perflens.optimizer.prompt_builder import _SYSTEM_PROMPT, build_optimization_prompt
from perflens.profiler.models import ProfileData
from perflens.scanner.dispatcher import detect_language, scan_file
from perflens.scanner.models import Finding

_MAX_TOKENS = 8192


class OptimizationEngine:
    """
    Iteratively apply optimizations to a source file.

    Backend selection::

        OptimizationEngine(backend="rules")           # no key, default
        OptimizationEngine(backend="ollama")          # local Ollama
        OptimizationEngine(backend="ollama:llama3:8b")
        OptimizationEngine(backend="groq")            # needs GROQ_API_KEY
        OptimizationEngine(backend="anthropic")       # needs ANTHROPIC_API_KEY
    """

    def __init__(
        self,
        hw_profile: str = "auto",
        max_iterations: int = 3,
        dry_run: bool = False,
        backend: str = "rules",
        # Backend-specific kwargs forwarded to create_backend()
        ollama_model: str = "codellama:34b",
        ollama_host: str = "http://localhost:11434",
        compat_url: Optional[str] = None,
        compat_model: Optional[str] = None,
        compat_key: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.max_iterations = max_iterations
        self.dry_run        = dry_run

        # Resolve hardware profile
        db = HardwareDatabase()
        if hw_profile == "auto":
            self.hardware = detect_hardware()
        else:
            hw = db.get(hw_profile)
            if hw is None:
                raise ValueError(
                    f"Unknown hardware profile '{hw_profile}'. "
                    f"Available: {db.list_ids()}"
                )
            self.hardware = hw

        # Resolve backend
        self.backend: LLMBackend = create_backend(
            backend,
            ollama_model=ollama_model,
            ollama_host=ollama_host,
            compat_url=compat_url,
            compat_model=compat_model,
            compat_key=compat_key,
            api_key=api_key,
        )
        self._backend_name = backend

    # ── Public API ────────────────────────────────────────────────────────────

    def optimize(
        self,
        source: Path,
        profile_data: Optional[ProfileData] = None,
        findings: Optional[list[Finding]] = None,
    ) -> list[OptimizationResult]:
        """Run up to *max_iterations* optimization passes on *source*."""
        language = detect_language(source)
        if findings is None:
            findings = scan_file(source, language=language)

        # ── Rule-engine path (no LLM) ─────────────────────────────────────
        from perflens.optimizer.rules.rule_engine import RuleEngineBackend
        if isinstance(self.backend, RuleEngineBackend):
            source_text = source.read_text(errors="replace")
            result = self.backend.run_rules(
                source_path=source,
                source_text=source_text,
                language=language,
                hardware=self.hardware,
                findings=findings,
            )
            return [result]

        # ── LLM path ──────────────────────────────────────────────────────
        if not self.backend.is_available():
            caps = self.backend.capabilities
            raise EnvironmentError(
                f"Backend '{caps.name}' is not available.\n"
                f"  Local: {caps.local}  Requires key: {caps.requires_api_key}\n"
                f"  Notes: {caps.notes}\n"
                f"\nTo use a key-free backend:\n"
                f"  perflens optimize {source} --backend rules\n"
                f"  perflens optimize {source} --backend ollama\n"
                f"  perflens optimize {source} --backend groq  (needs GROQ_API_KEY)"
            )

        current_source = source.read_text(errors="replace")
        results: list[OptimizationResult] = []

        for iteration in range(1, self.max_iterations + 1):
            result = self._run_iteration(
                source=source,
                source_text=current_source,
                language=language,
                findings=findings,
                profile_data=profile_data,
                iteration=iteration,
            )
            results.append(result)

            if not result.success:
                break
            if result.optimized_source:
                current_source = result.optimized_source
            if not result.patches:
                break   # converged

        return results

    # ── Single LLM iteration ──────────────────────────────────────────────────

    def _run_iteration(
        self,
        source: Path,
        source_text: str,
        language: str,
        findings: list[Finding],
        profile_data: Optional[ProfileData],
        iteration: int,
    ) -> OptimizationResult:
        messages = build_optimization_prompt(
            source=source,
            source_text=source_text,
            language=language,
            hardware=self.hardware,
            findings=findings,
            profile_data=profile_data,
            iteration=iteration,
        )
        try:
            raw_text = self.backend.generate(
                system=_SYSTEM_PROMPT,
                messages=messages,
                max_tokens=_MAX_TOKENS,
            )
        except Exception as exc:
            return OptimizationResult(
                source=source, iteration=iteration,
                error=f"{self.backend.capabilities.name} error: {exc}",
            )

        patches, explanation = self._parse_response(raw_text)
        optimized_source     = self._extract_optimized_source(raw_text)

        return OptimizationResult(
            source=source,
            iteration=iteration,
            patches=patches,
            optimized_source=optimized_source,
            llm_explanation=explanation,
            tokens_used=0,    # token tracking is backend-specific
        )

    # ── Response parsing ──────────────────────────────────────────────────────

    @staticmethod
    def _parse_response(text: str) -> tuple[list[Patch], str]:
        patches: list[Patch] = []
        explanation = ""

        json_match = re.search(r"```json\s*(\{.*?\})\s*```", text, re.DOTALL)
        if not json_match:
            json_match = re.search(r"\{[^{}]*\"patches\"[^{}]*\[.*?\]\s*\}", text, re.DOTALL)

        if json_match:
            try:
                data        = json.loads(json_match.group(1) if json_match.lastindex else json_match.group(0))
                explanation = data.get("explanation", "")
                for p in data.get("patches", []):
                    kind_str = p.get("transform_kind", "general")
                    try:
                        kind = TransformKind(kind_str)
                    except ValueError:
                        kind = TransformKind.GENERAL
                    patches.append(Patch(
                        transform_kind=kind,
                        description=p.get("description", ""),
                        original_snippet="",
                        optimized_snippet="",
                        start_line=int(p.get("start_line", 0)),
                        end_line=int(p.get("end_line", 0)),
                        rationale=p.get("rationale", ""),
                        expected_speedup=p.get("expected_speedup"),
                    ))
            except (json.JSONDecodeError, KeyError):
                pass

        if not explanation:
            clean = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
            clean = re.sub(r"<optimized_source>.*</optimized_source>", "", clean, flags=re.DOTALL)
            explanation = clean.strip()[:2000]

        return patches, explanation

    @staticmethod
    def _extract_optimized_source(text: str) -> Optional[str]:
        m = re.search(r"<optimized_source>\s*(.*?)\s*</optimized_source>", text, re.DOTALL)
        if m:
            src = m.group(1).strip()
            src = re.sub(r"^```\w*\n", "", src)
            src = re.sub(r"\n```$", "", src)
            return src
        blocks = re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
        if blocks:
            return blocks[-1].strip()
        return None
