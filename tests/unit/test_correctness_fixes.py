"""
Regression tests for the correctness bugs found in the main-branch audit.

Each test pins a specific bug fix so it cannot silently regress:
  Bug 1  OpenMPParallelRule annotated every loop incl. inner + reductions
  Bug 2  DivisionHoistRule produced non-compiling code (1.0/double, inv_h[i])
  Bug 3  OpenMPOffloadRule mapped the scalar bound instead of arrays
  Bug 4  ValidationReport.passed treated SKIP/WARNING as success
  Bug 5  Validator never ran numerical diff without perflens_driver.sh
  Bug 5F FortranOpenMPDoRule emitted unbalanced !$OMP END PARALLEL DO
  Bug 6  Autotuner silently failed on multi-file kernels (no main)
"""

from __future__ import annotations

import shutil
import textwrap
from pathlib import Path

import pytest

from perflens.optimizer.rules.base_rule import RuleContext
from perflens.hardware.database import HardwareDatabase


def _ctx(src, lang, hw, findings=None):
    return RuleContext(source=src, language=lang, path=Path(f"t.{lang}"),
                       hardware=hw, findings=findings or [])


@pytest.fixture
def cpu_hw():
    return HardwareDatabase().get("intel_spr")

@pytest.fixture
def gpu_hw():
    return HardwareDatabase().get("a100")


# ── Bug 1: OpenMP parallel only on outermost, skip reductions ─────────────────

class TestBug1_OpenMPParallel:
    def test_only_outermost_loop_annotated(self, cpu_hw):
        from perflens.optimizer.rules.c_rules import OpenMPParallelRule
        src = textwrap.dedent("""\
            void scale(double *A, double *B, int n) {
                for (int i = 0; i < n; i++) {
                    for (int j = 0; j < n; j++) {
                        B[i*n+j] = A[i*n+j] * 2.0;
                    }
                }
            }
        """)
        res = OpenMPParallelRule().apply(_ctx(src, "c", cpu_hw))
        assert res is not None
        out = res[0]
        assert out.count("#pragma omp parallel for") == 1

    def test_reduction_loop_not_parallelised(self, cpu_hw):
        from perflens.optimizer.rules.c_rules import OpenMPParallelRule
        src = textwrap.dedent("""\
            double dot(double *a, double *b, int n) {
                double sum = 0.0;
                for (int i = 0; i < n; i++) {
                    sum += a[i] * b[i];
                }
                return sum;
            }
        """)
        res = OpenMPParallelRule().apply(_ctx(src, "c", cpu_hw))
        # Either no change, or at least no pragma on the reduction loop
        if res is not None:
            assert "#pragma omp parallel for" not in res[0]

    def test_matmul_reduction_nest_skipped(self, cpu_hw):
        from perflens.optimizer.rules.c_rules import OpenMPParallelRule
        src = textwrap.dedent("""\
            void mm(double *A, double *B, double *C, int n) {
                for (int i = 0; i < n; i++) {
                    for (int j = 0; j < n; j++) {
                        double s = 0.0;
                        for (int k = 0; k < n; k++) s += A[i*n+k]*B[k*n+j];
                        C[i*n+j] = s;
                    }
                }
            }
        """)
        res = OpenMPParallelRule().apply(_ctx(src, "c", cpu_hw))
        cnt = res[0].count("#pragma omp parallel for") if res else 0
        assert cnt == 0


# ── Bug 2: division hoist must compile and only hoist invariant scalars ────────

class TestBug2_DivisionHoist:
    def _has_gcc(self):
        return shutil.which("gcc") is not None

    def test_does_not_hoist_keyword_double(self, cpu_hw):
        from perflens.optimizer.rules.c_rules import DivisionHoistRule
        from perflens.scanner.models import Finding, FindingKind, Severity
        src = textwrap.dedent("""\
            void f(double *a, int n) {
                for (int i = 0; i < n; i++) {
                    a[i] = (double)(a[i]) / 2.0;
                }
            }
        """)
        f = Finding(Path("f.c"), 3, 0, FindingKind.DIVISION_IN_LOOP,
                    Severity.MEDIUM, "d", "h")
        res = DivisionHoistRule().apply(_ctx(src, "c", cpu_hw, [f]))
        if res is not None:
            assert "1.0 / double" not in res[0]
            assert "inv_double" not in res[0]

    def test_does_not_hoist_indexed_divisor(self, cpu_hw):
        from perflens.optimizer.rules.c_rules import DivisionHoistRule
        from perflens.scanner.models import Finding, FindingKind, Severity
        src = textwrap.dedent("""\
            void f(double *a, double *h, int n) {
                for (int i = 0; i < n; i++) {
                    a[i] = a[i] / h[i];
                }
            }
        """)
        f = Finding(Path("f.c"), 3, 0, FindingKind.DIVISION_IN_LOOP,
                    Severity.MEDIUM, "d", "h")
        res = DivisionHoistRule().apply(_ctx(src, "c", cpu_hw, [f]))
        # h[i] is not loop-invariant — must not be hoisted
        if res is not None:
            assert "inv_h" not in res[0]

    def test_hoists_invariant_scalar_and_compiles(self, cpu_hw):
        from perflens.optimizer.rules.c_rules import DivisionHoistRule
        from perflens.scanner.models import Finding, FindingKind, Severity
        src = textwrap.dedent("""\
            #include <math.h>
            void f(double *a, double scale, int n) {
                for (int i = 0; i < n; i++) {
                    a[i] = a[i] / scale;
                }
            }
        """)
        f = Finding(Path("f.c"), 4, 0, FindingKind.DIVISION_IN_LOOP,
                    Severity.MEDIUM, "d", "h")
        res = DivisionHoistRule().apply(_ctx(src, "c", cpu_hw, [f]))
        assert res is not None
        assert "inv_scale" in res[0]
        if self._has_gcc():
            import subprocess, tempfile
            d = Path(tempfile.mkdtemp())
            (d / "f.c").write_text(res[0])
            r = subprocess.run(["gcc", "-O0", "-fno-fast-math", "-c",
                                str(d / "f.c"), "-o", str(d / "f.o")],
                               capture_output=True, text=True)
            assert r.returncode == 0, f"hoisted code must compile: {r.stderr}"


# ── Bug 3: offload maps real arrays, never the scalar bound ───────────────────

class TestBug3_OpenMPOffload:
    def test_maps_arrays_not_bound(self, gpu_hw):
        from perflens.optimizer.rules.c_rules import OpenMPOffloadRule
        src = textwrap.dedent("""\
            void saxpy(double *y, const double *x, double a, int n) {
                for (int i = 0; i < n; i++) {
                    y[i] = a * x[i] + y[i];
                }
            }
        """)
        res = OpenMPOffloadRule().apply(_ctx(src, "c", gpu_hw))
        assert res is not None
        line = [l for l in res[0].splitlines() if "target" in l][0]
        assert "map(tofrom:n[0:n])" not in line
        assert "map(tofrom:y[0:n])" in line
        assert "map(tofrom:x[0:n])" in line

    def test_skips_when_no_arrays(self, gpu_hw):
        from perflens.optimizer.rules.c_rules import OpenMPOffloadRule
        src = textwrap.dedent("""\
            void f(int n) {
                for (int i = 0; i < n; i++) {
                    int x = i * 2;
                }
            }
        """)
        res = OpenMPOffloadRule().apply(_ctx(src, "c", gpu_hw))
        # No arrays to map → must not emit an invalid pragma
        if res is not None:
            assert "map(tofrom:n" not in res[0]


# ── Bug 4 + 5: validation gate fails closed, harness verifies correctness ─────

class TestBug4_5_Validator:
    def _has_gcc(self):
        return shutil.which("gcc") is not None

    def test_skip_critical_check_is_not_passed(self):
        from perflens.validator.models import (
            ValidationReport, CheckResult, CheckStatus,
        )
        rep = ValidationReport(original=Path("a.c"), patched=Path("b.c"))
        rep.checks.append(CheckResult("Compile", CheckStatus.PASS))
        rep.checks.append(CheckResult("Numerical diff", CheckStatus.SKIP,
                                      critical=True))
        rep.semantics_may_change = True
        rep.correctness_verified = False
        assert rep.passed is False
        assert rep.verdict == "unverified"

    def test_verified_patch_passes(self):
        from perflens.validator.models import (
            ValidationReport, CheckResult, CheckStatus,
        )
        rep = ValidationReport(original=Path("a.c"), patched=Path("b.c"))
        rep.checks.append(CheckResult("Compile", CheckStatus.PASS))
        rep.checks.append(CheckResult("Numerical diff", CheckStatus.PASS,
                                      critical=True))
        rep.semantics_may_change = True
        rep.correctness_verified = True
        assert rep.passed is True
        assert rep.verdict == "passed"

    def test_comment_only_change_is_behaviour_preserving(self, tmp_path):
        from perflens.validator.checker import PatchValidator
        orig = tmp_path / "a.c"
        patched = tmp_path / "b.c"
        orig.write_text("void f(double*a,int n){for(int i=0;i<n;i++)a[i]+=1.0;}\n")
        patched.write_text("/* optimized */\nvoid f(double*a,int n){for(int i=0;i<n;i++)a[i]+=1.0;}\n")
        v = PatchValidator()
        assert v._semantics_may_change(orig, patched) is False

    def test_harness_accepts_correct_rejects_wrong(self, tmp_path):
        if not self._has_gcc():
            pytest.skip("gcc not available")
        from perflens.validator.checker import PatchValidator
        orig = tmp_path / "k.c"
        orig.write_text(textwrap.dedent("""\
            #include <math.h>
            void scale(double *a, int n, double s) {
                for (int i = 0; i < n; i++) a[i] = a[i]*s + sin(a[i]);
            }
        """))
        good = tmp_path / "good.c"
        good.write_text(textwrap.dedent("""\
            #include <math.h>
            void scale(double *a, int n, double s) {
                #pragma omp simd
                for (int i = 0; i < n; i++) a[i] = a[i]*s + sin(a[i]);
            }
        """))
        bad = tmp_path / "bad.c"
        bad.write_text(textwrap.dedent("""\
            #include <math.h>
            void scale(double *a, int n, double s) {
                for (int i = 0; i < n; i++) a[i] = a[i]*s + cos(a[i]);
            }
        """))
        v = PatchValidator()
        assert v.validate(orig, good).verdict == "passed"
        assert v.validate(orig, bad).verdict == "failed"


# ── Bug 5F: Fortran OMP DO balanced and compiles ──────────────────────────────

class TestBug5F_FortranOMP:
    def test_balanced_parallel_do(self, cpu_hw):
        from perflens.optimizer.rules.fortran_rules import FortranOpenMPDoRule
        src = textwrap.dedent("""\
            SUBROUTINE work(a, n)
              IMPLICIT NONE
              INTEGER, INTENT(IN) :: n
              REAL(8), INTENT(INOUT) :: a(n,n)
              INTEGER :: i, j
              DO i = 1, n
                DO j = 1, n
                  a(i,j) = a(i,j) * 2.0_8
                END DO
              END DO
            END SUBROUTINE
        """)
        res = FortranOpenMPDoRule().apply(_ctx(src, "fortran", cpu_hw))
        assert res is not None
        out = res[0].upper()
        assert out.count("!$OMP PARALLEL DO") == 1
        assert out.count("!$OMP END PARALLEL DO") == 1

    def test_fortran_omp_compiles(self, cpu_hw):
        if not shutil.which("gfortran"):
            pytest.skip("gfortran not available")
        from perflens.optimizer.rules.fortran_rules import FortranOpenMPDoRule
        import subprocess, tempfile
        src = textwrap.dedent("""\
            SUBROUTINE work(a, n)
              IMPLICIT NONE
              INTEGER, INTENT(IN) :: n
              REAL(8), INTENT(INOUT) :: a(n,n)
              INTEGER :: i, j
              DO i = 1, n
                DO j = 1, n
                  a(i,j) = a(i,j) * 2.0_8
                END DO
              END DO
            END SUBROUTINE
        """)
        res = FortranOpenMPDoRule().apply(_ctx(src, "fortran", cpu_hw))
        d = Path(tempfile.mkdtemp())
        (d / "w.f90").write_text(res[0])
        r = subprocess.run(["gfortran", "-fopenmp", "-c",
                            str(d / "w.f90"), "-o", str(d / "w.o")],
                           capture_output=True, text=True)
        assert r.returncode == 0, f"Fortran OMP must compile: {r.stderr}"


# ── Bug 6: autotuner reports a clear reason on multi-file kernels ─────────────

class TestBug6_Autotuner:
    def test_no_main_reports_clear_message(self, cpu_hw, tmp_path):
        from perflens.autotuner.tile_tuner import TileSearchTuner
        src = tmp_path / "kernel.c"
        src.write_text(textwrap.dedent("""\
            #define TILE 32
            void kernel(double *a, int n) {
                for (int i = 0; i < n; i += TILE) a[i] += 1.0;
            }
        """))
        tuner = TileSearchTuner(source=src, hardware=cpu_hw,
                                warmup_runs=0, timed_runs=1)
        pt = tuner._trial(src.read_text(), tile_size=32)
        assert pt.run_ok is False
        assert "main()" in pt.compiler_output

    def test_build_command_path_used(self, cpu_hw, tmp_path):
        if not shutil.which("gcc"):
            pytest.skip("gcc not available")
        from perflens.autotuner.tile_tuner import TileSearchTuner
        # A complete program with main → single-file mode works
        src = tmp_path / "prog.c"
        src.write_text(textwrap.dedent("""\
            #include <stdio.h>
            #define TILE 16
            int main(void) {
                double s = 0;
                for (int i = 0; i < 1000; i += TILE) s += i;
                printf("%f\\n", s);
                return 0;
            }
        """))
        tuner = TileSearchTuner(source=src, hardware=cpu_hw,
                                warmup_runs=0, timed_runs=1)
        pt = tuner._trial(src.read_text(), tile_size=16)
        assert pt.compile_ok is True
        assert pt.run_ok is True


# ── Bugs found during docs verification ───────────────────────────────────────

class TestDocsBugs:
    def _gcc(self):
        return shutil.which("gcc") is not None

    def test_loop_tiling_brace_balanced_and_compiles(self, cpu_hw, tmp_path):
        """LoopTilingRule must not emit inline #define or unbalanced braces."""
        from perflens.optimizer.rules.c_rules import LoopTilingRule
        src = textwrap.dedent("""\
            void add3d(double *A, double *B, double *C, int N) {
                for (int i = 0; i < N; i++) {
                    for (int j = 0; j < N; j++) {
                        for (int k = 0; k < N; k++) {
                            C[i*N*N+j*N+k] = A[i*N*N+j*N+k] + B[i*N*N+j*N+k];
                        }
                    }
                }
            }
        """)
        res = LoopTilingRule().apply(_ctx(src, "c", cpu_hw))
        assert res is not None
        out = res[0]
        # #define must be on its own line, never inline after '{'
        assert "{#define" not in out
        assert out.count("{") == out.count("}")
        # TILE macro present at top
        assert "#define TILE" in out
        if self._gcc():
            import subprocess
            p = tmp_path / "t.c"; p.write_text(out)
            r = subprocess.run(["gcc", "-O0", "-fno-fast-math", "-c",
                                str(p), "-o", str(tmp_path / "t.o")],
                               capture_output=True, text=True)
            assert r.returncode == 0, f"tiled code must compile: {r.stderr}"

    def test_tiling_skips_imperfect_nest(self, cpu_hw):
        """Matmul-style nests (accumulator between loops) must not be tiled."""
        from perflens.optimizer.rules.c_rules import LoopTilingRule
        src = textwrap.dedent("""\
            void mm(double *A, double *B, double *C, int n) {
                for (int i = 0; i < n; i++) {
                    for (int j = 0; j < n; j++) {
                        double sum = 0.0;
                        for (int k = 0; k < n; k++) {
                            sum += A[i*n+k] * B[k*n+j];
                        }
                        C[i*n+j] = sum;
                    }
                }
            }
        """)
        res = LoopTilingRule().apply(_ctx(src, "c", cpu_hw))
        # Imperfect nest → no tiling (would break accumulator scoping)
        assert res is None

    def test_offload_no_cross_function_contamination(self, gpu_hw):
        """Braceless loops must not pull arrays from the next function."""
        from perflens.optimizer.rules.c_rules import OpenMPOffloadRule
        src = textwrap.dedent("""\
            static void free2d(double **a, int rows) {
                for (int i = 0; i < rows; i++) free(a[i]);
            }
            void k(double *u, double *un, int n) {
                for (int i = 0; i < n; i++) { un[i] = u[i]*2.0; }
            }
        """)
        res = OpenMPOffloadRule().apply(_ctx(src, "c", gpu_hw))
        assert res is not None
        out = res[0]
        # free2d's loop region must not get a target pragma mapping u/un
        free_region = out.split("void k")[0]
        assert "#pragma omp target" not in free_region

    def test_offload_skips_alloc_free_loops(self, gpu_hw):
        from perflens.optimizer.rules.c_rules import OpenMPOffloadRule
        src = textwrap.dedent("""\
            void setup(double **a, int rows) {
                for (int i = 0; i < rows; i++) {
                    a[i] = malloc(8 * rows);
                }
            }
        """)
        res = OpenMPOffloadRule().apply(_ctx(src, "c", gpu_hw))
        # malloc loop must never be offloaded
        if res is not None:
            assert "#pragma omp target" not in res[0]


# ── 2D (double**) harness support ─────────────────────────────────────────────

class TestHarness2D:
    def _gcc(self):
        return shutil.which("gcc") is not None

    def test_discovers_2d_kernel_skips_memory_funcs(self):
        from perflens.validator.harness import discover_kernels
        from pathlib import Path
        import tempfile, textwrap
        d = Path(tempfile.mkdtemp())
        src = d / "s.c"
        src.write_text(textwrap.dedent("""\
            #include <stdlib.h>
            static double **alloc2d(int n) {
                double **a = malloc(n*sizeof(double*));
                for (int i=0;i<n;i++) a[i]=malloc(n*sizeof(double));
                return a;
            }
            static void free2d(double **a, int n) {
                for (int i=0;i<n;i++) free(a[i]);
                free(a);
            }
            void smooth(double **u, double **v, int n) {
                for (int i=1;i<n-1;i++)
                    for (int j=1;j<n-1;j++)
                        v[i][j] = 0.25*(u[i-1][j]+u[i+1][j]+u[i][j-1]+u[i][j+1]);
            }
        """))
        ks = discover_kernels(src, "c")
        assert len(ks) == 1
        # Must pick the compute kernel, not alloc2d/free2d
        assert ks[0].name == "smooth"

    def test_2d_harness_accepts_correct_rejects_wrong(self, tmp_path):
        if not self._gcc():
            pytest.skip("gcc not available")
        from perflens.validator.checker import PatchValidator
        import textwrap
        orig = tmp_path / "k.c"
        orig.write_text(textwrap.dedent("""\
            void smooth(double **u, double **v, int n) {
                for (int i=1;i<n-1;i++)
                    for (int j=1;j<n-1;j++)
                        v[i][j] = 0.25*(u[i-1][j]+u[i+1][j]+u[i][j-1]+u[i][j+1]);
            }
        """))
        good = tmp_path / "good.c"
        good.write_text(textwrap.dedent("""\
            void smooth(double **u, double **v, int n) {
                #pragma omp parallel for
                for (int i=1;i<n-1;i++)
                    for (int j=1;j<n-1;j++)
                        v[i][j] = 0.25*(u[i-1][j]+u[i+1][j]+u[i][j-1]+u[i][j+1]);
            }
        """))
        bad = tmp_path / "bad.c"
        bad.write_text(textwrap.dedent("""\
            void smooth(double **u, double **v, int n) {
                for (int i=1;i<n-1;i++)
                    for (int j=1;j<n-1;j++)
                        v[i][j] = 0.20*(u[i-1][j]+u[i+1][j]+u[i][j-1]+u[i][j+1]);
            }
        """))
        v = PatchValidator()
        assert v.validate(orig, good).verdict == "passed"
        assert v.validate(orig, bad).verdict == "failed"

    def test_2d_harness_handles_source_with_own_main(self, tmp_path):
        if not self._gcc():
            pytest.skip("gcc not available")
        from perflens.validator.checker import PatchValidator
        import textwrap
        body = textwrap.dedent("""\
            #include <stdio.h>
            #define N 64
            void scale2d(double **u, int n) {
                for (int i=0;i<n;i++)
                    for (int j=0;j<n;j++)
                        u[i][j] = u[i][j] * 2.0;
            }
            int main(void){ printf("hi\\n"); return 0; }
        """)
        orig = tmp_path / "k.c"; orig.write_text(body)
        patched = tmp_path / "p.c"
        patched.write_text(body.replace("void scale2d(double **u, int n) {",
                                        "void scale2d(double **u, int n) {\n    #pragma omp parallel for"))
        # Source defines its own main() and N — harness must still work
        rep = PatchValidator().validate(orig, patched)
        assert rep.verdict == "passed"
