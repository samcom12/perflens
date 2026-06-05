"""Unit tests for perflens.optimizer — models, prompt builder, response parsing."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest

from perflens.optimizer.models import OptimizationResult, Patch, TransformKind
from perflens.optimizer.engine import OptimizationEngine
from perflens.optimizer.prompt_builder import build_optimization_prompt


# ── TransformKind ─────────────────────────────────────────────────────────────

def test_transform_kind_values():
    assert TransformKind.LOOP_TILING.value == "loop_tiling"
    assert TransformKind.OPENMP_OFFLOAD.value == "openmp_offload"
    assert TransformKind.NUMPY_VECTORISE.value == "numpy_vectorise"


def test_transform_kind_from_string():
    kind = TransformKind("loop_interchange")
    assert kind == TransformKind.LOOP_INTERCHANGE


def test_transform_kind_fallback():
    """Unknown kind should fall back to GENERAL during parsing."""
    try:
        TransformKind("totally_unknown_kind")
        assert False, "should have raised"
    except ValueError:
        pass  # expected — engine uses GENERAL as fallback


# ── Patch model ───────────────────────────────────────────────────────────────

def test_patch_unified_diff():
    p = Patch(
        transform_kind=TransformKind.LOOP_TILING,
        description="Tile the i-loop",
        original_snippet="for (int i=0; i<N; i++) { a[i] = b[i]; }",
        optimized_snippet="for (int ii=0; ii<N; ii+=BS) {\n  for (int i=ii; i<ii+BS; i++) { a[i]=b[i]; }\n}",
        start_line=42, end_line=44,
        rationale="Improve L1 cache reuse",
        expected_speedup="1.5-2x",
    )
    diff = p.unified_diff()
    assert "---" in diff or "@@" in diff or diff == ""  # may be empty for one-liners


def test_patch_metadata_default():
    p = Patch(
        transform_kind=TransformKind.GENERAL,
        description="x", original_snippet="", optimized_snippet="",
        start_line=1, end_line=1, rationale="",
    )
    assert p.metadata == {}


# ── OptimizationResult ────────────────────────────────────────────────────────

def test_optimization_result_success():
    r = OptimizationResult(
        source=Path("solver.c"),
        iteration=1,
        patches=[Patch(TransformKind.VECTORIZATION, "vec", "", "",
                       10, 20, "rationale")],
        optimized_source="// optimized",
    )
    assert r.success is True


def test_optimization_result_failure():
    r = OptimizationResult(
        source=Path("solver.c"),
        iteration=1,
        error="API error",
    )
    assert r.success is False


def test_optimization_result_no_patches_no_source_not_success():
    r = OptimizationResult(source=Path("f.c"), iteration=1)
    assert r.success is False


def test_optimization_result_to_dict():
    p = Patch(TransformKind.LOOP_TILING, "tile", "", "", 5, 15, "cache", "2x")
    r = OptimizationResult(
        source=Path("solver.c"), iteration=2,
        patches=[p], tokens_used=4096,
    )
    d = r.to_dict()
    assert d["iteration"] == 2
    assert d["tokens_used"] == 4096
    assert len(d["patches"]) == 1
    assert d["patches"][0]["kind"] == "loop_tiling"
    assert d["patches"][0]["expected_speedup"] == "2x"


# ── Response parsing (private methods via engine) ────────────────────────────

def test_parse_response_json_block():
    raw = textwrap.dedent("""\
        Here are my proposed changes:

        ```json
        {
          "patches": [
            {
              "transform_kind": "loop_tiling",
              "description": "Tile the i-j loop nest",
              "start_line": 42,
              "end_line": 56,
              "rationale": "Improve L2 cache hit rate for 512x512 matrix",
              "expected_speedup": "2-3x"
            }
          ],
          "explanation": "The dominant bottleneck is cache thrashing in the loop nest."
        }
        ```

        <optimized_source>
        void kernel(double *a, int n) {
            // tiled version
        }
        </optimized_source>
    """)

    patches, explanation = OptimizationEngine._parse_response(raw)
    assert len(patches) == 1
    assert patches[0].transform_kind == TransformKind.LOOP_TILING
    assert patches[0].start_line == 42
    assert patches[0].expected_speedup == "2-3x"
    assert "bottleneck" in explanation


def test_parse_response_unknown_kind_becomes_general():
    raw = textwrap.dedent("""\
        ```json
        {
          "patches": [
            {
              "transform_kind": "some_future_transform",
              "description": "do something",
              "start_line": 1,
              "end_line": 10,
              "rationale": "because"
            }
          ],
          "explanation": "x"
        }
        ```
    """)
    patches, _ = OptimizationEngine._parse_response(raw)
    assert patches[0].transform_kind == TransformKind.GENERAL


def test_parse_response_empty_returns_empty():
    patches, explanation = OptimizationEngine._parse_response("")
    assert patches == []


def test_extract_optimized_source_tags():
    raw = "<optimized_source>\nvoid foo() { return; }\n</optimized_source>"
    src = OptimizationEngine._extract_optimized_source(raw)
    assert src is not None
    assert "void foo()" in src


def test_extract_optimized_source_code_fence_fallback():
    raw = "Here is the code:\n```c\nvoid bar() {}\n```"
    src = OptimizationEngine._extract_optimized_source(raw)
    assert src is not None
    assert "void bar()" in src


def test_extract_optimized_source_none_when_absent():
    raw = "No source code here, just explanation."
    src = OptimizationEngine._extract_optimized_source(raw)
    assert src is None


# ── Prompt builder ────────────────────────────────────────────────────────────

def test_build_prompt_contains_hardware_info():
    from perflens.hardware.database import HardwareDatabase
    hw = HardwareDatabase().get("a100")
    msgs = build_optimization_prompt(
        source=Path("solver.c"),
        source_text="void kernel(){}\n",
        language="c",
        hardware=hw,
        findings=[],
        profile_data=None,
        iteration=1,
    )
    assert len(msgs) == 1
    content = msgs[0]["content"]
    assert "A100" in content or "a100" in content.lower()
    assert "AVX-512" in content or "avx512" in content.lower()


def test_build_prompt_contains_source():
    from perflens.hardware.database import HardwareDatabase
    hw = HardwareDatabase().get("intel_spr")
    src = "double flux(double h) { return h * h; }\n"
    msgs = build_optimization_prompt(
        source=Path("flux.c"),
        source_text=src,
        language="c",
        hardware=hw,
        findings=[],
        profile_data=None,
        iteration=2,
    )
    assert src in msgs[0]["content"]


def test_build_prompt_iteration_number():
    from perflens.hardware.database import HardwareDatabase
    hw = HardwareDatabase().get("a100")
    msgs = build_optimization_prompt(
        source=Path("f.c"),
        source_text="",
        language="c",
        hardware=hw,
        findings=[],
        profile_data=None,
        iteration=3,
    )
    assert "Iteration 3" in msgs[0]["content"]


# ── Engine instantiation ──────────────────────────────────────────────────────

def test_engine_unknown_hw_raises():
    with pytest.raises(ValueError, match="Unknown hardware profile"):
        OptimizationEngine(hw_profile="nonexistent_gpu_xyz")


def test_engine_known_hw_ok():
    engine = OptimizationEngine(hw_profile="a100")
    assert engine.hardware.profile_id == "a100"


def test_engine_auto_hw_does_not_raise():
    # auto-detect should always return something
    engine = OptimizationEngine(hw_profile="auto")
    assert engine.hardware is not None


def test_engine_no_api_key_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    # Anthropic backend with empty key should raise when optimize() is called
    engine = OptimizationEngine(hw_profile="a100", backend="anthropic", api_key="")
    src = tmp_path / "test.c"
    src.write_text("void f(){}")
    with pytest.raises((EnvironmentError, RuntimeError)):
        engine.optimize(src)
