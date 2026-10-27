"""Tests for perflens.project — crawler, build system detection, dependency graph."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from perflens.project.crawler import ProjectCrawler, _detect_build_system
from perflens.project.models import (
    BuildSystem, ProjectGraph, SourceFile,
    OptimizationPhase, ProjectOptimizationPlan,
)
from perflens.project.dependency_graph import DependencyGraph


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def simple_c_project(tmp_path: Path) -> Path:
    """A tiny 3-file C project with known includes."""
    inc = tmp_path / "include"
    src = tmp_path / "src"
    inc.mkdir(); src.mkdir()

    (inc / "utils.h").write_text("#pragma once\nvoid add(double*,int);")
    (src / "utils.c").write_text('#include "utils.h"\nvoid add(double*a,int n){for(int i=0;i<n;i++)a[i]+=1;}')
    (src / "main.c").write_text('#include "utils.h"\n#include <stdio.h>\nint main(){return 0;}')
    (tmp_path / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.16)\nproject(test C)")
    return tmp_path


@pytest.fixture
def fortran_project(tmp_path: Path) -> Path:
    (tmp_path / "solver.f90").write_text(textwrap.dedent("""\
        MODULE utils
          IMPLICIT NONE
        CONTAINS
          SUBROUTINE add(a, n)
            INTEGER, INTENT(IN) :: n
            REAL(8), INTENT(INOUT) :: a(n)
            a = a + 1.0_8
          END SUBROUTINE
        END MODULE

        PROGRAM main
          USE utils
          IMPLICIT NONE
          REAL(8) :: a(100)
          CALL add(a, 100)
        END PROGRAM
    """))
    (tmp_path / "Makefile").write_text("all:\n\tgfortran solver.f90 -o solver\n")
    return tmp_path


@pytest.fixture
def python_project(tmp_path: Path) -> Path:
    (tmp_path / "solver.py").write_text("import numpy as np\ndef run(): return np.zeros(10)")
    (tmp_path / "utils.py").write_text("def helper(): pass")
    (tmp_path / "pyproject.toml").write_text('[build-system]\nrequires=["setuptools"]\n')
    return tmp_path


@pytest.fixture
def example_project() -> Path:
    return Path(__file__).parent.parent.parent / "examples" / "project_hello"


# ══════════════════════════════════════════════════════════════════════════════
# Build system detection
# ══════════════════════════════════════════════════════════════════════════════

def test_detect_cmake(simple_c_project):
    assert _detect_build_system(simple_c_project) == BuildSystem.CMAKE

def test_detect_make(fortran_project):
    assert _detect_build_system(fortran_project) == BuildSystem.MAKE

def test_detect_python(python_project):
    assert _detect_build_system(python_project) == BuildSystem.PYTHON

def test_detect_bare(tmp_path):
    (tmp_path / "solver.c").write_text("int main(){}")
    assert _detect_build_system(tmp_path) == BuildSystem.BARE

def test_detect_meson(tmp_path):
    (tmp_path / "meson.build").write_text("project('test', 'c')")
    assert _detect_build_system(tmp_path) == BuildSystem.MESON


# ══════════════════════════════════════════════════════════════════════════════
# ProjectCrawler
# ══════════════════════════════════════════════════════════════════════════════

def test_crawler_finds_c_files(simple_c_project):
    graph = ProjectCrawler(root=simple_c_project).crawl()
    langs = {sf.language for sf in graph.files.values()}
    assert "c" in langs

def test_crawler_finds_correct_count(simple_c_project):
    graph = ProjectCrawler(root=simple_c_project).crawl()
    # utils.h, utils.c, main.c
    c_files = [sf for sf in graph.files.values() if sf.language == "c"]
    assert len(c_files) == 3

def test_crawler_build_system(simple_c_project):
    graph = ProjectCrawler(root=simple_c_project).crawl()
    assert graph.build_system == BuildSystem.CMAKE

def test_crawler_skips_build_dirs(simple_c_project):
    build = simple_c_project / "build"
    build.mkdir()
    (build / "generated.c").write_text("// auto-generated")
    graph = ProjectCrawler(root=simple_c_project).crawl()
    paths = {sf.path.name for sf in graph.files.values()}
    assert "generated.c" not in paths

def test_crawler_fortran(fortran_project):
    graph = ProjectCrawler(root=fortran_project).crawl()
    assert any(sf.language == "fortran" for sf in graph.files.values())

def test_crawler_python(python_project):
    graph = ProjectCrawler(root=python_project).crawl()
    assert any(sf.language == "python" for sf in graph.files.values())

def test_crawler_extension_filter(simple_c_project):
    graph = ProjectCrawler(root=simple_c_project, extensions={".c"}).crawl()
    exts = {sf.path.suffix for sf in graph.files.values()}
    assert ".h" not in exts
    assert ".c" in exts

def test_crawler_respects_max_files(tmp_path):
    for i in range(20):
        (tmp_path / f"file_{i}.c").write_text(f"void f{i}(){{}}")
    graph = ProjectCrawler(root=tmp_path, max_files=5).crawl()
    assert len(graph.files) <= 5

def test_crawler_example_project(example_project):
    if not example_project.exists():
        pytest.skip("example project not present")
    graph = ProjectCrawler(root=example_project).crawl()
    assert len(graph.source_files) >= 3
    names = {sf.path.name for sf in graph.source_files}
    assert "flux.c"   in names
    assert "solver.c" in names
    assert "io.c"     in names

def test_crawler_resolves_includes(simple_c_project):
    graph = ProjectCrawler(root=simple_c_project).crawl()
    # main.c includes utils.h — should be resolved
    main_sf = next(
        (sf for sf in graph.files.values() if sf.path.name == "main.c"), None
    )
    assert main_sf is not None
    include_names = {p.name for p in main_sf.includes}
    assert "utils.h" in include_names

def test_crawler_builds_included_by(simple_c_project):
    graph = ProjectCrawler(root=simple_c_project).crawl()
    utils_h = next(
        (sf for sf in graph.files.values() if sf.path.name == "utils.h"), None
    )
    assert utils_h is not None
    # Both main.c and utils.c include utils.h
    assert len(utils_h.included_by) >= 1


# ══════════════════════════════════════════════════════════════════════════════
# ProjectGraph model
# ══════════════════════════════════════════════════════════════════════════════

def test_source_files_excludes_headers(simple_c_project):
    graph = ProjectCrawler(root=simple_c_project).crawl()
    for sf in graph.source_files:
        assert not sf.is_header

def test_is_header_detection():
    assert SourceFile(Path("foo.h"),    "c").is_header
    assert SourceFile(Path("bar.hpp"),  "cpp").is_header
    assert not SourceFile(Path("a.c"),  "c").is_header
    assert not SourceFile(Path("b.py"), "python").is_header

def test_priority_score_with_hotspot():
    sf = SourceFile(Path("hot.c"), "c")
    sf.hotspot_pct = 40.0
    assert sf.priority_score > 20.0

def test_priority_score_with_compiler_misses():
    from perflens.compiler_feedback.models import (
        CompilerFeedbackReport, CompilerRemark, FeedbackKind,
    )
    sf = SourceFile(Path("x.c"), "c")
    remarks = [
        CompilerRemark("x.c", i, 0, FeedbackKind.NOT_VECTORIZED, "gcc", "lv", "miss")
        for i in range(5)
    ]
    sf.compiler_feedback = CompilerFeedbackReport(
        source=Path("x.c"), compiler="gcc", remarks=remarks
    )
    assert sf.priority_score > 5.0

def test_priority_score_zero_for_clean_file():
    sf = SourceFile(Path("clean.c"), "c")
    assert sf.priority_score == 0.0

def test_graph_language_breakdown(simple_c_project):
    graph = ProjectCrawler(root=simple_c_project).crawl()
    lb    = graph.language_breakdown()
    assert "c" in lb
    assert lb["c"] >= 2

def test_graph_total_lines(simple_c_project):
    graph = ProjectCrawler(root=simple_c_project).crawl()
    assert graph.total_lines() > 0

def test_graph_source_files_sorted_by_priority(simple_c_project):
    graph = ProjectCrawler(root=simple_c_project).crawl()
    # Manually set hotspot_pct
    files = list(graph.files.values())
    if len(files) >= 2:
        files[0].hotspot_pct = 50.0
        files[1].hotspot_pct = 10.0
    sorted_files = graph.source_files
    scores = [sf.priority_score for sf in sorted_files]
    assert scores == sorted(scores, reverse=True)

def test_source_file_to_dict():
    sf = SourceFile(Path("flux.c"), "c")
    sf.hotspot_pct = 23.4
    d = sf.to_dict()
    assert d["path"] == "flux.c"
    assert d["language"] == "c"
    assert d["hotspot_pct"] == 23.4
    assert "priority_score" in d


# ══════════════════════════════════════════════════════════════════════════════
# DependencyGraph
# ══════════════════════════════════════════════════════════════════════════════

def _make_graph_with_edges(tmp_path: Path) -> ProjectGraph:
    """Build a tiny 4-file graph with known edges."""
    paths = {
        "utils.h":  SourceFile(tmp_path / "utils.h",  "c"),
        "math.h_":  SourceFile(tmp_path / "mymath.h", "c"),
        "solver.c": SourceFile(tmp_path / "solver.c", "c"),
        "main.c":   SourceFile(tmp_path / "main.c",   "c"),
    }
    # solver.c → utils.h, mymath.h
    paths["solver.c"].includes = [paths["utils.h"].path, paths["math.h_"].path]
    paths["utils.h"].included_by  = [paths["solver.c"].path]
    paths["math.h_"].included_by  = [paths["solver.c"].path]
    # main.c → utils.h
    paths["main.c"].includes   = [paths["utils.h"].path]
    paths["utils.h"].included_by.append(paths["main.c"].path)

    graph = ProjectGraph(root=tmp_path, build_system=BuildSystem.BARE)
    for sf in paths.values():
        graph.files[sf.path] = sf
    return graph


def test_depgraph_topological_order(tmp_path):
    graph = _make_graph_with_edges(tmp_path)
    dg    = DependencyGraph(graph)
    order = dg.topological_order()
    # Headers (no outgoing edges) should come before files that include them
    utils_idx  = next(i for i, p in enumerate(order) if p.name == "utils.h")
    solver_idx = next(i for i, p in enumerate(order) if p.name == "solver.c")
    assert utils_idx < solver_idx

def test_depgraph_transitive_dependents(tmp_path):
    graph = _make_graph_with_edges(tmp_path)
    dg    = DependencyGraph(graph)
    utils_path = tmp_path / "utils.h"
    deps = dg.transitive_dependents(utils_path)
    dep_names = {p.name for p in deps}
    assert "solver.c" in dep_names or "main.c" in dep_names

def test_depgraph_shared_header(tmp_path):
    graph = _make_graph_with_edges(tmp_path)
    dg    = DependencyGraph(graph)
    utils_path = tmp_path / "utils.h"
    # utils.h is included by solver.c and main.c (2 files)
    assert dg.is_shared_header(utils_path, threshold=2)
    assert not dg.is_shared_header(utils_path, threshold=5)

def test_depgraph_shared_headers_list(tmp_path):
    graph = _make_graph_with_edges(tmp_path)
    dg    = DependencyGraph(graph)
    shared = dg.shared_headers(threshold=2)
    names  = {p.name for p in shared}
    assert "utils.h" in names

def test_depgraph_build_optimization_order(tmp_path):
    graph = _make_graph_with_edges(tmp_path)
    # Make solver.c a hotspot
    graph.files[tmp_path / "solver.c"].hotspot_pct = 45.0
    dg      = DependencyGraph(graph)
    batches = dg.build_optimization_order(top_hotspot_n=5)
    assert len(batches) >= 1
    batch0_names = {p.name for p in batches[0]}
    assert "solver.c" in batch0_names

def test_depgraph_dot_graph(tmp_path):
    graph = _make_graph_with_edges(tmp_path)
    dg    = DependencyGraph(graph)
    dot   = dg.dot_graph()
    assert "digraph" in dot
    assert "solver.c" in dot

def test_depgraph_no_cycles_crash(tmp_path):
    """Circular deps should not crash the topological sort."""
    a = SourceFile(tmp_path / "a.c", "c")
    b = SourceFile(tmp_path / "b.c", "c")
    a.includes = [b.path]; b.included_by = [a.path]
    b.includes = [a.path]; a.included_by = [b.path]
    graph = ProjectGraph(root=tmp_path, build_system=BuildSystem.BARE)
    graph.files[a.path] = a
    graph.files[b.path] = b
    dg    = DependencyGraph(graph)
    order = dg.topological_order()   # must not raise
    assert len(order) == 2


# ══════════════════════════════════════════════════════════════════════════════
# OptimizationPlan builder
# ══════════════════════════════════════════════════════════════════════════════

def test_build_plan_creates_phases(simple_c_project):
    from perflens.optimizer.project_optimizer import build_optimization_plan
    graph = ProjectCrawler(root=simple_c_project).crawl()
    plan  = build_optimization_plan(graph, backend="rules", min_priority=0.0)
    assert isinstance(plan, ProjectOptimizationPlan)
    assert plan.total_files >= 0   # may be 0 if no hot files

def test_build_plan_hotspot_phase_first(tmp_path):
    from perflens.optimizer.project_optimizer import build_optimization_plan
    for name in ("hot.c", "cold.c"):
        (tmp_path / name).write_text(f"void {name[:3]}(){{}}")
    graph = ProjectCrawler(root=tmp_path).crawl()
    # Mark hot.c as very hot
    hot_path = tmp_path / "hot.c"
    if hot_path in graph.files:
        graph.files[hot_path].hotspot_pct = 80.0
    plan = build_optimization_plan(graph, backend="rules", min_priority=0.0)
    if plan.phases:
        phase0_names = {sf.path.name for sf in plan.phases[0].files}
        assert "hot.c" in phase0_names

def test_build_plan_respects_min_priority(simple_c_project):
    from perflens.optimizer.project_optimizer import build_optimization_plan
    graph = ProjectCrawler(root=simple_c_project).crawl()
    # With very high min_priority, nothing should qualify
    plan = build_optimization_plan(graph, backend="rules", min_priority=999.0)
    assert plan.total_files == 0


# ══════════════════════════════════════════════════════════════════════════════


def test_project_file_table_disambiguates_same_basenames(tmp_path):
    from rich.console import Console

    first = tmp_path / "src" / "io.c"
    second = tmp_path / "tests" / "io.c"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("int first(void) { return 1; }")
    second.write_text("int second(void) { return 2; }")

    graph = ProjectCrawler(root=tmp_path).crawl()
    console = Console(record=True, width=120)
    graph.print_file_table(console)
    output = console.export_text()

    assert "src/io.c" in output
    assert "tests/io.c" in output


def test_optimization_plan_disambiguates_same_basenames(tmp_path):
    from rich.console import Console

    first = tmp_path / "src" / "io.c"
    second = tmp_path / "tests" / "io.c"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("int first(void) { return 1; }")
    second.write_text("int second(void) { return 2; }")

    graph = ProjectCrawler(root=tmp_path).crawl()
    plan = ProjectOptimizationPlan(
        graph=graph,
        phases=[
            OptimizationPhase(
                phase_id=1,
                files=[graph.files[first], graph.files[second]],
                reason="test",
            )
        ],
    )
    console = Console(record=True, width=120)
    plan.print_plan(console)
    output = console.export_text()

    assert "src/io.c" in output
    assert "tests/io.c" in output


# End-to-end project pipeline (rule engine, no build)
# ══════════════════════════════════════════════════════════════════════════════

def test_project_pipeline_dry_run(example_project):
    if not example_project.exists():
        pytest.skip("example project not present")
    from perflens.pipeline.project_pipeline import ProjectPipeline

    pipeline = ProjectPipeline(
        root=example_project,
        hw_profile="intel_spr",
        backend="rules",
        build=False,           # skip actual compilation in CI
        dry_run=True,
        validate=False,
    )
    result = pipeline.run()
    # Dry run: no files modified, but plan should be built
    assert result.plan is not None
    assert result.error is None

def test_project_pipeline_rules_no_build(example_project):
    if not example_project.exists():
        pytest.skip("example project not present")
    from perflens.pipeline.project_pipeline import ProjectPipeline

    pipeline = ProjectPipeline(
        root=example_project,
        hw_profile="a100",
        backend="rules",
        build=False,
        validate=False,
        apply_patches=False,
    )
    result = pipeline.run()
    assert result.error is None
    # Rule engine should have found and patched at least one file
    assert result.files_optimized >= 1
    assert result.total_patches >= 1

def test_project_pipeline_patch_dir_created(example_project, tmp_path):
    if not example_project.exists():
        pytest.skip("example project not present")
    from perflens.pipeline.project_pipeline import ProjectPipeline

    pipeline = ProjectPipeline(
        root=example_project,
        hw_profile="a100",
        backend="rules",
        build=False,
        validate=False,
    )
    # Monkeypatch patch_dir to tmp_path so we don't pollute example dir
    import perflens.optimizer.project_optimizer as po
    orig_init = po.ProjectOptimizer.__init__

    def patched_init(self, plan, hardware, **kwargs):
        kwargs["patch_dir"] = tmp_path / "patches"
        orig_init(self, plan, hardware, **kwargs)

    po.ProjectOptimizer.__init__ = patched_init
    try:
        result = pipeline.run()
    finally:
        po.ProjectOptimizer.__init__ = orig_init

    assert result.error is None


def test_project_optimizer_writes_patch_for_nested_source(tmp_path, monkeypatch):
    from types import SimpleNamespace

    from perflens.optimizer.models import (
        OptimizationResult,
        Patch,
        TransformKind,
    )
    from perflens.optimizer.project_optimizer import ProjectOptimizer

    source = tmp_path / "src" / "nested" / "p10_fixture.c"
    source.parent.mkdir(parents=True)
    source.write_text("int compute(int x) { return x + 1; }\n")

    sf = SourceFile(source, "c")
    graph = ProjectGraph(root=tmp_path, build_system=BuildSystem.BARE)
    graph.files[source] = sf
    phase = OptimizationPhase(
        phase_id=0,
        files=[sf],
        reason="nested-source regression test",
    )
    plan = ProjectOptimizationPlan(graph=graph, phases=[phase])

    optimized = "int compute(int x) { return x + 2; }\n"
    patch = Patch(
        transform_kind=TransformKind.GENERAL,
        description="test transformation",
        original_snippet="return x + 1;",
        optimized_snippet="return x + 2;",
        start_line=1,
        end_line=1,
        rationale="Exercise nested patch output",
    )
    engine_result = OptimizationResult(
        source=source,
        iteration=1,
        patches=[patch],
        optimized_source=optimized,
    )

    class FakeEngine:
        def __init__(self, **kwargs):
            self.hardware = None

        def optimize(self, **kwargs):
            return [engine_result]

    monkeypatch.setattr(
        "perflens.optimizer.engine.OptimizationEngine", FakeEngine
    )

    optimizer = ProjectOptimizer(
        plan=plan,
        hardware=SimpleNamespace(name="test"),
        patch_dir=tmp_path / "perflens_patches",
        validate_each_phase=False,
    )
    result = optimizer.run()

    patch_path = tmp_path / "perflens_patches" / "src" / "nested" / "p10_fixture.c"
    assert patch_path.exists()
    assert patch_path.read_text() == optimized
    assert sf.optimized_source == optimized
    assert result.files_optimized == 1
    assert result.total_patches == 1



def test_project_optimizer_real_rules_backend_writes_nested_patch(tmp_path):
    """Regression: real rules engine output is materialized at nested paths."""
    from types import SimpleNamespace

    from perflens.optimizer.project_optimizer import ProjectOptimizer
    from perflens.project.models import (
        BuildSystem, ProjectGraph, SourceFile,
        OptimizationPhase, ProjectOptimizationPlan,
    )
    from perflens.scanner.models import Finding, FindingKind, Severity

    root = tmp_path / "project"
    source = root / "src" / "nested" / "p10_fixture.c"
    source.parent.mkdir(parents=True)
    original = """void compute(double *a, double scale, int n) {
    for (int i = 0; i < n; i++) {
        a[i] = a[i] / scale;
    }
}
"""
    source.write_text(original)

    finding = Finding(
        file=source,
        line=3,
        col=0,
        kind=FindingKind.DIVISION_IN_LOOP,
        severity=Severity.MEDIUM,
        message="Division inside loop",
        suggestion="Hoist invariant reciprocal",
    )
    sf = SourceFile(source, "c")
    sf.scanner_findings = [finding]

    graph = ProjectGraph(root=root, build_system=BuildSystem.BARE)
    graph.files[source] = sf
    phase = OptimizationPhase(
        phase_id=0,
        files=[sf],
        reason="P10-01 real-engine nested patch regression",
    )
    plan = ProjectOptimizationPlan(graph=graph, phases=[phase])
    patch_dir = root / "perflens_patches"

    optimizer = ProjectOptimizer(
        plan=plan,
        hardware=SimpleNamespace(name="test"),
        patch_dir=patch_dir,
        validate_each_phase=False,
        backend="rules",
    )
    result = optimizer.run()

    patch_path = patch_dir / "src" / "nested" / "p10_fixture.c"
    assert result.error is None
    assert patch_path.is_file()
    assert "inv_scale" in patch_path.read_text()
    assert sf.optimized_source == patch_path.read_text()
    assert result.files_optimized == 1
    assert result.total_patches >= 1
    assert source.read_text() == original


def test_apply_patches_rejects_invalid_source(tmp_path):
    from perflens.optimizer.project_optimizer import ProjectOptimizer

    root = tmp_path / "project"
    patch_dir = tmp_path / "patches"
    source = root / "src" / "solver.c"
    patch = patch_dir / "src" / "solver.c"

    source.parent.mkdir(parents=True)
    patch.parent.mkdir(parents=True)

    original = "int main(void) { return 0; }\n"
    malformed = "this is not valid C source !!!\n"
    source.write_text(original)
    patch.write_text(malformed)

    sf = SourceFile(path=source, language="c")
    graph = ProjectGraph(
        root=root,
        build_system=BuildSystem.BARE,
        files={source: sf},
    )
    plan = ProjectOptimizationPlan(
        graph=graph,
        phases=[
            OptimizationPhase(
                phase_id=0,
                files=[sf],
                reason="invalid patch regression",
            )
        ],
    )
    optimizer = ProjectOptimizer(
        plan=plan,
        hardware=None,
        patch_dir=patch_dir,
        validate_each_phase=False,
    )

    updated = optimizer.apply_patches(backup=True)

    assert updated == 0
    assert source.read_text() == original
    assert not source.with_suffix(".c.perflens_backup").exists()
    assert patch.read_text() == malformed


def test_apply_patches_accepts_valid_comment_only_patch(tmp_path):
    from perflens.optimizer.project_optimizer import ProjectOptimizer

    root = tmp_path / "project"
    patch_dir = tmp_path / "patches"
    source = root / "src" / "solver.c"
    patch = patch_dir / "src" / "solver.c"

    source.parent.mkdir(parents=True)
    patch.parent.mkdir(parents=True)

    original = "void scale(double *a, int n) { for (int i = 0; i < n; i++) a[i] *= 2.0; }\n"
    patched = "/* validated patch */\n" + original
    source.write_text(original)
    patch.write_text(patched)

    sf = SourceFile(path=source, language="c")
    graph = ProjectGraph(
        root=root,
        build_system=BuildSystem.BARE,
        files={source: sf},
    )
    plan = ProjectOptimizationPlan(
        graph=graph,
        phases=[
            OptimizationPhase(
                phase_id=0,
                files=[sf],
                reason="valid patch regression",
            )
        ],
    )
    optimizer = ProjectOptimizer(
        plan=plan,
        hardware=None,
        patch_dir=patch_dir,
        validate_each_phase=False,
    )

    updated = optimizer.apply_patches(backup=True)

    assert updated == 1
    assert source.read_text() == patched
    assert source.with_suffix(".c.perflens_backup").read_text() == original
    assert patch.read_text() == patched
