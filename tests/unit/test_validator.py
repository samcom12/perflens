"""Unit tests for perflens.validator."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from perflens.validator.checker import PatchValidator
from perflens.validator.models import CheckStatus, ValidationReport


def _write(tmp_path: Path, name: str, text: str) -> Path:
    p = tmp_path / name
    p.write_text(text)
    return p


# ── Python compile check ──────────────────────────────────────────────────────

GOOD_PY = textwrap.dedent("""\
    import numpy as np

    def run():
        a = np.arange(1000, dtype=float)
        return np.sin(a) * 2.0
""")

BAD_PY_SYNTAX = textwrap.dedent("""\
    def run(
        return 42
""")


def test_python_compile_pass(tmp_path):
    orig = _write(tmp_path, "orig.py", GOOD_PY)
    patched = _write(tmp_path, "patched.py", GOOD_PY)
    v = PatchValidator()
    report = v.validate(orig, patched)
    compile_check = next(c for c in report.checks if "Compile" in c.name and "patched" in c.name.lower())
    assert compile_check.status == CheckStatus.PASS


def test_python_compile_fail(tmp_path):
    orig = _write(tmp_path, "orig.py", GOOD_PY)
    bad = _write(tmp_path, "bad.py", BAD_PY_SYNTAX)
    v = PatchValidator()
    report = v.validate(orig, bad)
    compile_check = next(c for c in report.checks if "patched" in c.name.lower())
    assert compile_check.status == CheckStatus.FAIL
    assert not report.passed


# ── Numerical diff ────────────────────────────────────────────────────────────

ORIG_PY_WITH_RUN = textwrap.dedent("""\
    import numpy as np

    def run():
        return np.arange(100, dtype=float)
""")

CLOSE_PY = textwrap.dedent("""\
    import numpy as np

    def run():
        # numerically identical
        return np.arange(100, dtype=float) * 1.0
""")

WRONG_PY = textwrap.dedent("""\
    import numpy as np

    def run():
        # wrong — adds 100 to every element
        return np.arange(100, dtype=float) + 100.0
""")


def test_numerical_diff_pass(tmp_path):
    orig    = _write(tmp_path, "orig.py", ORIG_PY_WITH_RUN)
    patched = _write(tmp_path, "close.py", CLOSE_PY)
    v = PatchValidator(tolerance=1e-9)
    report = v.validate(orig, patched)
    diff_check = next((c for c in report.checks if "numerical" in c.name.lower()), None)
    if diff_check and diff_check.status != CheckStatus.SKIP:
        assert diff_check.status == CheckStatus.PASS
        assert report.numerical_diff_max is not None
        assert report.numerical_diff_max < 1e-9


def test_numerical_diff_fail(tmp_path):
    orig    = _write(tmp_path, "orig.py", ORIG_PY_WITH_RUN)
    patched = _write(tmp_path, "wrong.py", WRONG_PY)
    v = PatchValidator(tolerance=1e-6)
    report = v.validate(orig, patched)
    diff_check = next((c for c in report.checks if "numerical" in c.name.lower()), None)
    if diff_check and diff_check.status != CheckStatus.SKIP:
        assert diff_check.status == CheckStatus.FAIL
        assert not report.passed


# ── Diff sanity check ─────────────────────────────────────────────────────────

SMALL_CHANGE = textwrap.dedent("""\
    import numpy as np

    def run():
        # added pragma comment
        a = np.arange(100, dtype=float)
        return np.sin(a)  # vectorised
""")

COMPLETE_REWRITE = "x = 1\n" * 200   # totally different


def test_diff_sanity_small_change(tmp_path):
    orig    = _write(tmp_path, "orig.py", GOOD_PY)
    patched = _write(tmp_path, "small.py", SMALL_CHANGE)
    v = PatchValidator()
    report = v.validate(orig, patched)
    sanity = next(c for c in report.checks if "sanity" in c.name.lower())
    assert sanity.status in (CheckStatus.PASS, CheckStatus.WARNING)


def test_diff_sanity_large_rewrite(tmp_path):
    orig    = _write(tmp_path, "orig.py", GOOD_PY)
    patched = _write(tmp_path, "rewrite.py", COMPLETE_REWRITE)
    v = PatchValidator()
    report = v.validate(orig, patched)
    sanity = next(c for c in report.checks if "sanity" in c.name.lower())
    # Large rewrites should be flagged as WARNING
    assert sanity.status == CheckStatus.WARNING


# ── C compile check ───────────────────────────────────────────────────────────

GOOD_C = textwrap.dedent("""\
    #include <math.h>
    void add(double *a, const double *b, int n) {
        for (int i = 0; i < n; i++) a[i] += b[i];
    }
""")

BAD_C = textwrap.dedent("""\
    void add(double *a, const double *b, int n) {
        SYNTAX ERROR HERE
    }
""")


def test_c_compile_pass(tmp_path):
    orig    = _write(tmp_path, "orig.c", GOOD_C)
    patched = _write(tmp_path, "patched.c", GOOD_C)
    v = PatchValidator()
    report = v.validate(orig, patched)
    compile_check = next(
        (c for c in report.checks if "patched" in c.name.lower()), None
    )
    if compile_check and compile_check.status != CheckStatus.SKIP:
        assert compile_check.status in (CheckStatus.PASS, CheckStatus.WARNING)


def test_c_compile_fail(tmp_path):
    orig    = _write(tmp_path, "orig.c", GOOD_C)
    patched = _write(tmp_path, "bad.c", BAD_C)
    v = PatchValidator()
    report = v.validate(orig, patched)
    compile_check = next(
        (c for c in report.checks if "patched" in c.name.lower()), None
    )
    if compile_check and compile_check.status != CheckStatus.SKIP:
        assert compile_check.status == CheckStatus.FAIL
        assert not report.passed


# ── ValidationReport.passed ───────────────────────────────────────────────────

def test_report_passes_when_all_pass():
    from perflens.validator.models import CheckResult
    r = ValidationReport(original=Path("a.py"), patched=Path("b.py"))
    r.checks = [
        CheckResult("Compile original", CheckStatus.PASS),
        CheckResult("Compile patched",  CheckStatus.PASS),
        CheckResult("Test suite",       CheckStatus.SKIP),
        CheckResult("Numerical diff",   CheckStatus.PASS),
        CheckResult("Diff sanity",      CheckStatus.PASS),
    ]
    assert r.passed is True


def test_report_fails_when_any_fail():
    from perflens.validator.models import CheckResult
    r = ValidationReport(original=Path("a.py"), patched=Path("b.py"))
    r.checks = [
        CheckResult("Compile patched", CheckStatus.FAIL, "syntax error"),
        CheckResult("Test suite",      CheckStatus.SKIP),
    ]
    assert r.passed is False
