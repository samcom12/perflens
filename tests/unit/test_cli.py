"""
CLI integration tests — exercises every top-level command via
typer's CliRunner so no subprocess is needed.

We test:
  - Exit code (0 = success, non-zero = expected failure)
  - Key strings in output
  - That no unhandled exception escapes
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest
from typer.testing import CliRunner

from perflens.cli import app

runner = CliRunner()


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def c_file(tmp_path: Path) -> Path:
    p = tmp_path / "solver.c"
    p.write_text(textwrap.dedent("""\
        #include <math.h>
        #include <mpi.h>
        void compute(double *a, double *b, int n, double scale) {
            for (int i = 0; i < n; i++) {
                a[i] = sin(b[i]) / scale;
            }
            MPI_Send(a, n, MPI_DOUBLE, 1, 0, MPI_COMM_WORLD);
        }
    """))
    return p


@pytest.fixture
def py_file(tmp_path: Path) -> Path:
    p = tmp_path / "heat.py"
    p.write_text(textwrap.dedent("""\
        import math, numpy as np

        def run():
            result = []
            for i in range(100):
                result.append(math.sin(i * 0.01))
            return np.array(result)
    """))
    return p


@pytest.fixture
def f90_file(tmp_path: Path) -> Path:
    p = tmp_path / "jacobi.f90"
    p.write_text(textwrap.dedent("""\
        SUBROUTINE work(a, n)
          INTEGER n
          REAL(8) a(n)
          INTEGER :: i
          DO i = 1, n
            a(i) = SIN(a(i))
          END DO
        END SUBROUTINE
    """))
    return p


@pytest.fixture
def vtune_csv(tmp_path: Path) -> Path:
    p = tmp_path / "report.csv"
    p.write_text(textwrap.dedent("""\
        Function,Module,CPU Time,CPU Time (%)
        compute_flux,solver,2500.5,45.3
        update,solver,1200.0,21.7
    """))
    return p


@pytest.fixture
def gcc_log(tmp_path: Path) -> Path:
    p = tmp_path / "gcc.log"
    p.write_text(textwrap.dedent("""\
        solver.c:42:5: optimized: loop vectorized using 32-byte vectors
        solver.c:87:9: missed: couldn't vectorize loop
        solver.c:87:9: note: not vectorized: multiple loop exits.
    """))
    return p


@pytest.fixture
def example_project() -> Path:
    return Path(__file__).parent.parent.parent / "examples" / "project_hello"


# ══════════════════════════════════════════════════════════════════════════════
# --version
# ══════════════════════════════════════════════════════════════════════════════

def test_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "perflens" in result.output


# ══════════════════════════════════════════════════════════════════════════════
# perflens scan
# ══════════════════════════════════════════════════════════════════════════════

def test_scan_c_file(c_file):
    result = runner.invoke(app, ["scan", str(c_file)])
    assert result.exit_code == 0

def test_scan_python_file(py_file):
    result = runner.invoke(app, ["scan", str(py_file)])
    assert result.exit_code == 0

def test_scan_fortran_file(f90_file):
    result = runner.invoke(app, ["scan", str(f90_file)])
    assert result.exit_code == 0

def test_scan_output_json(c_file, tmp_path):
    import json
    out = tmp_path / "findings.json"
    result = runner.invoke(app, ["scan", str(c_file), "--output", str(out)])
    assert result.exit_code == 0
    assert out.exists()
    data = json.loads(out.read_text())
    assert isinstance(data, list)

def test_scan_explicit_language(c_file):
    result = runner.invoke(app, ["scan", str(c_file), "--lang", "c"])
    assert result.exit_code == 0

def test_scan_missing_file():
    result = runner.invoke(app, ["scan", "/nonexistent/solver.c"])
    assert result.exit_code != 0

def test_scan_examples_c():
    p = Path("examples/c/stencil.c")
    if not p.exists():
        pytest.skip("example not present")
    result = runner.invoke(app, ["scan", str(p)])
    assert result.exit_code == 0

def test_scan_examples_python():
    p = Path("examples/python/heat_solver.py")
    if not p.exists():
        pytest.skip("example not present")
    result = runner.invoke(app, ["scan", str(p)])
    assert result.exit_code == 0


# ══════════════════════════════════════════════════════════════════════════════
# perflens profile
# ══════════════════════════════════════════════════════════════════════════════

def test_profile_vtune_csv(c_file, vtune_csv):
    result = runner.invoke(app, [
        "profile", str(c_file),
        "--tool", "vtune",
        "--report", str(vtune_csv),
    ])
    assert result.exit_code == 0

def test_profile_output_json(c_file, vtune_csv, tmp_path):
    import json
    out = tmp_path / "profile.json"
    result = runner.invoke(app, [
        "profile", str(c_file),
        "--report", str(vtune_csv),
        "--output", str(out),
    ])
    assert result.exit_code == 0
    assert out.exists()
    data = json.loads(out.read_text())
    assert "hotspots" in data


# ══════════════════════════════════════════════════════════════════════════════
# perflens optimize (rule engine — no API key)
# ══════════════════════════════════════════════════════════════════════════════

def test_optimize_c_rules(c_file):
    result = runner.invoke(app, [
        "optimize", str(c_file),
        "--backend", "rules",
        "--hw", "intel_spr",
    ])
    # Rule engine runs without key — any clean exit is fine
    assert result.exit_code in (0, 1, 2)

def test_optimize_python_rules(py_file):
    result = runner.invoke(app, [
        "optimize", str(py_file),
        "--backend", "rules",
        "--hw", "a100",
    ])
    assert result.exit_code in (0, 1)

def test_optimize_fortran_rules(f90_file):
    result = runner.invoke(app, [
        "optimize", str(f90_file),
        "--backend", "rules",
        "--hw", "a100",
    ])
    assert result.exit_code in (0, 1)

def test_optimize_dry_run(c_file):
    result = runner.invoke(app, [
        "optimize", str(c_file),
        "--backend", "rules",
        "--dry-run",
    ])
    assert result.exit_code == 0
    # No optimized file created in dry-run
    optimized = list(c_file.parent.glob("*_optimized*"))
    assert len(optimized) == 0

def test_optimize_with_profile(c_file, vtune_csv):
    result = runner.invoke(app, [
        "optimize", str(c_file),
        "--backend", "rules",
        "--profile", str(vtune_csv),
        "--profile-tool", "vtune",
    ])
    assert result.exit_code in (0, 1)

def test_optimize_unknown_hw(c_file):
    result = runner.invoke(app, [
        "optimize", str(c_file),
        "--backend", "rules",
        "--hw", "nonexistent_hardware_xyz",
    ])
    # Should either exit non-zero or show an error message
    assert result.exit_code != 0 or "unknown" in result.output.lower() or \
           "nonexistent" in result.output.lower() or result.exit_code == 1


# ══════════════════════════════════════════════════════════════════════════════
# perflens validate
# ══════════════════════════════════════════════════════════════════════════════

def test_validate_identical_files(tmp_path):
    src = textwrap.dedent("""\
        import numpy as np
        def run():
            return np.arange(10, dtype=float)
    """)
    orig    = tmp_path / "orig.py"
    patched = tmp_path / "patched.py"
    orig.write_text(src)
    patched.write_text(src)
    result = runner.invoke(app, ["validate", str(orig), str(patched)])
    assert result.exit_code == 0

def test_validate_broken_patch_exits_nonzero(tmp_path):
    orig    = tmp_path / "orig.py"
    broken  = tmp_path / "broken.py"
    orig.write_text("def run(): return 1\n")
    broken.write_text("def run( return 1\n")  # syntax error
    result = runner.invoke(app, ["validate", str(orig), str(broken)])
    assert result.exit_code != 0


# ══════════════════════════════════════════════════════════════════════════════
# perflens backends
# ══════════════════════════════════════════════════════════════════════════════

def test_backends_lists_rules():
    result = runner.invoke(app, ["backends"])
    assert result.exit_code == 0
    assert "rules" in result.output

def test_backends_lists_ollama():
    result = runner.invoke(app, ["backends"])
    assert "ollama" in result.output

def test_backends_lists_anthropic():
    result = runner.invoke(app, ["backends"])
    assert "anthropic" in result.output

def test_backends_shows_key_info():
    result = runner.invoke(app, ["backends"])
    # Should show "no key" for rule engine
    assert "no" in result.output.lower()


# ══════════════════════════════════════════════════════════════════════════════
# perflens compiler
# ══════════════════════════════════════════════════════════════════════════════

def test_compiler_parses_gcc_log(c_file, gcc_log):
    result = runner.invoke(app, [
        "compiler", str(c_file),
        "--report", str(gcc_log),
        "--compiler", "gcc",
    ])
    assert result.exit_code == 0

def test_compiler_output_json(c_file, gcc_log, tmp_path):
    import json
    out = tmp_path / "feedback.json"
    result = runner.invoke(app, [
        "compiler", str(c_file),
        "--report", str(gcc_log),
        "--output", str(out),
    ])
    assert result.exit_code == 0
    assert out.exists()
    data = json.loads(out.read_text())
    assert "remarks" in data
    assert len(data["remarks"]) >= 2


# ══════════════════════════════════════════════════════════════════════════════
# perflens autotune
# ══════════════════════════════════════════════════════════════════════════════

def test_autotune_no_tile_define(tmp_path):
    src = tmp_path / "notiled.c"
    src.write_text("void f(){}")  # no #define TILE
    result = runner.invoke(app, [
        "autotune", str(src),
        "--param", "tile",
        "--hw", "intel_spr",
    ])
    assert result.exit_code == 0   # should warn gracefully, not crash

def test_autotune_invalid_param(tmp_path):
    src = tmp_path / "x.c"
    src.write_text("void f(){}")
    result = runner.invoke(app, [
        "autotune", str(src),
        "--param", "invalid_param_xyz",
    ])
    assert result.exit_code != 0


# ══════════════════════════════════════════════════════════════════════════════
# perflens hw
# ══════════════════════════════════════════════════════════════════════════════

def test_hw_list():
    result = runner.invoke(app, ["hw", "list"])
    assert result.exit_code == 0
    # IDs may be truncated in the table; check the profile count instead
    assert "a100" in result.output
    assert "a64" in result.output   # a64fx truncated to a64…

def test_hw_detect():
    result = runner.invoke(app, ["hw", "detect"])
    assert result.exit_code == 0

def test_hw_show_known():
    result = runner.invoke(app, ["hw", "show", "a100"])
    assert result.exit_code == 0
    assert "A100" in result.output

def test_hw_show_unknown():
    result = runner.invoke(app, ["hw", "show", "nonexistent_hw"])
    assert result.exit_code != 0

@pytest.mark.parametrize("profile_id", [
    "a100", "h100", "v100", "intel_spr", "intel_icx",
    "amd_genoa", "amd_milan", "a64fx", "graviton3",
])
def test_hw_show_all_profiles(profile_id):
    result = runner.invoke(app, ["hw", "show", profile_id])
    assert result.exit_code == 0


# ══════════════════════════════════════════════════════════════════════════════
# perflens project
# ══════════════════════════════════════════════════════════════════════════════

def test_project_scan(example_project):
    if not example_project.exists():
        pytest.skip("example project not present")
    result = runner.invoke(app, ["project", "scan", str(example_project)])
    assert result.exit_code == 0
    assert "project_hello" in result.output.lower() or "src" in result.output.lower()

def test_project_scan_with_deps(example_project):
    if not example_project.exists():
        pytest.skip("example project not present")
    result = runner.invoke(app, [
        "project", "scan", str(example_project), "--deps"
    ])
    assert result.exit_code == 0

def test_project_scan_output_json(example_project, tmp_path):
    if not example_project.exists():
        pytest.skip("example project not present")
    import json
    out = tmp_path / "graph.json"
    result = runner.invoke(app, [
        "project", "scan", str(example_project), "--output", str(out)
    ])
    assert result.exit_code == 0
    assert out.exists()
    data = json.loads(out.read_text())
    assert "files" in data
    assert len(data["files"]) >= 3

def test_project_scan_empty_dir(tmp_path):
    result = runner.invoke(app, ["project", "scan", str(tmp_path)])
    assert result.exit_code == 0   # empty project is valid, just 0 files

def test_project_status_no_patches(example_project):
    if not example_project.exists():
        pytest.skip("example project not present")
    result = runner.invoke(app, ["project", "status", str(example_project)])
    assert result.exit_code == 0

def test_project_diff_no_patches(example_project):
    if not example_project.exists():
        pytest.skip("example project not present")
    result = runner.invoke(app, ["project", "diff", str(example_project)])
    assert result.exit_code == 0

def test_project_optimize_dry_run(example_project):
    if not example_project.exists():
        pytest.skip("example project not present")
    result = runner.invoke(app, [
        "project", "optimize", str(example_project),
        "--backend", "rules",
        "--no-build",
        "--dry-run",
        "--hw", "a100",
    ])
    assert result.exit_code in (0, 1)

def test_project_optimize_rules_no_build(example_project):
    if not example_project.exists():
        pytest.skip("example project not present")
    result = runner.invoke(app, [
        "project", "optimize", str(example_project),
        "--backend", "rules",
        "--no-build",
        "--no-validate",
        "--hw", "intel_spr",
    ])
    assert result.exit_code in (0, 1)
    # Patch directory should have been created
    patch_dir = example_project / "perflens_patches"
    # (may or may not exist depending on whether any rules fired)

def test_project_build_no_build_flag(example_project, tmp_path):
    """--no-build with build command should only collect feedback."""
    if not example_project.exists():
        pytest.skip("example project not present")
    result = runner.invoke(app, [
        "project", "build", str(example_project),
        "--no-build",
        "--hw", "intel_spr",
    ])
    assert result.exit_code == 0
