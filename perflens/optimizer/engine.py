"""
LLM Optimization Engine — drives Anthropic Claude to produce
source-level performance transformations.

Features:
- Multi-iteration optimization loop (each iteration sees the previous result)
- Structured JSON patch extraction
- Full rewritten source extraction
- Token budget tracking
- Dry-run mode (show proposed patches, do not write files)
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Optional

from perflens.hardware.database import HardwareDatabase
from perflens.hardware.detector import detect_hardware
from perflens.hardware.models import HardwareProfile
from perflens.optimizer.models import OptimizationResult, Patch, TransformKind
from perflens.optimizer.prompt_builder import _SYSTEM_PROMPT, build_optimization_prompt
from perflens.profiler.models import ProfileData
from perflens.scanner.dispatcher import detect_language, scan_file
from perflens.scanner.models import Finding

_MODEL = "claude-opus-4-5"
_MAX_TOKENS = 8192


class OptimizationEngine:
    """
    Iteratively apply LLM-driven optimizations to a source file.

    Usage::

        engine = OptimizationEngine(hw_profile="a100", max_iterations=3)
        results = engine.optimize(Path("solver.c"), profile_data=pd)
    """

    def __init__(
        self,
        hw_profile: str = "auto",
        max_iterations: int = 3,
        dry_run: bool = False,
        api_key: Optional[str] = None,
    ):
        self.max_iterations = max_iterations
        self.dry_run = dry_run
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")

        db = HardwareDatabase()
        if hw_profile == "auto":
            self.hardware = detect_hardware()
        else:
            hw = db.get(hw_profile)
            if hw is None:
                raise ValueError(f"Unknown hardware profile '{hw_profile}'. "
                                 f"Available: {db.list_ids()}")
            self.hardware = hw

    # ── Public API ────────────────────────────────────────────────────────────

    def optimize(
        self,
        source: Path,
        profile_data: Optional[ProfileData] = None,
        findings: Optional[list[Finding]] = None,
    ) -> list[OptimizationResult]:
        """
        Run up to *max_iterations* optimization passes on *source*.

        Returns a list of OptimizationResult (one per iteration).
        """
        if not self._api_key:
            raise EnvironmentError(
                "ANTHROPIC_API_KEY not set. Export it before running perflens optimize."
            )

        language = detect_language(source)
        if findings is None:
            findings = scan_file(source, language=language)

        current_source = source.read_text(errors="replace")
        results: list[OptimizationResult] = []
        total_tokens = 0

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
            total_tokens += result.tokens_used

            if not result.success:
                break

            # Feed optimized source into next iteration
            if result.optimized_source:
                current_source = result.optimized_source

            # Stop if no patches proposed (converged)
            if not result.patches:
                break

        return results

    # ── Private: single iteration ────────────────────────────────────────────

    def _run_iteration(
        self,
        source: Path,
        source_text: str,
        language: str,
        findings: list[Finding],
        profile_data: Optional[ProfileData],
        iteration: int,
    ) -> OptimizationResult:
        try:
            import anthropic
        except ImportError:
            return OptimizationResult(
                source=source, iteration=iteration,
                error="anthropic package not installed — run: pip install anthropic",
            )

        client = anthropic.Anthropic(api_key=self._api_key)

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
            response = client.messages.create(
                model=_MODEL,
                max_tokens=_MAX_TOKENS,
                system=_SYSTEM_PROMPT,
                messages=messages,
            )
        except Exception as exc:
            return OptimizationResult(
                source=source, iteration=iteration,
                error=f"Anthropic API error: {exc}",
            )

        raw_text = "".join(
            block.text for block in response.content if hasattr(block, "text")
        )
        tokens_used = response.usage.input_tokens + response.usage.output_tokens

        patches, explanation = self._parse_response(raw_text)
        optimized_source = self._extract_optimized_source(raw_text)

        return OptimizationResult(
            source=source,
            iteration=iteration,
            patches=patches,
            optimized_source=optimized_source,
            llm_explanation=explanation,
            tokens_used=tokens_used,
        )

    # ── Parsing helpers ───────────────────────────────────────────────────────

    @staticmethod
    def _parse_response(text: str) -> tuple[list[Patch], str]:
        """Extract the JSON patch list and explanation from the LLM response."""
        patches: list[Patch] = []
        explanation = ""

        # Find JSON block
        json_match = re.search(
            r"```json\s*(\{.*?\})\s*```",
            text, re.DOTALL,
        )
        if not json_match:
            # Try bare JSON object
            json_match = re.search(r"\{[^{}]*\"patches\"[^{}]*\[.*?\]\s*\}", text, re.DOTALL)

        if json_match:
            try:
                data = json.loads(json_match.group(1) if json_match.lastindex else json_match.group(0))
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
                        original_snippet="",   # filled in by validator if needed
                        optimized_snippet="",
                        start_line=int(p.get("start_line", 0)),
                        end_line=int(p.get("end_line", 0)),
                        rationale=p.get("rationale", ""),
                        expected_speedup=p.get("expected_speedup"),
                    ))
            except (json.JSONDecodeError, KeyError):
                pass

        # Fallback: extract explanation from text
        if not explanation:
            # Take first non-JSON paragraph
            clean = re.sub(r"```.*?```", "", text, flags=re.DOTALL)
            clean = re.sub(r"<optimized_source>.*</optimized_source>", "", clean, flags=re.DOTALL)
            explanation = clean.strip()[:2000]

        return patches, explanation

    @staticmethod
    def _extract_optimized_source(text: str) -> Optional[str]:
        """Pull the rewritten source from between <optimized_source> tags."""
        m = re.search(
            r"<optimized_source>\s*(.*?)\s*</optimized_source>",
            text, re.DOTALL,
        )
        if m:
            src = m.group(1).strip()
            # Strip any leftover markdown fences
            src = re.sub(r"^```\w*\n", "", src)
            src = re.sub(r"\n```$", "", src)
            return src

        # Fallback: last code block in response
        blocks = re.findall(r"```(?:\w+)?\n(.*?)```", text, re.DOTALL)
        if blocks:
            return blocks[-1].strip()
        return None
