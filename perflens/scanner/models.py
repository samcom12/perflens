"""Data models for scanner findings."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class Severity(str, Enum):
    CRITICAL = "critical"   # Definitely a hotspot / correctness risk
    HIGH     = "high"       # Strong optimization opportunity
    MEDIUM   = "medium"     # Moderate opportunity
    LOW      = "low"        # Minor / informational
    INFO     = "info"


class FindingKind(str, Enum):
    # Memory
    CACHE_UNFRIENDLY_ACCESS  = "cache_unfriendly_access"
    FALSE_SHARING            = "false_sharing"
    UNALIGNED_ACCESS         = "unaligned_access"
    EXCESSIVE_ALLOCATION     = "excessive_allocation"

    # Vectorization
    VECTORIZATION_INHIBITOR  = "vectorization_inhibitor"
    SCALAR_LOOP              = "scalar_loop"
    MISSING_SIMD_PRAGMA      = "missing_simd_pragma"

    # Parallelism
    MISSING_OMP_PARALLEL     = "missing_omp_parallel"
    MISSING_OMP_SIMD         = "missing_omp_simd"
    MISSING_OMP_OFFLOAD      = "missing_omp_offload"
    MPI_SYNCHRONOUS_HOTSPOT  = "mpi_synchronous_hotspot"
    RACE_CONDITION_RISK      = "race_condition_risk"

    # Loop structure
    LOOP_TILING_OPPORTUNITY  = "loop_tiling_opportunity"
    LOOP_FUSION_OPPORTUNITY  = "loop_fusion_opportunity"
    LOOP_INTERCHANGE         = "loop_interchange"
    REDUCTION_CANDIDATE      = "reduction_candidate"

    # Arithmetic
    DIVISION_IN_LOOP         = "division_in_loop"
    TRANSCENDENTAL_IN_LOOP   = "transcendental_in_loop"
    MIXED_PRECISION          = "mixed_precision"
    REDUNDANT_COMPUTATION    = "redundant_computation"

    # I/O
    UNBUFFERED_IO            = "unbuffered_io"
    IO_IN_LOOP               = "io_in_loop"

    # Language-specific
    NUMPY_LOOP               = "numpy_loop"          # Python: explicit loop over array
    GIL_BOTTLENECK           = "gil_bottleneck"      # Python threading
    FORTRAN_ARRAY_COPY       = "fortran_array_copy"  # Unnecessary temp array

    # General
    GENERAL                  = "general"


@dataclass
class Finding:
    """A single optimization opportunity found in source code."""
    file: Path
    line: int
    col: int
    kind: FindingKind
    severity: Severity
    message: str
    suggestion: str
    context_lines: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "file": str(self.file),
            "line": self.line,
            "col": self.col,
            "kind": self.kind.value,
            "severity": self.severity.value,
            "message": self.message,
            "suggestion": self.suggestion,
            "metadata": self.metadata,
        }

    @property
    def location(self) -> str:
        return f"{self.file}:{self.line}:{self.col}"
