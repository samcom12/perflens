"""Tests for compiler_feedback and autotuner modules."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from perflens.compiler_feedback.models import (
    CompilerFeedbackReport, CompilerRemark, FeedbackKind,
)


# ══════════════════════════════════════════════════════════════════════════════
# GCC parser
# ══════════════════════════════════════════════════════════════════════════════

GCC_OPT_INFO = textwrap.dedent("""\
    solver.c:42:5: optimized: loop vectorized using 32-byte vectors
    solver.c:87:9: missed: couldn't vectorize loop
    solver.c:87:9: note: not vectorized: multiple loop exits.
    solver.c:100:5: optimized: loop vectorized using 16-byte vectors
    solver.c:112:3: missed: couldn't vectorize loop
    solver.c:112:3: note: not vectorized: data dependence prevents vectorization at 'solver.c:115'.
    solver.c:200:7: optimized: loop unrolled 4 times
""")


def test_gcc_parse_text(tmp_path):
    from perflens.compiler_feedback.gcc_parser import GCCFeedbackParser
    log = tmp_path / "gcc.log"
    log.write_text(GCC_OPT_INFO)
    report = GCCFeedbackParser().parse_file(log, source=Path("solver.c"))
    assert report.compiler == "gcc"
    assert len(report.remarks) > 0


def test_gcc_vectorized_count(tmp_path):
    from perflens.compiler_feedback.gcc_parser import GCCFeedbackParser
    log = tmp_path / "gcc.log"
    log.write_text(GCC_OPT_INFO)
    report = GCCFeedbackParser().parse_file(log, source=Path("solver.c"))
    assert len(report.vectorized_loops) >= 2


def test_gcc_missed_vectorization(tmp_path):
    from perflens.compiler_feedback.gcc_parser import GCCFeedbackParser
    log = tmp_path / "gcc.log"
    log.write_text(GCC_OPT_INFO)
    report = GCCFeedbackParser().parse_file(log, source=Path("solver.c"))
    assert len(report.missed_vectorization) >= 2


def test_gcc_line_numbers(tmp_path):
    from perflens.compiler_feedback.gcc_parser import GCCFeedbackParser
    log = tmp_path / "gcc.log"
    log.write_text(GCC_OPT_INFO)
    report = GCCFeedbackParser().parse_file(log, source=Path("solver.c"))
    lines = {r.line for r in report.remarks}
    assert 42  in lines
    assert 87  in lines
    assert 100 in lines


def test_gcc_scanner_hints(tmp_path):
    from perflens.compiler_feedback.gcc_parser import GCCFeedbackParser
    log = tmp_path / "gcc.log"
    log.write_text(GCC_OPT_INFO)
    report = GCCFeedbackParser().parse_file(log, source=Path("solver.c"))
    hints = report.to_scanner_hints()
    assert isinstance(hints, list)
    assert len(hints) >= 1
    assert any("NOT vectorized" in h or "vectorized" in h.lower() for h in hints)


# ══════════════════════════════════════════════════════════════════════════════
# Clang parser
# ══════════════════════════════════════════════════════════════════════════════

CLANG_REMARKS = textwrap.dedent("""\
    stencil.c:42:5: remark: vectorized loop (vectorization width: 8, interleaved count: 2) [-Rpass=loop-vectorize]
    stencil.c:87:9: remark: loop not vectorized: cannot identify array bounds [-Rpass-missed=loop-vectorize]
    stencil.c:112:3: remark: loop not vectorized: value that could not be identified as reduction is used outside the loop [-Rpass-missed=loop-vectorize]
    stencil.c:200:5: remark: 'compute_flux' inlined into 'run' [-Rpass=inline]
""")


def test_clang_parse_text(tmp_path):
    from perflens.compiler_feedback.clang_parser import ClangFeedbackParser
    log = tmp_path / "clang.log"
    log.write_text(CLANG_REMARKS)
    report = ClangFeedbackParser().parse_file(log, source=Path("stencil.c"))
    assert report.compiler == "clang"
    assert len(report.remarks) >= 3


def test_clang_vectorized_remark(tmp_path):
    from perflens.compiler_feedback.clang_parser import ClangFeedbackParser
    log = tmp_path / "clang.log"
    log.write_text(CLANG_REMARKS)
    report = ClangFeedbackParser().parse_file(log, source=Path("stencil.c"))
    assert len(report.vectorized_loops) >= 1
    assert report.vectorized_loops[0].line == 42


def test_clang_missed_vectorization(tmp_path):
    from perflens.compiler_feedback.clang_parser import ClangFeedbackParser
    log = tmp_path / "clang.log"
    log.write_text(CLANG_REMARKS)
    report = ClangFeedbackParser().parse_file(log, source=Path("stencil.c"))
    assert len(report.missed_vectorization) >= 2


# ══════════════════════════════════════════════════════════════════════════════
# ICX parser
# ══════════════════════════════════════════════════════════════════════════════

ICX_OPTRPT = textwrap.dedent("""\
    Begin optimization report for: compute_flux(double*, double*, int)
    Report from: Vector optimizations [vec]

    LOOP BEGIN at solver.c(42,5)
       remark #15305: vectorization support: vector length 8
       LOOP WAS VECTORIZED
    LOOP END

    LOOP BEGIN at solver.c(87,9)
       remark #15344: loop was not vectorized: vector dependence prevents vectorization
       remark #15346: vector dependence: assumed FLOW dependence between a[i] (89:9) and a[i] (89:9)
    LOOP END

    LOOP BEGIN at solver.c(112,3)
       remark #25439: unrolled with remainder by 4
    LOOP END
""")


def test_icx_parse_text(tmp_path):
    from perflens.compiler_feedback.clang_parser import ICXFeedbackParser
    rpt = tmp_path / "solver.optrpt"
    rpt.write_text(ICX_OPTRPT)
    report = ICXFeedbackParser().parse_file(rpt, source=Path("solver.c"))
    assert report.compiler == "icx"
    assert len(report.remarks) >= 2


def test_icx_vectorized(tmp_path):
    from perflens.compiler_feedback.clang_parser import ICXFeedbackParser
    rpt = tmp_path / "solver.optrpt"
    rpt.write_text(ICX_OPTRPT)
    report = ICXFeedbackParser().parse_file(rpt, source=Path("solver.c"))
    assert len(report.vectorized_loops) >= 1
    assert report.vectorized_loops[0].line == 42


def test_icx_missed(tmp_path):
    from perflens.compiler_feedback.clang_parser import ICXFeedbackParser
    rpt = tmp_path / "solver.optrpt"
    rpt.write_text(ICX_OPTRPT)
    report = ICXFeedbackParser().parse_file(rpt, source=Path("solver.c"))
    missed = report.missed_vectorization
    assert len(missed) >= 1
    assert missed[0].line == 87


# ══════════════════════════════════════════════════════════════════════════════
# Dispatcher
# ══════════════════════════════════════════════════════════════════════════════

def test_collect_feedback_gcc_log(tmp_path):
    from perflens.compiler_feedback import collect_feedback
    log = tmp_path / "gcc.log"
    log.write_text(GCC_OPT_INFO)
    src = tmp_path / "solver.c"
    src.write_text("void f(){}")
    report = collect_feedback(src, compiler="gcc", report_file=log)
    assert len(report.remarks) > 0

def test_collect_feedback_clang_log(tmp_path):
    from perflens.compiler_feedback import collect_feedback
    log = tmp_path / "clang.log"
    log.write_text(CLANG_REMARKS)
    src = tmp_path / "stencil.c"
    src.write_text("void f(){}")
    report = collect_feedback(src, compiler="clang", report_file=log)
    assert len(report.remarks) > 0

def test_collect_feedback_unknown_compiler_returns_empty(tmp_path):
    from perflens.compiler_feedback import collect_feedback
    src = tmp_path / "solver.c"
    src.write_text("void f(){}")
    # Nonexistent compiler, no report file — returns empty report, doesn't raise
    report = collect_feedback(src, compiler="nvfortran_xyz_nonexistent")
    assert isinstance(report, CompilerFeedbackReport)


# ══════════════════════════════════════════════════════════════════════════════
# CompilerRemark model
# ══════════════════════════════════════════════════════════════════════════════

def test_remark_to_dict():
    r = CompilerRemark(
        source_file="solver.c", line=42, col=5,
        kind=FeedbackKind.VECTORIZED,
        compiler="gcc", pass_name="loop-vectorize",
        message="loop vectorized using 32-byte vectors",
    )
    d = r.to_dict()
    assert d["line"] == 42
    assert d["kind"] == "vectorized"
    assert d["compiler"] == "gcc"

def test_report_vectorized_loops_filter():
    r1 = CompilerRemark("f.c", 10, 0, FeedbackKind.VECTORIZED,    "gcc", "lv", "ok")
    r2 = CompilerRemark("f.c", 20, 0, FeedbackKind.NOT_VECTORIZED, "gcc", "lv", "miss")
    r3 = CompilerRemark("f.c", 30, 0, FeedbackKind.VECTORIZED,     "gcc", "lv", "ok")
    report = CompilerFeedbackReport(source=Path("f.c"), compiler="gcc", remarks=[r1, r2, r3])
    assert len(report.vectorized_loops) == 2
    assert len(report.missed_vectorization) == 1

def test_report_empty_hints():
    report = CompilerFeedbackReport(source=Path("f.c"), compiler="gcc")
    hints = report.to_scanner_hints()
    assert hints == []


# ══════════════════════════════════════════════════════════════════════════════
# TileSearchTuner — unit tests (no actual compilation)
# ══════════════════════════════════════════════════════════════════════════════

def test_tuner_default_candidates():
    from perflens.autotuner.tile_tuner import TileSearchTuner
    from perflens.hardware.database import HardwareDatabase
    hw    = HardwareDatabase().get("a100")
    tuner = TileSearchTuner(source=Path("dummy.c"), hardware=hw)
    candidates = tuner._default_candidates()
    assert len(candidates) >= 2
    assert all(c > 0 for c in candidates)
    # All should be powers of 2
    assert all((c & (c - 1)) == 0 for c in candidates)

def test_tuner_no_tile_define(tmp_path):
    from perflens.autotuner.tile_tuner import TileSearchTuner
    from perflens.hardware.database import HardwareDatabase
    hw  = HardwareDatabase().get("intel_spr")
    src = tmp_path / "no_tile.c"
    src.write_text("void f(){}")   # no #define TILE
    tuner  = TileSearchTuner(source=src, hardware=hw)
    result = tuner.run(tile_candidates=[8, 16])
    # Should return gracefully with no valid points
    assert result.best.run_ok is False

def test_tuner_result_model():
    from perflens.autotuner.tile_tuner import TunePoint, TuneResult
    best = TunePoint(tile_size=32, runtime_ms=150.0, compile_ok=True, run_ok=True)
    result = TuneResult(best=best, baseline_ms=300.0, param_name="tile_size")
    summary = result.summary()
    assert "32" in summary
    assert "150" in summary

def test_tune_point_defaults():
    from perflens.autotuner.tile_tuner import TunePoint
    pt = TunePoint()
    assert pt.runtime_ms == float("inf")
    assert pt.compile_ok is False
    assert pt.run_ok is False
