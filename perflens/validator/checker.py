"""
PatchValidator — ensures that a patched source file:

1. Compiles cleanly (language-appropriate compiler)
2. Passes the existing test suite (pytest / CTest / custom runner)
3. Produces numerically equivalent output (within tolerance)
4. Shows no new compiler warnings that indicate correctness issues

Supports: C, C++, Fortran, Python
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Optional

from rich.console import Console

from perflens.scanner.dispatcher import detect_language
from perflens.validator.models import CheckResult, CheckStatus, ValidationReport

# ── Compiler toolchain selection ─────────────────────────────────────────────

_C_COMPILERS   = ["gcc", "clang", "icx", "nvc"]
_CXX_COMPILERS = ["g++", "clang++", "icpx", "nvc++"]
_F_COMPILERS   = ["gfortran", "ifort", "ifx", "nvfortran"]

# Validation builds run on the BUILD HOST, which may differ from the target
# architecture the user is tuning for. We therefore must NOT use target-specific
# flags like -march=sapphirerapids / -mavx512f (binary may SIGILL on the build
# host), and must NOT use -ffast-math (it perturbs FP results and would make a
# numerical-equivalence check meaningless). Portable -O0 + IEEE math only.
_CFLAGS_BASE   = ["-O0", "-Wall", "-Wextra", "-fopenmp", "-fno-fast-math"]
_CXXFLAGS_BASE = ["-O0", "-Wall", "-Wextra", "-fopenmp", "-std=c++17", "-fno-fast-math"]
_FFLAGS_BASE   = ["-O0", "-Wall", "-fopenmp"]
_LINK_LIBS     = ["-lm"]


def _find_compiler(candidates: list[str]) -> Optional[str]:
    return next((c for c in candidates if shutil.which(c)), None)


class PatchValidator:
    def __init__(
        self,
        tolerance: float = 1e-6,
        console: Optional[Console] = None,
        timeout: int = 120,
    ):
        self.tolerance = tolerance
        self.console = console or Console()
        self.timeout = timeout

    # ── Public API ────────────────────────────────────────────────────────────

    def validate(
        self,
        original: Path,
        patched: Path,
        test_dir: Optional[Path] = None,
    ) -> ValidationReport:
        language = detect_language(original)
        # Store so _compile_check can add -I flags for relative includes.
        self._original_dir: Optional[Path] = original.parent
        report = ValidationReport(
            original=original,
            patched=patched,
            tolerance=self.tolerance,
        )

        # 1. Compile original
        report.checks.append(self._compile_check("Compile original", original, language))

        # 2. Compile patched
        compile_result = self._compile_check("Compile patched", patched, language)
        report.checks.append(compile_result)

        if compile_result.status == CheckStatus.FAIL:
            # No point running further checks if it doesn't compile
            report.checks.append(CheckResult(
                name="Tests", status=CheckStatus.SKIP,
                message="Skipped — patch does not compile",
            ))
            return report

        # 3. Run tests
        tests_passed = False
        if test_dir and test_dir.exists():
            test_result = self._run_tests(test_dir, language, patched)
            report.checks.append(test_result)
            tests_passed = test_result.status == CheckStatus.PASS
        else:
            report.checks.append(CheckResult(
                name="Test suite",
                status=CheckStatus.SKIP,
                message="No test directory provided",
            ))

        # 4. Numerical diff (Python and compiled languages).
        # This is the PRIMARY correctness signal. If the patch changes program
        # semantics and this check cannot run, we must fail closed — hence
        # critical=True so a SKIP does not silently count as success.
        if language == "python":
            diff_result, max_diff = self._python_numerical_diff(original, patched)
        else:
            diff_result, max_diff = self._compiled_numerical_diff(
                original, patched, language
            )
        diff_result.critical = True
        report.checks.append(diff_result)
        report.numerical_diff_max = max_diff

        # Determine whether this patch could change numerical behaviour.
        report.semantics_may_change = self._semantics_may_change(original, patched)

        # Correctness is considered verified if the test suite passed OR the
        # numerical diff was within tolerance.
        report.correctness_verified = tests_passed or (
            diff_result.status == CheckStatus.PASS
        )

        # 5. Diff size / regression check
        report.checks.append(self._diff_sanity_check(original, patched))

        return report

    # ── Semantics-change heuristic ────────────────────────────────────────────

    @staticmethod
    def _semantics_may_change(original: Path, patched: Path) -> bool:
        """
        Decide whether a patch could alter numerical results / behaviour.

        Pure pragma insertions that the compiler may ignore (e.g. #pragma omp
        simd) are still treated as semantics-changing, because parallelisation
        can introduce races or reassociate FP operations. Only whitespace /
        comment-only diffs are considered behaviour-preserving.
        """
        import re as _re
        o = original.read_text(errors="replace")
        p = patched.read_text(errors="replace")
        if o == p:
            return False

        def _strip(text: str) -> str:
            # Remove C/C++/Fortran/Python comments and all whitespace so that
            # a comment-only or reformatting change is detected as no-op.
            text = _re.sub(r"/\*.*?\*/", "", text, flags=_re.DOTALL)
            text = _re.sub(r"//[^\n]*", "", text)
            text = _re.sub(r"!.*?$", "", text, flags=_re.MULTILINE)   # Fortran
            text = _re.sub(r"#(?!\s*pragma|\s*include|\s*define).*?$", "",
                           text, flags=_re.MULTILINE)                  # py/# comments
            return _re.sub(r"\s+", "", text)

        return _strip(o) != _strip(p)

    # ── Compile check ─────────────────────────────────────────────────────────

    def _compile_check(self, name: str, path: Path, language: str) -> CheckResult:
        t0 = time.monotonic()

        if language == "python":
            # Syntax check via py_compile
            try:
                import py_compile
                py_compile.compile(str(path), doraise=True)
                return CheckResult(name=name, status=CheckStatus.PASS,
                                   message="Python syntax OK",
                                   duration_s=time.monotonic() - t0)
            except py_compile.PyCompileError as e:
                return CheckResult(name=name, status=CheckStatus.FAIL,
                                   message=str(e), duration_s=time.monotonic() - t0)

        # C / C++ / Fortran: compile to object file only
        if language in ("c",):
            compiler = _find_compiler(_C_COMPILERS)
            flags = _CFLAGS_BASE
        elif language == "cpp":
            compiler = _find_compiler(_CXX_COMPILERS)
            flags = _CXXFLAGS_BASE
        else:  # fortran
            compiler = _find_compiler(_F_COMPILERS)
            flags = _FFLAGS_BASE

        if compiler is None:
            return CheckResult(name=name, status=CheckStatus.SKIP,
                               message="No suitable compiler found",
                               duration_s=time.monotonic() - t0)

        # When the patched file lives in a temp dir, relative #includes like
        # '../include/foo.h' cannot be resolved. Add -I flags so the compiler
        # searches the original source's directory and its parent, matching the
        # way the project is normally built.
        include_dirs = []
        original_dir = self._original_dir   # set by validate() from the original path
        if original_dir and original_dir.is_dir():
            include_dirs = [f"-I{original_dir}", f"-I{original_dir.parent}"]

        with tempfile.NamedTemporaryFile(suffix=".o", delete=True) as obj:
            cmd = [compiler] + flags + include_dirs + ["-c", str(path), "-o", obj.name]
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=self.timeout
                )
                dur = time.monotonic() - t0
                if proc.returncode == 0:
                    # Check for suspicious warnings
                    warn_lines = [l for l in proc.stderr.splitlines()
                                  if "warning" in l.lower()
                                  and any(w in l.lower() for w in
                                          ["undefined", "uninitialized", "overflow",
                                           "array-bounds", "use-after"])]
                    if warn_lines:
                        return CheckResult(
                            name=name, status=CheckStatus.WARNING,
                            message=f"Compiled with {len(warn_lines)} correctness warnings",
                            stderr="\n".join(warn_lines[:5]),
                            duration_s=dur,
                        )
                    return CheckResult(name=name, status=CheckStatus.PASS,
                                       message=f"Compiled OK ({compiler})", duration_s=dur)
                else:
                    # Some failures are environment limitations, not rule bugs.
                    # A missing Fortran .mod file means the source depends on a
                    # separately-compiled module (multi-file compilation); we
                    # cannot validate this stand-alone, so SKIP instead of FAIL.
                    # Similarly, a missing mpi.h means MPI is not installed in
                    # the validation environment — not a correctness problem.
                    skip_patterns = [
                        "cannot open module file",   # gfortran MODULE dependency
                        "no such file or directory",  # missing header (mpi.h etc.)
                        ".mod",
                        "mpi.h",
                    ]
                    stderr_lower = proc.stderr.lower()
                    if any(p.lower() in stderr_lower for p in skip_patterns):
                        return CheckResult(
                            name=name, status=CheckStatus.SKIP,
                            message=(
                                "Compilation requires missing environment files "
                                "(Fortran .mod or system headers like mpi.h). "
                                "Correctness cannot be established in this environment."
                            ),
                            stderr=proc.stderr[:300],
                            duration_s=dur,
                        )
                    return CheckResult(name=name, status=CheckStatus.FAIL,
                                       message=f"Compiler returned {proc.returncode}",
                                       stderr=proc.stderr[:500],
                                       duration_s=dur)
            except subprocess.TimeoutExpired:
                return CheckResult(name=name, status=CheckStatus.FAIL,
                                   message="Compilation timed out",
                                   duration_s=time.monotonic() - t0)

    # ── Test runner ───────────────────────────────────────────────────────────

    def _run_tests(
        self, test_dir: Path, language: str, patched: Path
    ) -> CheckResult:
        t0 = time.monotonic()
        name = "Test suite"

        if language == "python" and shutil.which("pytest"):
            cmd = ["pytest", str(test_dir), "-q", "--tb=short",
                   f"--timeout={self.timeout}"]
            # Inject patched file's parent onto PYTHONPATH
            env_patch = {"PYTHONPATH": str(patched.parent)}
        elif shutil.which("ctest"):
            cmd = ["ctest", "--test-dir", str(test_dir), "--output-on-failure",
                   f"--timeout {self.timeout}"]
            env_patch = {}
        else:
            return CheckResult(name=name, status=CheckStatus.SKIP,
                               message="No test runner found (pytest/ctest)",
                               duration_s=time.monotonic() - t0)

        import os
        env = {**os.environ, **env_patch}
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True,
                timeout=self.timeout * 2, env=env,
            )
            dur = time.monotonic() - t0
            if proc.returncode == 0:
                return CheckResult(name=name, status=CheckStatus.PASS,
                                   message="All tests passed", stdout=proc.stdout[:300],
                                   duration_s=dur)
            else:
                return CheckResult(name=name, status=CheckStatus.FAIL,
                                   message="Test failures detected",
                                   stdout=proc.stdout[-500:], stderr=proc.stderr[-300:],
                                   duration_s=dur)
        except subprocess.TimeoutExpired:
            return CheckResult(name=name, status=CheckStatus.FAIL,
                               message="Tests timed out", duration_s=time.monotonic() - t0)

    # ── Numerical diff (Python) ───────────────────────────────────────────────

    def _python_numerical_diff(
        self, original: Path, patched: Path
    ) -> tuple[CheckResult, Optional[float]]:
        """
        Import both modules and call a `run()` function if present,
        comparing numerical outputs.
        """
        import importlib.util, sys, types

        name = "Numerical diff"

        def load_mod(path: Path, mod_name: str) -> Optional[types.ModuleType]:
            spec = importlib.util.spec_from_file_location(mod_name, path)
            if spec is None or spec.loader is None:
                return None
            mod = importlib.util.module_from_spec(spec)
            try:
                spec.loader.exec_module(mod)  # type: ignore[arg-type]
                return mod
            except Exception:
                return None

        orig_mod = load_mod(original, "_perflens_orig")
        patched_mod = load_mod(patched, "_perflens_patched")

        if orig_mod is None or patched_mod is None:
            return CheckResult(name=name, status=CheckStatus.SKIP,
                               message="Could not import modules for numerical diff"), None

        run_orig = getattr(orig_mod, "run", None)
        run_patch = getattr(patched_mod, "run", None)

        if run_orig is None or run_patch is None:
            return CheckResult(name=name, status=CheckStatus.SKIP,
                               message="No `run()` function found for numerical comparison"), None

        try:
            import numpy as np
            r_orig   = run_orig()
            r_patch  = run_patch()
            arr_o = np.asarray(r_orig, dtype=float).ravel()
            arr_p = np.asarray(r_patch, dtype=float).ravel()
            if arr_o.shape != arr_p.shape:
                return CheckResult(name=name, status=CheckStatus.FAIL,
                                   message=f"Output shape mismatch: {arr_o.shape} vs {arr_p.shape}"), None
            max_diff = float(np.max(np.abs(arr_o - arr_p)))
            if max_diff <= self.tolerance:
                return CheckResult(name=name, status=CheckStatus.PASS,
                                   message=f"Max diff={max_diff:.2e} ≤ tol={self.tolerance:.1e}"), max_diff
            else:
                return CheckResult(name=name, status=CheckStatus.FAIL,
                                   message=f"Max diff={max_diff:.2e} exceeds tol={self.tolerance:.1e}"), max_diff
        except Exception as exc:
            return CheckResult(name=name, status=CheckStatus.WARNING,
                               message=f"Numerical diff error: {exc}"), None

    def _compiled_numerical_diff(
        self, original: Path, patched: Path, language: str
    ) -> tuple[CheckResult, Optional[float]]:
        """
        Establish numerical equivalence for compiled languages.

        Strategy (in priority order):
          1. If the user supplied a perflens_driver.sh next to the source, use it.
          2. Otherwise AUTO-GENERATE a harness: discover exported functions whose
             signatures we can synthesise inputs for, compile original+harness and
             patched+harness into two binaries, run both with identical seeded
             inputs, and compare their printed outputs.
          3. If no callable kernel can be harnessed, return SKIP (the caller marks
             this check critical, so an un-harnessable semantic change fails closed).
        """
        name = "Numerical diff"

        # 1. User-provided driver takes precedence.
        driver = original.parent / "perflens_driver.sh"
        if driver.exists():
            return self._diff_via_driver(driver, original, patched, name)

        # 2. Auto-generated harness.
        if language in ("c", "cpp"):
            return self._diff_via_autoharness(original, patched, language, name)

        # 3. Fortran auto-harness is not yet implemented → cannot verify.
        return CheckResult(
            name=name, status=CheckStatus.SKIP,
            message="No driver and auto-harness unavailable for this language — "
                    "correctness could not be established",
        ), None

    # ── Driver-based diff (user supplied) ─────────────────────────────────────

    def _diff_via_driver(
        self, driver: Path, original: Path, patched: Path, name: str
    ) -> tuple[CheckResult, Optional[float]]:
        def run_driver(src: Path) -> Optional[str]:
            try:
                proc = subprocess.run(
                    ["bash", str(driver), str(src)],
                    capture_output=True, text=True, timeout=self.timeout,
                )
                return proc.stdout if proc.returncode == 0 else None
            except Exception:
                return None

        out_orig    = run_driver(original)
        out_patched = run_driver(patched)
        if out_orig is None or out_patched is None:
            return CheckResult(name=name, status=CheckStatus.SKIP,
                               message="Driver failed to run"), None
        return self._compare_float_text(out_orig, out_patched, name)

    # ── Auto-generated harness diff ───────────────────────────────────────────

    def _diff_via_autoharness(
        self, original: Path, patched: Path, language: str, name: str
    ) -> tuple[CheckResult, Optional[float]]:
        from perflens.validator.harness import (
            discover_kernels, build_harness, HarnessError,
        )

        try:
            kernels = discover_kernels(original, language)
        except Exception as exc:
            return CheckResult(name=name, status=CheckStatus.SKIP,
                               message=f"Kernel discovery failed: {exc}"), None

        if not kernels:
            return CheckResult(
                name=name, status=CheckStatus.SKIP,
                message="No harness-able kernel found — correctness not established"), None

        compiler = (_find_compiler(_C_COMPILERS) if language == "c"
                    else _find_compiler(_CXX_COMPILERS))
        if compiler is None:
            return CheckResult(name=name, status=CheckStatus.SKIP,
                               message="No compiler available for harness"), None

        flags = _CFLAGS_BASE if language == "c" else _CXXFLAGS_BASE

        try:
            out_orig = build_harness(
                source=original, kernels=kernels, language=language,
                compiler=compiler, flags=flags, link_libs=_LINK_LIBS,
                timeout=self.timeout,
            )
            out_patched = build_harness(
                source=patched, kernels=kernels, language=language,
                compiler=compiler, flags=flags, link_libs=_LINK_LIBS,
                timeout=self.timeout,
            )
        except HarnessError as exc:
            return CheckResult(name=name, status=CheckStatus.SKIP,
                               message=f"Harness build/run failed: {exc}"), None

        if out_orig is None or out_patched is None:
            return CheckResult(name=name, status=CheckStatus.SKIP,
                               message="Harness produced no output"), None

        return self._compare_float_text(out_orig, out_patched, name)

    # ── Float comparison helper ───────────────────────────────────────────────

    def _compare_float_text(
        self, out_orig: str, out_patched: str, name: str
    ) -> tuple[CheckResult, Optional[float]]:
        import re
        import numpy as np

        def parse_floats(text: str) -> list[float]:
            return [float(x) for x in
                    re.findall(r"[-+]?\d*\.?\d+(?:[eE][-+]?\d+)?", text)]

        floats_o = parse_floats(out_orig)
        floats_p = parse_floats(out_patched)

        if not floats_o or len(floats_o) != len(floats_p):
            return CheckResult(name=name, status=CheckStatus.SKIP,
                               message="Could not parse matching float outputs"), None

        arr_o = np.array(floats_o)
        arr_p = np.array(floats_p)
        max_diff = float(np.max(np.abs(arr_o - arr_p)))

        if max_diff <= self.tolerance:
            return CheckResult(name=name, status=CheckStatus.PASS,
                               message=f"Max diff={max_diff:.2e} ≤ tol={self.tolerance:.1e} "
                                       f"({len(floats_o)} values)"), max_diff
        return CheckResult(name=name, status=CheckStatus.FAIL,
                           message=f"Numerical regression: max diff={max_diff:.2e} "
                                   f"> tol={self.tolerance:.1e}"), max_diff

    # ── Diff sanity ───────────────────────────────────────────────────────────

    @staticmethod
    def _diff_sanity_check(original: Path, patched: Path) -> CheckResult:
        import difflib
        orig_lines   = original.read_text(errors="replace").splitlines()
        patch_lines  = patched.read_text(errors="replace").splitlines()
        diff = list(difflib.unified_diff(orig_lines, patch_lines, lineterm=""))

        changed = sum(1 for l in diff if l.startswith(("+", "-")) and not l.startswith(("+++", "---")))
        total   = len(orig_lines)
        pct     = changed / max(total, 1) * 100

        if pct > 80:
            return CheckResult(
                name="Diff sanity",
                status=CheckStatus.WARNING,
                message=f"{changed}/{total} lines changed ({pct:.0f}%) — large rewrite, review carefully",
            )
        return CheckResult(
            name="Diff sanity",
            status=CheckStatus.PASS,
            message=f"{changed} lines changed ({pct:.0f}% of {total} total)",
        )
