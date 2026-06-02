"""Shared pytest fixtures for PerfLens test suite."""

from __future__ import annotations

from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def examples_dir() -> Path:
    return Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="session")
def hw_a100():
    from perflens.hardware.database import HardwareDatabase
    return HardwareDatabase().get("a100")


@pytest.fixture(scope="session")
def hw_intel_spr():
    from perflens.hardware.database import HardwareDatabase
    return HardwareDatabase().get("intel_spr")


@pytest.fixture
def simple_c_file(tmp_path: Path) -> Path:
    src = tmp_path / "simple.c"
    src.write_text("""\
#include <math.h>
void kernel(double *a, double *b, int n) {
    for (int i = 0; i < n; i++) {
        a[i] = sin(b[i]) / b[i];
    }
}
""")
    return src


@pytest.fixture
def simple_py_file(tmp_path: Path) -> Path:
    src = tmp_path / "simple.py"
    src.write_text("""\
import numpy as np
import math

def run():
    result = []
    for i in range(1000):
        result.append(math.sin(i * 0.01))
    return np.array(result)
""")
    return src


@pytest.fixture
def simple_fortran_file(tmp_path: Path) -> Path:
    src = tmp_path / "simple.f90"
    src.write_text("""\
SUBROUTINE jacobi(a, n)
  INTEGER n
  REAL(8) a(n, n)
  INTEGER :: i, j
  DO j = 1, n
    DO i = 1, n
      a(i, j) = SIN(a(i, j)) + COS(a(i, j))
    END DO
  END DO
END SUBROUTINE
""")
    return src
