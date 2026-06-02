"""
Integration tests — exercise the full scan→profile→validate pipeline
on the bundled example files.  The LLM optimizer step is SKIPPED
(requires real API key and network) unless PERFLENS_RUN_LLM_TESTS=1.
"""

from __future__ import annotations

import os
import textwrap
from pathlib import Path

import pytest

EXAMPLES = Path(__file__).parent.parent.parent / "examples"
RUN_LLM = os.environ.get("PERFLENS_RUN_LLM_TESTS", "0") == "1"


# ── Scanner integration ───────────────────────────────────────────────────────

def test_scan_c_example():
    src = EXAMPLES / "c" / "stencil.c"
    if not src.exists():
        pytest.skip("Example file not present")
    from perflens.scanner.dispatcher import scan_file
    findings = scan_file(src, language="c")
    assert isinstance(findings, list)
    # stencil.c has known transcendental / tiling patterns
    kinds = {f.kind.value for f in findings}
    assert len(kinds) > 0


def test_scan_python_example():
    src = EXAMPLES / "python" / "heat_solver.py"
    if not src.exists():
        pytest.skip("Example file not present")
    from perflens.scanner.dispatcher import scan_file
    findings = scan_file(src, language="python")
    assert isinstance(findings, list)


def test_scan_fortran_example():
    src = EXAMPLES / "fortran" / "jacobi.f90"
    if not src.exists():
        pytest.skip("Example file not present")
    from perflens.scanner.dispatcher import scan_file
    findings = scan_file(src, language="fortran")
    assert isinstance(findings, list)


# ── Validator integration (Python, no compile needed) ─────────────────────────

def test_validate_identical_python(tmp_path):
    src = textwrap.dedent("""\
        import numpy as np
        def run():
            return np.arange(50, dtype=float)
    """)
    orig    = tmp_path / "orig.py"
    patched = tmp_path / "patched.py"
    orig.write_text(src)
    patched.write_text(src)

    from perflens.validator.checker import PatchValidator
    report = PatchValidator().validate(orig, patched)
    assert report.passed


def test_validate_broken_patch_fails(tmp_path):
    orig = tmp_path / "orig.py"
    orig.write_text("def run(): return 1\n")
    bad = tmp_path / "bad.py"
    bad.write_text("def run( return 1\n")  # syntax error
    from perflens.validator.checker import PatchValidator
    report = PatchValidator().validate(orig, bad)
    assert not report.passed


# ── Hardware detector integration ─────────────────────────────────────────────

def test_detect_hardware_returns_profile():
    from perflens.hardware.detector import detect_hardware
    hw = detect_hardware()
    assert hw is not None
    assert hw.total_cores > 0
    assert hw.memory_bandwidth_gbs > 0


# ── Dashboard API integration ─────────────────────────────────────────────────

def test_dashboard_api_create_and_list_run(tmp_path):
    """Spin up the FastAPI app in-process and exercise the REST API."""
    from fastapi.testclient import TestClient
    from perflens.dashboard.app import create_app

    db = tmp_path / "test.db"
    app = create_app(db_path=db)
    client = TestClient(app)

    # POST a new run
    payload = {
        "label": "test_run",
        "source_file": "solver.c",
        "hw_profile": "a100",
        "iteration": 1,
        "runtime_ms": 4200.5,
        "speedup": 2.3,
        "hotspots": [
            {"function": "compute_flux", "cpu_pct": 45.0, "cpu_ms": 1890.0},
            {"function": "extrapolate",  "cpu_pct": 22.0, "cpu_ms": 924.0},
        ],
    }
    resp = client.post("/api/runs", json=payload)
    assert resp.status_code == 201
    run_id = resp.json()["id"]
    assert isinstance(run_id, int)

    # GET list
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    runs = resp.json()
    assert any(r["id"] == run_id for r in runs)

    # GET single
    resp = client.get(f"/api/runs/{run_id}")
    assert resp.status_code == 200
    detail = resp.json()
    assert detail["label"] == "test_run"
    assert len(detail["hotspots"]) == 2

    # GET missing run
    resp = client.get("/api/runs/99999")
    assert resp.status_code == 404


def test_dashboard_charts_return_plotly_json(tmp_path):
    from fastapi.testclient import TestClient
    from perflens.dashboard.app import create_app

    db = tmp_path / "charts.db"
    app = create_app(db_path=db)
    client = TestClient(app)

    # Seed some data
    for i in range(3):
        client.post("/api/runs", json={
            "label": f"run_{i}", "iteration": i,
            "runtime_ms": 5000.0 / (i + 1), "speedup": float(i + 1),
        })

    for endpoint in ["/api/chart/timeline", "/api/chart/speedup",
                     "/api/chart/roofline", "/api/chart/hotspots"]:
        resp = client.get(endpoint)
        assert resp.status_code == 200
        data = resp.json()
        assert "data" in data          # Plotly JSON must have "data" key
        assert "layout" in data


def test_dashboard_index_returns_html(tmp_path):
    from fastapi.testclient import TestClient
    from perflens.dashboard.app import create_app

    app = create_app(db_path=tmp_path / "idx.db")
    client = TestClient(app)
    resp = client.get("/")
    assert resp.status_code == 200
    assert "PerfLens" in resp.text
    assert "plotly" in resp.text.lower()


# ── LLM optimizer (skipped by default) ───────────────────────────────────────

@pytest.mark.skipif(not RUN_LLM, reason="Set PERFLENS_RUN_LLM_TESTS=1 to run LLM tests")
def test_llm_optimize_c_stencil(tmp_path):
    src = EXAMPLES / "c" / "stencil.c"
    if not src.exists():
        pytest.skip("Example stencil.c not present")
    import shutil
    work = tmp_path / "stencil.c"
    shutil.copy(src, work)

    from perflens.optimizer.engine import OptimizationEngine
    engine = OptimizationEngine(hw_profile="a100", max_iterations=1)
    results = engine.optimize(work)
    assert len(results) >= 1
    assert results[0].success
    assert results[0].optimized_source is not None
