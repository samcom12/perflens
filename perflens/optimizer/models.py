"""Data models for the LLM optimization engine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class TransformKind(str, Enum):
    LOOP_TILING           = "loop_tiling"
    LOOP_INTERCHANGE      = "loop_interchange"
    LOOP_FUSION           = "loop_fusion"
    LOOP_UNROLLING        = "loop_unrolling"
    VECTORIZATION         = "vectorization"
    OPENMP_PARALLELISE    = "openmp_parallelise"
    OPENMP_SIMD           = "openmp_simd"
    OPENMP_OFFLOAD        = "openmp_offload"
    MPI_NONBLOCKING       = "mpi_nonblocking"
    HOIST_INVARIANT       = "hoist_invariant"
    STRENGTH_REDUCTION    = "strength_reduction"
    MEMORY_LAYOUT         = "memory_layout"
    PREFETCH              = "prefetch"
    NUMPY_VECTORISE       = "numpy_vectorise"
    NUMBA_JIT             = "numba_jit"
    GENERAL               = "general"


@dataclass
class Patch:
    """A single source-level transformation proposed by the LLM."""
    transform_kind: TransformKind
    description: str
    original_snippet: str
    optimized_snippet: str
    start_line: int
    end_line: int
    rationale: str
    expected_speedup: Optional[str] = None   # e.g. "2–4×"
    metadata: dict = field(default_factory=dict)

    def unified_diff(self, context: int = 3) -> str:
        import difflib
        a = self.original_snippet.splitlines(keepends=True)
        b = self.optimized_snippet.splitlines(keepends=True)
        return "".join(difflib.unified_diff(
            a, b,
            fromfile="original",
            tofile="optimized",
            n=context,
        ))


@dataclass
class OptimizationResult:
    """Result of one LLM optimization pass on a source file."""
    source: Path
    iteration: int
    patches: list[Patch] = field(default_factory=list)
    optimized_source: Optional[str] = None
    llm_explanation: str = ""
    tokens_used: int = 0
    error: Optional[str] = None

    @property
    def success(self) -> bool:
        return self.error is None and bool(self.patches or self.optimized_source)

    def to_dict(self) -> dict:
        return {
            "source": str(self.source),
            "iteration": self.iteration,
            "patches": [
                {
                    "kind": p.transform_kind.value,
                    "description": p.description,
                    "lines": f"{p.start_line}–{p.end_line}",
                    "expected_speedup": p.expected_speedup,
                    "rationale": p.rationale,
                }
                for p in self.patches
            ],
            "tokens_used": self.tokens_used,
            "error": self.error,
        }
