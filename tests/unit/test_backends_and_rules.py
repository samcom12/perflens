"""Tests for multi-backend system and rule-based engine."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from perflens.optimizer.backends.base import BackendCapabilities, LLMBackend
from perflens.optimizer.backends.registry import create_backend, list_backends
from perflens.optimizer.rules.rule_engine import RuleEngine, RuleEngineBackend
from perflens.optimizer.rules.base_rule import RuleContext
from perflens.hardware.database import HardwareDatabase


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def hw_a100():
    return HardwareDatabase().get("a100")

@pytest.fixture
def hw_intel():
    return HardwareDatabase().get("intel_spr")

@pytest.fixture
def hw_no_gpu():
    return HardwareDatabase().get("intel_spr")


# ══════════════════════════════════════════════════════════════════════════════
# Backend Registry
# ══════════════════════════════════════════════════════════════════════════════

def test_create_backend_rules():
    b = create_backend("rules")
    assert isinstance(b, RuleEngineBackend)
    assert not b.capabilities.requires_api_key
    assert b.capabilities.local

def test_create_backend_ollama():
    from perflens.optimizer.backends.ollama_backend import OllamaBackend
    b = create_backend("ollama")
    assert isinstance(b, OllamaBackend)
    assert not b.capabilities.requires_api_key

def test_create_backend_ollama_with_model():
    from perflens.optimizer.backends.ollama_backend import OllamaBackend
    b = create_backend("ollama:llama3:8b")
    assert isinstance(b, OllamaBackend)
    assert b.model == "llama3:8b"

def test_create_backend_anthropic():
    from perflens.optimizer.backends.anthropic_backend import AnthropicBackend
    b = create_backend("anthropic")
    assert isinstance(b, AnthropicBackend)
    assert b.capabilities.requires_api_key

def test_create_backend_groq():
    from perflens.optimizer.backends.openai_compat_backend import OpenAICompatBackend
    b = create_backend("groq")
    assert isinstance(b, OpenAICompatBackend)
    assert "groq" in b.base_url

def test_create_backend_lmstudio():
    from perflens.optimizer.backends.openai_compat_backend import OpenAICompatBackend
    b = create_backend("lmstudio")
    assert isinstance(b, OpenAICompatBackend)
    assert "localhost" in b.base_url

def test_create_backend_llamacpp():
    from perflens.optimizer.backends.openai_compat_backend import OpenAICompatBackend
    b = create_backend("llamacpp")
    assert isinstance(b, OpenAICompatBackend)

def test_create_backend_vllm():
    from perflens.optimizer.backends.openai_compat_backend import OpenAICompatBackend
    b = create_backend("vllm")
    assert isinstance(b, OpenAICompatBackend)

def test_create_backend_unknown_raises():
    with pytest.raises(ValueError, match="Unknown backend"):
        create_backend("nonexistent_backend_xyz")

def test_list_backends_returns_all():
    rows = list_backends()
    names = [r["name"] for r in rows]
    assert "rules"    in names
    assert "ollama"   in names
    assert "groq"     in names
    assert "anthropic" in names

def test_list_backends_rules_always_available():
    rows = list_backends()
    rules_row = next(r for r in rows if r["name"] == "rules")
    assert rules_row["available"] is True
    assert rules_row["requires_key"] is False


# ══════════════════════════════════════════════════════════════════════════════
# RuleEngineBackend capabilities
# ══════════════════════════════════════════════════════════════════════════════

def test_rule_engine_backend_capabilities():
    b = RuleEngineBackend()
    caps = b.capabilities
    assert caps.name == "rule-engine"
    assert not caps.requires_api_key
    assert caps.local is True

def test_rule_engine_backend_generate_raises():
    b = RuleEngineBackend()
    with pytest.raises(NotImplementedError):
        b.generate("system", [{"role": "user", "content": "x"}])

def test_rule_engine_backend_is_available():
    b = RuleEngineBackend()
    assert b.is_available() is True


# ══════════════════════════════════════════════════════════════════════════════
# C/C++ Rules
# ══════════════════════════════════════════════════════════════════════════════

C_PARALLEL_LOOP = textwrap.dedent("""\
    #include <math.h>
    void compute(double *a, double *b, int n) {
        for (int i = 0; i < n; i++) {
            a[i] = b[i] * 2.0;
        }
    }
""")

C_SIMD_INNER = textwrap.dedent("""\
    void nested(double *a, double *b, int n, int m) {
        for (int i = 0; i < n; i++) {
            for (int j = 0; j < m; j++) {
                a[i*m+j] = b[i*m+j] * 2.0;
            }
        }
    }
""")

C_DIVISION_LOOP = textwrap.dedent("""\
    void norm(double *a, double scale, int n) {
        for (int i = 0; i < n; i++) {
            a[i] = a[i] / scale;
        }
    }
""")

C_MPI_BLOCKING = textwrap.dedent("""\
    #include <mpi.h>
    void exchange(double *buf, int n) {
        int rank;
        MPI_Comm_rank(MPI_COMM_WORLD, &rank);
        MPI_Send(buf, n, MPI_DOUBLE, rank+1, 0, MPI_COMM_WORLD);
        MPI_Recv(buf, n, MPI_DOUBLE, rank-1, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
    }
""")

C_TRIPLE_NEST = textwrap.dedent("""\
    #define N 512
    void matmul(double a[N][N], double b[N][N], double c[N][N]) {
        for (int i = 0; i < N; i++) {
            for (int j = 0; j < N; j++) {
                for (int k = 0; k < N; k++) {
                    c[i][j] += a[i][k] * b[k][j];
                }
            }
        }
    }
""")

C_GPU_LOOP = textwrap.dedent("""\
    void saxpy(double *y, const double *x, double a, int n) {
        for (int i = 0; i < n; i++) {
            y[i] = a * x[i] + y[i];
        }
    }
""")


def _make_ctx(source, language, hw, findings=None):
    from perflens.scanner.models import Finding
    return RuleContext(
        source=source, language=language,
        path=Path(f"test.{language}"),
        hardware=hw,
        findings=findings or [],
    )


class TestOpenMPParallelRule:
    def test_applies_multicores(self, hw_intel):
        from perflens.optimizer.rules.c_rules import OpenMPParallelRule
        r = OpenMPParallelRule()
        ctx = _make_ctx(C_PARALLEL_LOOP, "c", hw_intel)
        assert r.applies(ctx)

    def test_inserts_pragma(self, hw_intel):
        from perflens.optimizer.rules.c_rules import OpenMPParallelRule
        r   = OpenMPParallelRule()
        ctx = _make_ctx(C_PARALLEL_LOOP, "c", hw_intel)
        result = r.apply(ctx)
        assert result is not None
        new_src, patches = result
        assert "#pragma omp parallel for" in new_src
        assert len(patches) >= 1
        assert patches[0].expected_speedup is not None

    def test_does_not_duplicate(self, hw_intel):
        from perflens.optimizer.rules.c_rules import OpenMPParallelRule
        r   = OpenMPParallelRule()
        src = "#pragma omp parallel for\n" + C_PARALLEL_LOOP
        ctx = _make_ctx(src, "c", hw_intel)
        assert not r.applies(ctx)

    def test_not_applicable_python(self, hw_intel):
        from perflens.optimizer.rules.c_rules import OpenMPParallelRule
        r   = OpenMPParallelRule()
        ctx = _make_ctx("for i in range(n): pass", "python", hw_intel)
        assert not r.applies(ctx)


class TestOpenMPSIMDRule:
    def test_applies_simd_hw(self, hw_a100):
        from perflens.optimizer.rules.c_rules import OpenMPSIMDRule
        r   = OpenMPSIMDRule()
        ctx = _make_ctx(C_SIMD_INNER, "c", hw_a100)
        assert r.applies(ctx)

    def test_inserts_simd_pragma(self, hw_a100):
        from perflens.optimizer.rules.c_rules import OpenMPSIMDRule
        r   = OpenMPSIMDRule()
        ctx = _make_ctx(C_SIMD_INNER, "c", hw_a100)
        result = r.apply(ctx)
        assert result is not None
        new_src, patches = result
        assert "#pragma omp simd" in new_src


class TestOpenMPOffloadRule:
    def test_applies_gpu(self, hw_a100):
        from perflens.optimizer.rules.c_rules import OpenMPOffloadRule
        r   = OpenMPOffloadRule()
        ctx = _make_ctx(C_GPU_LOOP, "c", hw_a100)
        assert r.applies(ctx)

    def test_not_applies_no_gpu(self, hw_intel):
        from perflens.optimizer.rules.c_rules import OpenMPOffloadRule
        r   = OpenMPOffloadRule()
        ctx = _make_ctx(C_GPU_LOOP, "c", hw_intel)
        assert not r.applies(ctx)

    def test_inserts_target_pragma(self, hw_a100):
        from perflens.optimizer.rules.c_rules import OpenMPOffloadRule
        r   = OpenMPOffloadRule()
        ctx = _make_ctx(C_GPU_LOOP, "c", hw_a100)
        result = r.apply(ctx)
        assert result is not None
        new_src, patches = result
        assert "#pragma omp target" in new_src
        assert patches[0].transform_kind.value == "openmp_offload"


class TestDivisionHoistRule:
    def test_applies_when_finding_present(self, hw_a100):
        from perflens.optimizer.rules.c_rules import DivisionHoistRule
        from perflens.scanner.models import Finding, FindingKind, Severity
        r = DivisionHoistRule()
        finding = Finding(Path("x.c"), 3, 0, FindingKind.DIVISION_IN_LOOP,
                          Severity.MEDIUM, "div", "hoist")
        ctx = _make_ctx(C_DIVISION_LOOP, "c", hw_a100, [finding])
        assert r.applies(ctx)

    def test_hoists_reciprocal(self, hw_a100):
        from perflens.optimizer.rules.c_rules import DivisionHoistRule
        from perflens.scanner.models import Finding, FindingKind, Severity
        r = DivisionHoistRule()
        finding = Finding(Path("x.c"), 3, 0, FindingKind.DIVISION_IN_LOOP,
                          Severity.MEDIUM, "div", "hoist")
        ctx = _make_ctx(C_DIVISION_LOOP, "c", hw_a100, [finding])
        result = r.apply(ctx)
        assert result is not None
        new_src, patches = result
        assert "inv_scale" in new_src or "* inv" in new_src


class TestMPINonBlockingRule:
    def test_applies_on_blocking_calls(self, hw_a100):
        from perflens.optimizer.rules.c_rules import MPINonBlockingRule
        r = MPINonBlockingRule()
        ctx = _make_ctx(C_MPI_BLOCKING, "c", hw_a100)
        assert r.applies(ctx)

    def test_converts_to_nonblocking(self, hw_a100):
        from perflens.optimizer.rules.c_rules import MPINonBlockingRule
        r = MPINonBlockingRule()
        ctx = _make_ctx(C_MPI_BLOCKING, "c", hw_a100)
        result = r.apply(ctx)
        assert result is not None
        new_src, patches = result
        assert "MPI_Isend" in new_src
        assert "MPI_Irecv" in new_src
        assert "MPI_Waitall" in new_src

    def test_not_applies_python(self, hw_a100):
        from perflens.optimizer.rules.c_rules import MPINonBlockingRule
        r = MPINonBlockingRule()
        ctx = _make_ctx("no mpi here", "python", hw_a100)
        assert not r.applies(ctx)


class TestLoopTilingRule:
    def test_applies_triple_nest(self, hw_a100):
        from perflens.optimizer.rules.c_rules import LoopTilingRule
        r = LoopTilingRule()
        ctx = _make_ctx(C_TRIPLE_NEST, "c", hw_a100)
        assert r.applies(ctx)

    def test_produces_tiled_source(self, hw_a100):
        from perflens.optimizer.rules.c_rules import LoopTilingRule
        r = LoopTilingRule()
        ctx = _make_ctx(C_TRIPLE_NEST, "c", hw_a100)
        result = r.apply(ctx)
        assert result is not None
        new_src, patches = result
        assert "TILE" in new_src
        assert patches[0].metadata.get("tile_size", 0) > 0

    def test_tile_size_positive(self, hw_a100):
        from perflens.optimizer.rules.c_rules import _compute_tile_size
        tile = _compute_tile_size(hw_a100)
        assert tile > 0
        # Must be a power of 2
        assert (tile & (tile - 1)) == 0


# ══════════════════════════════════════════════════════════════════════════════
# Python Rules
# ══════════════════════════════════════════════════════════════════════════════

PY_MATH_CALLS = textwrap.dedent("""\
    import math
    import numpy as np

    def compute(a):
        result = []
        for x in a:
            result.append(math.sin(x) + math.exp(x))
        return result
""")

PY_ALLOC_LOOP = textwrap.dedent("""\
    import numpy as np

    def bad(n, iters):
        for i in range(iters):
            tmp = np.zeros(n)
            tmp[0] = i
        return tmp
""")

PY_ITERROWS_SRC = textwrap.dedent("""\
    import pandas as pd

    def slow(df):
        total = 0
        for idx, row in df.iterrows():
            total += row['val']
        return total
""")


class TestScalarMathToNumpyRule:
    def test_applies_math_import(self, hw_a100):
        from perflens.optimizer.rules.python_rules import ScalarMathToNumpyRule
        r   = ScalarMathToNumpyRule()
        ctx = _make_ctx(PY_MATH_CALLS, "python", hw_a100)
        assert r.applies(ctx)

    def test_replaces_math_sin(self, hw_a100):
        from perflens.optimizer.rules.python_rules import ScalarMathToNumpyRule
        r   = ScalarMathToNumpyRule()
        ctx = _make_ctx(PY_MATH_CALLS, "python", hw_a100)
        result = r.apply(ctx)
        assert result is not None
        new_src, patches = result
        assert "np.sin" in new_src
        assert "np.exp" in new_src
        assert "math.sin" not in new_src

    def test_not_applies_without_math(self, hw_a100):
        from perflens.optimizer.rules.python_rules import ScalarMathToNumpyRule
        r   = ScalarMathToNumpyRule()
        ctx = _make_ctx("import numpy as np\nresult = np.sin(x)", "python", hw_a100)
        assert not r.applies(ctx)


class TestPreAllocateRule:
    def test_applies_with_finding(self, hw_a100):
        from perflens.optimizer.rules.python_rules import PreAllocateRule
        from perflens.scanner.models import Finding, FindingKind, Severity
        r = PreAllocateRule()
        finding = Finding(Path("x.py"), 4, 0, FindingKind.EXCESSIVE_ALLOCATION,
                          Severity.HIGH, "alloc", "preallocate")
        ctx = _make_ctx(PY_ALLOC_LOOP, "python", hw_a100, [finding])
        assert r.applies(ctx)

    def test_hoists_allocation(self, hw_a100):
        from perflens.optimizer.rules.python_rules import PreAllocateRule
        from perflens.scanner.models import Finding, FindingKind, Severity
        r = PreAllocateRule()
        finding = Finding(Path("x.py"), 4, 0, FindingKind.EXCESSIVE_ALLOCATION,
                          Severity.HIGH, "alloc", "preallocate")
        ctx = _make_ctx(PY_ALLOC_LOOP, "python", hw_a100, [finding])
        result = r.apply(ctx)
        assert result is not None
        new_src, patches = result
        # allocation should appear before the for loop
        alloc_pos = new_src.find("np.zeros")
        for_pos   = new_src.find("for i in range")
        assert alloc_pos < for_pos or "hoisted" in new_src


class TestPandasIterrowsRule:
    def test_applies(self, hw_a100):
        from perflens.optimizer.rules.python_rules import PandasIterrowsRule
        r   = PandasIterrowsRule()
        ctx = _make_ctx(PY_ITERROWS_SRC, "python", hw_a100)
        assert r.applies(ctx)

    def test_inserts_hint(self, hw_a100):
        from perflens.optimizer.rules.python_rules import PandasIterrowsRule
        r   = PandasIterrowsRule()
        ctx = _make_ctx(PY_ITERROWS_SRC, "python", hw_a100)
        result = r.apply(ctx)
        assert result is not None
        new_src, patches = result
        assert "PERFLENS" in new_src
        assert len(patches) == 1


# ══════════════════════════════════════════════════════════════════════════════
# Fortran Rules
# ══════════════════════════════════════════════════════════════════════════════

F_NO_IMPLICIT = textwrap.dedent("""\
    SUBROUTINE compute(a, n)
      INTEGER n
      REAL(8) a(n)
      INTEGER :: i
      DO i = 1, n
        a(i) = a(i) * 2.0
      END DO
    END SUBROUTINE
""")

F_DO_LOOPS = textwrap.dedent("""\
    SUBROUTINE work(a, n, m)
      IMPLICIT NONE
      INTEGER, INTENT(IN)    :: n, m
      REAL(8), INTENT(INOUT) :: a(n, m)
      INTEGER :: i, j
      DO i = 1, n
        DO j = 1, m
          a(i,j) = a(i,j) * 2.0_8
        END DO
      END DO
    END SUBROUTINE
""")

F_MPI_BLOCKING = textwrap.dedent("""\
    SUBROUTINE exchange(buf, n)
      USE mpi
      IMPLICIT NONE
      INTEGER, INTENT(IN)    :: n
      REAL(8), INTENT(INOUT) :: buf(n)
      INTEGER :: ierr
      CALL MPI_SEND(buf, n, MPI_DOUBLE_PRECISION, 1, 0, MPI_COMM_WORLD, ierr)
      CALL MPI_RECV(buf, n, MPI_DOUBLE_PRECISION, 0, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE, ierr)
    END SUBROUTINE
""")


class TestImplicitNoneRule:
    def test_applies_missing(self, hw_a100):
        from perflens.optimizer.rules.fortran_rules import ImplicitNoneRule
        r   = ImplicitNoneRule()
        ctx = _make_ctx(F_NO_IMPLICIT, "fortran", hw_a100)
        assert r.applies(ctx)

    def test_inserts_implicit_none(self, hw_a100):
        from perflens.optimizer.rules.fortran_rules import ImplicitNoneRule
        r   = ImplicitNoneRule()
        ctx = _make_ctx(F_NO_IMPLICIT, "fortran", hw_a100)
        result = r.apply(ctx)
        assert result is not None
        new_src, patches = result
        assert "IMPLICIT NONE" in new_src.upper()

    def test_not_applies_if_present(self, hw_a100):
        from perflens.optimizer.rules.fortran_rules import ImplicitNoneRule
        r   = ImplicitNoneRule()
        ctx = _make_ctx(F_DO_LOOPS, "fortran", hw_a100)
        assert not r.applies(ctx)


class TestFortranOpenMPDoRule:
    def test_applies_multicores(self, hw_a100):
        from perflens.optimizer.rules.fortran_rules import FortranOpenMPDoRule
        r   = FortranOpenMPDoRule()
        ctx = _make_ctx(F_DO_LOOPS, "fortran", hw_a100)
        assert r.applies(ctx)

    def test_inserts_omp_do(self, hw_a100):
        from perflens.optimizer.rules.fortran_rules import FortranOpenMPDoRule
        r   = FortranOpenMPDoRule()
        ctx = _make_ctx(F_DO_LOOPS, "fortran", hw_a100)
        result = r.apply(ctx)
        assert result is not None
        new_src, patches = result
        assert "!$OMP PARALLEL DO" in new_src.upper()
        assert "!$OMP END PARALLEL DO" in new_src.upper()


class TestFortranMPINonBlockingRule:
    def test_applies(self, hw_a100):
        from perflens.optimizer.rules.fortran_rules import FortranMPINonBlockingRule
        r   = FortranMPINonBlockingRule()
        ctx = _make_ctx(F_MPI_BLOCKING, "fortran", hw_a100)
        assert r.applies(ctx)

    def test_converts_to_isend(self, hw_a100):
        from perflens.optimizer.rules.fortran_rules import FortranMPINonBlockingRule
        r   = FortranMPINonBlockingRule()
        ctx = _make_ctx(F_MPI_BLOCKING, "fortran", hw_a100)
        result = r.apply(ctx)
        assert result is not None
        new_src, patches = result
        assert "MPI_ISEND" in new_src.upper()
        assert "MPI_IRECV" in new_src.upper()


# ══════════════════════════════════════════════════════════════════════════════
# RuleEngine (orchestrator)
# ══════════════════════════════════════════════════════════════════════════════

def test_rule_engine_runs_c(hw_a100, tmp_path):
    engine = RuleEngine()
    result = engine.run(
        source_path=tmp_path / "test.c",
        source_text=C_PARALLEL_LOOP,
        language="c",
        hardware=hw_a100,
        findings=[],
    )
    assert result is not None
    # Should find at least one applicable rule
    assert len(result.patches) >= 1

def test_rule_engine_runs_python(hw_a100, tmp_path):
    engine = RuleEngine()
    result = engine.run(
        source_path=tmp_path / "test.py",
        source_text=PY_MATH_CALLS,
        language="python",
        hardware=hw_a100,
        findings=[],
    )
    assert result is not None

def test_rule_engine_runs_fortran(hw_a100, tmp_path):
    engine = RuleEngine()
    result = engine.run(
        source_path=tmp_path / "test.f90",
        source_text=F_DO_LOOPS,
        language="fortran",
        hardware=hw_a100,
        findings=[],
    )
    assert result is not None

def test_rule_engine_gpu_fires_offload(hw_a100, tmp_path):
    engine = RuleEngine()
    result = engine.run(
        source_path=tmp_path / "saxpy.c",
        source_text=C_GPU_LOOP,
        language="c",
        hardware=hw_a100,
        findings=[],
    )
    kinds = {p.transform_kind.value for p in result.patches}
    assert "openmp_offload" in kinds   # A100 has GPU, should fire

def test_rule_engine_no_gpu_no_offload(hw_intel, tmp_path):
    engine = RuleEngine()
    result = engine.run(
        source_path=tmp_path / "saxpy.c",
        source_text=C_GPU_LOOP,
        language="c",
        hardware=hw_intel,
        findings=[],
    )
    kinds = {p.transform_kind.value for p in result.patches}
    assert "openmp_offload" not in kinds   # No GPU

def test_rule_engine_list_applicable(hw_a100):
    engine = RuleEngine()
    applicable = engine.list_applicable(
        source_text=C_PARALLEL_LOOP,
        language="c",
        hardware=hw_a100,
        findings=[],
    )
    assert isinstance(applicable, list)
    assert len(applicable) >= 1

def test_rule_engine_tokens_zero(hw_a100, tmp_path):
    """Rule engine never calls an LLM — token count should be 0."""
    engine = RuleEngine()
    result = engine.run(tmp_path / "t.c", C_PARALLEL_LOOP, "c", hw_a100, [])
    assert result.tokens_used == 0
