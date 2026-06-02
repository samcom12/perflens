"""Unit tests for perflens.scanner — all language backends."""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from perflens.scanner.dispatcher import detect_language, scan_file
from perflens.scanner.models import Finding, FindingKind, Severity


# ── detect_language ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("filename,expected", [
    ("solver.c",     "c"),
    ("solver.cpp",   "cpp"),
    ("solver.cxx",   "cpp"),
    ("solver.cc",    "cpp"),
    ("solver.f90",   "fortran"),
    ("solver.f",     "fortran"),
    ("solver.F90",   "fortran"),
    ("solver.py",    "python"),
    ("solver.h",     "c"),
    ("solver.hpp",   "cpp"),
    ("solver.txt",   "unknown"),
])
def test_detect_language(filename: str, expected: str):
    assert detect_language(Path(filename)) == expected


# ── C scanner ────────────────────────────────────────────────────────────────

C_TRANSCENDENTAL = textwrap.dedent("""\
    #include <math.h>
    void kernel(double *a, int n) {
        for (int i = 0; i < n; i++) {
            a[i] = sin(a[i]) + cos(a[i]);
        }
    }
""")

C_IO_IN_LOOP = textwrap.dedent("""\
    #include <stdio.h>
    void dump(double *a, int n) {
        for (int i = 0; i < n; i++) {
            printf("%f\\n", a[i]);
        }
    }
""")

C_MPI_BLOCKING = textwrap.dedent("""\
    #include <mpi.h>
    void exchange(double *buf, int n, int rank) {
        MPI_Send(buf, n, MPI_DOUBLE, rank+1, 0, MPI_COMM_WORLD);
        MPI_Recv(buf, n, MPI_DOUBLE, rank-1, 0, MPI_COMM_WORLD, MPI_STATUS_IGNORE);
    }
""")

C_DIVISION_IN_LOOP = textwrap.dedent("""\
    void normalize(double *a, double norm, int n) {
        for (int i = 0; i < n; i++) {
            a[i] = a[i] / norm;
        }
    }
""")


def _write_tmp(tmp_path: Path, name: str, src: str) -> Path:
    p = tmp_path / name
    p.write_text(src)
    return p


def test_c_transcendental_in_loop(tmp_path):
    f = _write_tmp(tmp_path, "trig.c", C_TRANSCENDENTAL)
    findings = scan_file(f, language="c")
    kinds = {ff.kind for ff in findings}
    assert FindingKind.TRANSCENDENTAL_IN_LOOP in kinds


def test_c_io_in_loop(tmp_path):
    f = _write_tmp(tmp_path, "io.c", C_IO_IN_LOOP)
    findings = scan_file(f, language="c")
    kinds = {ff.kind for ff in findings}
    assert FindingKind.IO_IN_LOOP in kinds


def test_c_mpi_blocking(tmp_path):
    f = _write_tmp(tmp_path, "mpi.c", C_MPI_BLOCKING)
    findings = scan_file(f, language="c")
    kinds = {ff.kind for ff in findings}
    assert FindingKind.MPI_SYNCHRONOUS_HOTSPOT in kinds


def test_c_division_in_loop(tmp_path):
    f = _write_tmp(tmp_path, "div.c", C_DIVISION_IN_LOOP)
    findings = scan_file(f, language="c")
    kinds = {ff.kind for ff in findings}
    assert FindingKind.DIVISION_IN_LOOP in kinds


def test_c_clean_code_no_findings(tmp_path):
    src = textwrap.dedent("""\
        void add(double *a, const double *b, int n) {
            for (int i = 0; i < n; i++) {
                a[i] += b[i];
            }
        }
    """)
    f = _write_tmp(tmp_path, "clean.c", src)
    findings = scan_file(f, language="c")
    # Clean code may still get MISSING_SIMD_PRAGMA (low severity) — that's OK
    critical = [ff for ff in findings if ff.severity == Severity.CRITICAL]
    assert len(critical) == 0


# ── Python scanner ────────────────────────────────────────────────────────────

PY_NUMPY_LOOP = textwrap.dedent("""\
    import numpy as np

    def bad_loop(a):
        result = np.zeros(len(a))
        for i in range(len(a)):
            result[i] = a[i] * 2.0
        return result
""")

PY_SCALAR_MATH_IN_LOOP = textwrap.dedent("""\
    import math

    def compute(xs):
        result = []
        for x in xs:
            result.append(math.sin(x))
        return result
""")

PY_ALLOC_IN_LOOP = textwrap.dedent("""\
    import numpy as np

    def bad_alloc(n, iters):
        for i in range(iters):
            tmp = np.zeros(n)
            tmp[0] = i
        return tmp
""")

PY_GIL = textwrap.dedent("""\
    import threading

    def parallel_work(data):
        threads = [threading.Thread(target=lambda: None) for _ in data]
        for t in threads:
            t.start()
""")

PY_ITERROWS = textwrap.dedent("""\
    import pandas as pd

    def slow_sum(df):
        total = 0
        for idx, row in df.iterrows():
            total += row['value']
        return total
""")


def test_python_numpy_loop(tmp_path):
    f = _write_tmp(tmp_path, "loop.py", PY_NUMPY_LOOP)
    findings = scan_file(f, language="python")
    kinds = {ff.kind for ff in findings}
    assert FindingKind.NUMPY_LOOP in kinds


def test_python_scalar_math_in_loop(tmp_path):
    f = _write_tmp(tmp_path, "math_loop.py", PY_SCALAR_MATH_IN_LOOP)
    findings = scan_file(f, language="python")
    kinds = {ff.kind for ff in findings}
    assert FindingKind.TRANSCENDENTAL_IN_LOOP in kinds


def test_python_alloc_in_loop(tmp_path):
    f = _write_tmp(tmp_path, "alloc.py", PY_ALLOC_IN_LOOP)
    findings = scan_file(f, language="python")
    kinds = {ff.kind for ff in findings}
    assert FindingKind.EXCESSIVE_ALLOCATION in kinds


def test_python_gil(tmp_path):
    f = _write_tmp(tmp_path, "gil.py", PY_GIL)
    findings = scan_file(f, language="python")
    kinds = {ff.kind for ff in findings}
    assert FindingKind.GIL_BOTTLENECK in kinds


def test_python_iterrows(tmp_path):
    f = _write_tmp(tmp_path, "iterrows.py", PY_ITERROWS)
    findings = scan_file(f, language="python")
    kinds = {ff.kind for ff in findings}
    assert FindingKind.NUMPY_LOOP in kinds


def test_python_clean(tmp_path):
    src = textwrap.dedent("""\
        import numpy as np

        def fast(a: np.ndarray) -> np.ndarray:
            return np.sin(a) * 2.0 + np.cos(a)
    """)
    f = _write_tmp(tmp_path, "clean.py", src)
    findings = scan_file(f, language="python")
    high_plus = [ff for ff in findings
                 if ff.severity in (Severity.HIGH, Severity.CRITICAL)]
    assert len(high_plus) == 0


# ── Fortran scanner ────────────────────────────────────────────────────────────

F_TRANSCENDENTAL = textwrap.dedent("""\
    SUBROUTINE trig_loop(a, n)
      IMPLICIT NONE
      INTEGER, INTENT(IN) :: n
      REAL(8), INTENT(INOUT) :: a(n)
      INTEGER :: i
      DO i = 1, n
        a(i) = SIN(a(i)) + COS(a(i))
      END DO
    END SUBROUTINE
""")

F_MPI = textwrap.dedent("""\
    SUBROUTINE exchange(buf, n)
      USE mpi
      IMPLICIT NONE
      INTEGER, INTENT(IN) :: n
      REAL(8), INTENT(INOUT) :: buf(n)
      INTEGER :: ierr
      CALL MPI_SEND(buf, n, MPI_DOUBLE_PRECISION, 1, 0, MPI_COMM_WORLD, ierr)
    END SUBROUTINE
""")

F_MISSING_IMPLICIT_NONE = textwrap.dedent("""\
    SUBROUTINE legacy(a, n)
      INTEGER n
      REAL a(n)
      DO i = 1, n
        a(i) = a(i) * 2.0
      END DO
    END SUBROUTINE
""")


def test_fortran_transcendental(tmp_path):
    f = _write_tmp(tmp_path, "trig.f90", F_TRANSCENDENTAL)
    findings = scan_file(f, language="fortran")
    kinds = {ff.kind for ff in findings}
    assert FindingKind.TRANSCENDENTAL_IN_LOOP in kinds


def test_fortran_mpi_blocking(tmp_path):
    f = _write_tmp(tmp_path, "mpi.f90", F_MPI)
    findings = scan_file(f, language="fortran")
    kinds = {ff.kind for ff in findings}
    assert FindingKind.MPI_SYNCHRONOUS_HOTSPOT in kinds


def test_fortran_missing_implicit_none(tmp_path):
    f = _write_tmp(tmp_path, "legacy.f90", F_MISSING_IMPLICIT_NONE)
    findings = scan_file(f, language="fortran")
    assert len(findings) > 0


# ── Finding model ─────────────────────────────────────────────────────────────

def test_finding_to_dict():
    f = Finding(
        file=Path("foo.c"), line=10, col=4,
        kind=FindingKind.DIVISION_IN_LOOP,
        severity=Severity.MEDIUM,
        message="Division in loop",
        suggestion="Use reciprocal",
    )
    d = f.to_dict()
    assert d["line"] == 10
    assert d["kind"] == "division_in_loop"
    assert d["severity"] == "medium"


def test_finding_location():
    f = Finding(
        file=Path("bar.cpp"), line=42, col=8,
        kind=FindingKind.GENERAL,
        severity=Severity.LOW,
        message="x", suggestion="y",
    )
    assert f.location == "bar.cpp:42:8"


def test_scan_file_not_found():
    with pytest.raises(FileNotFoundError):
        scan_file(Path("/nonexistent/solver.c"))


def test_scan_unsupported_language(tmp_path):
    f = tmp_path / "solver.rs"
    f.write_text("fn main() {}")
    with pytest.raises(ValueError, match="Unsupported language"):
        scan_file(f, language="rust")
