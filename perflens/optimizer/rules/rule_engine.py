"""
Rule Engine Backend — applies all applicable rules to a source file.

This is a **zero-LLM, zero-API-key** backend. It uses only:
  - Static analysis findings from the scanner
  - Hardware profile information
  - Regex / AST-level pattern matching

All transformations are safe (additive pragmas, reciprocal hoisting, etc.)
and are validated by the same PatchValidator used for LLM-generated code.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from perflens.optimizer.backends.base import BackendCapabilities, LLMBackend
from perflens.optimizer.models import OptimizationResult, Patch
from perflens.optimizer.rules.base_rule import RuleContext, TransformRule


def _load_all_rules() -> list[TransformRule]:
    """Instantiate every concrete rule class."""
    from perflens.optimizer.rules.c_rules import (
        OpenMPParallelRule,
        OpenMPSIMDRule,
        OpenMPOffloadRule,
        DivisionHoistRule,
        MPINonBlockingRule,
        LoopTilingRule,
    )
    from perflens.optimizer.rules.python_rules import (
        ScalarMathToNumpyRule,
        PreAllocateRule,
        NumbaAnnotateRule,
        PandasIterrowsRule,
    )
    from perflens.optimizer.rules.fortran_rules import (
        ImplicitNoneRule,
        FortranOpenMPDoRule,
        FortranOpenMPSIMDRule,
        FortranMPINonBlockingRule,
    )
    return [
        # C/C++
        LoopTilingRule(),
        DivisionHoistRule(),
        OpenMPParallelRule(),
        OpenMPSIMDRule(),
        OpenMPOffloadRule(),
        MPINonBlockingRule(),
        # Python
        ScalarMathToNumpyRule(),
        PreAllocateRule(),
        NumbaAnnotateRule(),
        PandasIterrowsRule(),
        # Fortran
        ImplicitNoneRule(),
        FortranOpenMPDoRule(),
        FortranOpenMPSIMDRule(),
        FortranMPINonBlockingRule(),
    ]


class RuleEngine:
    """
    Applies a sequence of TransformRules to a source file.

    Designed to be run directly (not through the LLM backend interface)
    or called from the engine via the RuleEngineBackend shim.
    """

    def __init__(self, rules: Optional[list[TransformRule]] = None):
        self._rules = rules if rules is not None else _load_all_rules()

    # ── Public API ────────────────────────────────────────────────────────────

    def run(
        self,
        source_path: Path,
        source_text: str,
        language: str,
        hardware,          # HardwareProfile
        findings: list,    # list[Finding]
    ) -> OptimizationResult:
        """Apply all applicable rules and return a single OptimizationResult."""
        ctx = RuleContext(
            source=source_text,
            language=language,
            path=source_path,
            hardware=hardware,
            findings=findings,
        )

        current_source = source_text
        all_patches: list[Patch] = []
        applied_rules: list[str] = []

        for rule in self._rules:
            # Language filter
            if language not in rule.supported_languages:
                continue
            # Quick applicability check
            try:
                if not rule.applies(ctx):
                    continue
            except Exception:
                continue

            # Apply rule on current (possibly already-modified) source
            ctx_current = RuleContext(
                source=current_source,
                language=language,
                path=source_path,
                hardware=hardware,
                findings=findings,
            )
            try:
                result = rule.apply(ctx_current)
            except Exception as exc:
                continue

            if result is None:
                continue

            new_source, patches = result
            if new_source == current_source:
                continue

            current_source = new_source
            all_patches.extend(patches)
            applied_rules.append(rule.name)

        explanation = (
            f"Rule engine applied {len(applied_rules)} transformations: "
            + ", ".join(applied_rules)
            if applied_rules
            else "No applicable rules found for this source/hardware combination."
        )

        return OptimizationResult(
            source=source_path,
            iteration=0,
            patches=all_patches,
            optimized_source=current_source if current_source != source_text else None,
            llm_explanation=explanation,
            tokens_used=0,
        )

    def list_applicable(
        self,
        source_text: str,
        language: str,
        hardware,
        findings: list,
    ) -> list[str]:
        """Return names of all rules that would fire on this source."""
        ctx = RuleContext(
            source=source_text,
            language=language,
            path=Path("__check__"),
            hardware=hardware,
            findings=findings,
        )
        return [
            r.name for r in self._rules
            if language in r.supported_languages and r.applies(ctx)
        ]


# ── LLM backend shim (so RuleEngine works in the engine's backend slot) ───────

class RuleEngineBackend(LLMBackend):
    """
    A LLMBackend shim that delegates to the RuleEngine.

    This means the OptimizationEngine can select ``backend="rules"``
    and the entire pipeline works without any LLM.

    The ``generate()`` method is never called — the engine checks for
    this class and calls ``run_rules()`` directly.
    """

    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            name="rule-engine",
            requires_api_key=False,
            supports_code_generation=True,
            max_context_tokens=0,          # unlimited (no token budget)
            local=True,
            notes=(
                "Zero-LLM rule-based engine. No API key required. "
                "Applies: loop tiling, OpenMP parallel/SIMD/offload, "
                "MPI non-blocking, division hoisting, NumPy vectorisation, "
                "Numba annotation, Fortran IMPLICIT NONE."
            ),
        )

    def generate(self, system: str, messages: list[dict], max_tokens: int = 4096) -> str:
        # Should not be called; engine uses run_rules() path
        raise NotImplementedError(
            "RuleEngineBackend does not call an LLM. "
            "Use OptimizationEngine.optimize() which detects this backend."
        )

    def run_rules(
        self,
        source_path: Path,
        source_text: str,
        language: str,
        hardware,
        findings: list,
    ) -> OptimizationResult:
        engine = RuleEngine()
        return engine.run(source_path, source_text, language, hardware, findings)
