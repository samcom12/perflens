# Perflens: Python 3.12 and Clang Environment Setup

**Status:** Completed for Clang-based SIMD analysis
**Date:** 30 October 2026
**Platform:** HPC cluster
**Scope:** User-local Python environment; no system-wide changes

## 1. Initial problem

The cluster's existing Python 3.12 installation was missing the `_ctypes` extension.

This prevented the Python Clang bindings (`clang.cindex`) from importing successfully. Consequently, Perflens could not use Clang's AST functionality for SIMD loop analysis.

The original test run showed four failures in `TestOpenMPSIMDRule`, caused by this environment limitation.

## 2. What we changed

All installations were kept inside the user's home directory.

### A. Built and installed libffi

- Downloaded and built libffi 3.4.6.
- Installed it under:

  `$HOME/local/libffi-3.4.6`

- Verified its headers, shared library, and pkg-config metadata.

### B. Built a custom Python 3.12

- Used Python 3.12.0 source.
- Configured the build to use the locally installed libffi.
- Enabled shared-library support.
- Successfully built and installed Python under:

  `$HOME/local/python-3.12.0-ctypes`

- Confirmed that `_ctypes` was built and importable.

### C. Created a separate project virtual environment

Created:

`$HOME/perflens_work/venvs/perflens-py312-ctypes`

Installed Perflens development dependencies using:

`pip install -e ".[dev]"`

Verified successful imports of:
- Python `ctypes`
- Python `_ctypes`
- `clang.cindex`

The repository's existing `.venv` was left untouched.

## 3. SIMD validation

Ran the OpenMP SIMD rule test class:

```bash
python -m pytest -o addopts='' -p no:pytest_cov \
  tests/unit/test_backends_and_rules.py::TestOpenMPSIMDRule -v
```

**Result: 8 passed.**

This includes all four tests that had previously failed:

- `test_applies_simd_hw`
- `test_inserts_simd_pragma`
- `test_only_inserts_before_innermost_nested_loop`
- `test_triple_nested_loop_only_gets_innermost_pragma`

This confirms that the custom Python environment can load Clang bindings and perform the AST-based SIMD analysis required by these tests.

## 4. Full test-suite result

Ran the full suite with the coverage plugin disabled:

```bash
python -m pytest -o addopts='' -p no:pytest_cov -v
```

**Result:**
- 345 passed
- 3 failed
- 5 skipped

The three remaining failures were:

- `test_dashboard_api_create_and_list_run`
- `test_dashboard_charts_return_plotly_json`
- `test_dashboard_index_returns_html`

All three were blocked by the missing Python `_sqlite3` extension.

The cluster had a SQLite runtime library, but no development header was found. The custom Python build therefore did not include `_sqlite3`.

## 5. Deferred work: SQLite

SQLite is not required for the Clang bindings or the SIMD tests validated above.

It is only needed to restore functionality for the SQLite-dependent dashboard tests and normal coverage-enabled test runs in this Python environment.

**Decision:** Defer SQLite installation and Python rebuilding until dashboard testing or full-suite validation requires it.

## 6. Environment safety

The work was performed locally under `$HOME/local` and `$HOME/perflens_work`.

- No system Python installation was modified.
- No system libraries were replaced.
- No cluster-wide configuration was changed.
- The existing project `.venv` was preserved.
- Existing repository changes and untracked files were preserved.

## 7. Current outcome

**The original environment blocker is resolved.**

The custom Python 3.12 environment supports `_ctypes`, the Python Clang bindings, and the Perflens OpenMP SIMD rule tests.

SQLite support remains a separate, optional environment improvement for dashboard and coverage testing.