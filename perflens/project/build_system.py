"""
Build System Driver — invokes the project's native build system while
injecting compiler flags to collect optimization reports automatically.

Supports:
  - CMake  (compile_commands.json + -DCMAKE_*_FLAGS)
  - Make   (CFLAGS / FFLAGS injection via env)
  - Meson  (b_ndebug + compiler args)
  - Bare   (compile each file individually)

The driver does TWO things in one build pass:
  1. Compiles the project at -O3 (for runtime performance)
  2. Collects per-file compiler opt-info reports automatically
     (GCC -fopt-info, Clang -Rpass, ICX -qopt-report)
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

from perflens.project.models import BuildSystem, CompileCommand, ProjectGraph


# ── Compiler flag injection ───────────────────────────────────────────────────

def _opt_flags(compiler: str, log_file: Optional[Path] = None) -> list[str]:
    """Return compiler flags that enable both -O3 and optimization reports."""
    c = Path(compiler).name.lower()

    if "icx" in c or "icpx" in c or "ifort" in c or "ifx" in c:
        flags = ["-O3", "-xCORE-AVX512", "-fopenmp", "-qopt-report=5"]
        if log_file:
            flags += [f"-qopt-report-file={log_file}"]
        return flags

    if "clang" in c:
        return [
            "-O3", "-march=native", "-fopenmp",
            "-Rpass=loop-vectorize",
            "-Rpass-missed=loop-vectorize",
            "-Rpass-analysis=loop-vectorize",
        ]

    # GCC / gfortran (default)
    flags = [
        "-O3", "-march=native", "-fopenmp",
        "-fopt-info-vec-optimized",
        "-fopt-info-vec-missed",
        "-fopt-info-loop",
    ]
    return flags


# ── compile_commands.json loader ─────────────────────────────────────────────

def _load_compile_commands(path: Path) -> dict[Path, CompileCommand]:
    """Parse compile_commands.json into a file→CompileCommand mapping."""
    result: dict[Path, CompileCommand] = {}
    try:
        entries = json.loads(path.read_text())
    except Exception:
        return result
    for entry in entries:
        file_path = Path(entry.get("file", "")).resolve()
        directory = Path(entry.get("directory", ".")).resolve()
        command   = entry.get("command", "")
        arguments = entry.get("arguments", command.split() if command else [])
        result[file_path] = CompileCommand(
            file=file_path,
            directory=directory,
            command=command,
            arguments=arguments,
        )
    return result


# ── Main driver ───────────────────────────────────────────────────────────────

class BuildDriver:
    """
    Detect and invoke the build system for *graph.root*.

    After a successful build:
    - ``graph.compile_commands`` is populated (per-file flags)
    - ``graph.build_dir`` points to the build output
    - ``graph.binary_paths`` lists produced executables
    - Per-file compiler opt-info is written to the build dir
      and parsed into ``SourceFile.compiler_feedback``
    """

    def __init__(
        self,
        graph: ProjectGraph,
        hardware,                      # HardwareProfile
        jobs: int = 0,                 # 0 = auto (nproc)
        extra_cmake_args: Optional[list[str]] = None,
        extra_cflags: Optional[list[str]] = None,
        timeout: int = 600,
    ):
        self.graph             = graph
        self.hardware          = hardware
        self.jobs              = jobs or _nproc()
        self.extra_cmake_args  = extra_cmake_args or []
        self.extra_cflags      = extra_cflags or []
        self.timeout           = timeout

    # ── Public API ────────────────────────────────────────────────────────────

    def build(self) -> bool:
        """
        Run the build, collect compile commands, attach compiler feedback.
        Returns True on success.
        """
        bs = self.graph.build_system

        if bs == BuildSystem.CMAKE:
            ok = self._build_cmake()
        elif bs == BuildSystem.MAKE:
            ok = self._build_make()
        elif bs == BuildSystem.MESON:
            ok = self._build_meson()
        elif bs == BuildSystem.PYTHON:
            ok = self._build_python()
        else:
            ok = self._build_bare()

        if ok:
            self._attach_compiler_feedback()
        return ok

    def collect_compiler_feedback_only(self) -> None:
        """
        Don't rebuild — just compile each source file once with opt-info flags
        and attach the resulting feedback.  Useful when the project is already
        built and we only want the reports.
        """
        for sf in self.graph.files.values():
            if sf.is_header or sf.language == "python":
                continue
            cc = self.graph.compile_commands.get(sf.path)
            feedback = self._compile_one_for_feedback(sf.path, cc)
            if feedback:
                sf.compiler_feedback = feedback

    # ── CMake ─────────────────────────────────────────────────────────────────

    def _build_cmake(self) -> bool:
        cmake = shutil.which("cmake")
        if not cmake:
            return False

        build_dir = self.graph.root / "build_perflens"
        build_dir.mkdir(exist_ok=True)
        self.graph.build_dir = build_dir

        # Pick compiler flags for opt-info
        c_compiler   = shutil.which("gcc") or shutil.which("clang") or "cc"
        cxx_compiler = shutil.which("g++") or shutil.which("clang++") or "c++"
        f_compiler   = shutil.which("gfortran") or "gfortran"

        opt_c   = " ".join(_opt_flags(c_compiler))
        opt_cxx = " ".join(_opt_flags(cxx_compiler))
        opt_f   = " ".join(_opt_flags(f_compiler))

        # Redirect GCC opt-info to a per-build log file
        log_file = build_dir / "compiler_opt.log"
        opt_c   += f" -fopt-info-vec-missed={log_file}"
        opt_cxx += f" -fopt-info-vec-missed={log_file}"

        configure_cmd = [
            cmake, str(self.graph.root),
            "-B", str(build_dir),
            "-DCMAKE_BUILD_TYPE=RelWithDebInfo",
            "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
            f"-DCMAKE_C_COMPILER={c_compiler}",
            f"-DCMAKE_CXX_COMPILER={cxx_compiler}",
            f"-DCMAKE_Fortran_COMPILER={f_compiler}",
            f"-DCMAKE_C_FLAGS={opt_c}",
            f"-DCMAKE_CXX_FLAGS={opt_cxx}",
            f"-DCMAKE_Fortran_FLAGS={opt_f}",
        ] + self.extra_cmake_args
        self.graph.cmake_options = {"build_dir": str(build_dir)}

        try:
            r = subprocess.run(configure_cmd, capture_output=True, text=True,
                               timeout=self.timeout, cwd=str(self.graph.root))
            if r.returncode != 0:
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

        # Build
        build_cmd = [cmake, "--build", str(build_dir),
                     "--parallel", str(self.jobs)]
        try:
            r = subprocess.run(build_cmd, capture_output=True, text=True,
                               timeout=self.timeout, cwd=str(self.graph.root))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

        # Load compile_commands.json
        cc_json = build_dir / "compile_commands.json"
        if cc_json.exists():
            self.graph.compile_commands = _load_compile_commands(cc_json)

        # Store the log for later parsing
        self.graph.build_flags = [f"log={log_file}"]

        # Find built binaries
        self._find_binaries(build_dir)
        return r.returncode == 0

    # ── Make ──────────────────────────────────────────────────────────────────

    def _build_make(self) -> bool:
        make = shutil.which("make") or shutil.which("gmake")
        if not make:
            return False

        c_compiler = shutil.which("gcc") or "gcc"
        log_file   = self.graph.root / "compiler_opt_perflens.log"
        opt_flags  = " ".join(_opt_flags(c_compiler)) + f" -fopt-info-vec-missed={log_file}"

        env = dict(os.environ)
        env["CFLAGS"]   = opt_flags
        env["CXXFLAGS"] = opt_flags.replace("-fopt-info-vec-missed=", "2>>")
        env["FFLAGS"]   = " ".join(["-O3", "-march=native", "-fopenmp",
                                     "-fopt-info-vec-missed"])

        cmd = [make, f"-j{self.jobs}"]
        try:
            r = subprocess.run(cmd, env=env, capture_output=True, text=True,
                               timeout=self.timeout, cwd=str(self.graph.root))
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

        # Store log path for later parsing
        if log_file.exists():
            self.graph.build_flags = [f"log={log_file}"]

        # Infer compile commands from Make output
        self._infer_compile_commands_from_make_output(r.stderr + r.stdout)
        self._find_binaries(self.graph.root)
        return r.returncode == 0

    # ── Meson ─────────────────────────────────────────────────────────────────

    def _build_meson(self) -> bool:
        meson = shutil.which("meson")
        ninja = shutil.which("ninja")
        if not (meson and ninja):
            return False

        build_dir = self.graph.root / "build_perflens"
        self.graph.build_dir = build_dir

        c_compiler = shutil.which("gcc") or "gcc"
        opt_flags  = " ".join(_opt_flags(c_compiler))

        setup_cmd = [
            meson, "setup", str(build_dir),
            "--buildtype=debugoptimized",
            "--wipe",
            f"-Dc_args={opt_flags}",
            f"-Dcpp_args={opt_flags}",
        ]
        try:
            r = subprocess.run(setup_cmd, capture_output=True, text=True,
                               timeout=120, cwd=str(self.graph.root))
            if r.returncode != 0:
                return False
            r = subprocess.run(
                [ninja, f"-j{self.jobs}"],
                capture_output=True, text=True,
                timeout=self.timeout, cwd=str(build_dir),
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False

        self._find_binaries(build_dir)
        return r.returncode == 0

    # ── Python project ────────────────────────────────────────────────────────

    def _build_python(self) -> bool:
        """For Python projects: install in editable mode so imports work."""
        pip = shutil.which("pip") or shutil.which("pip3")
        if not pip:
            return True   # assume already installed

        pyproject = self.graph.root / "pyproject.toml"
        setup     = self.graph.root / "setup.py"
        if not (pyproject.exists() or setup.exists()):
            return True   # no install step needed

        try:
            r = subprocess.run(
                [pip, "install", "-e", ".", "--quiet",
                 "--break-system-packages"],
                cwd=str(self.graph.root), capture_output=True,
                text=True, timeout=120,
            )
            return r.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return True

    # ── Bare (no build system) ────────────────────────────────────────────────

    def _build_bare(self) -> bool:
        """Compile each source file individually and record compile commands."""
        c_compiler   = shutil.which("gcc")   or "gcc"
        cxx_compiler = shutil.which("g++")   or "g++"
        f_compiler   = shutil.which("gfortran") or "gfortran"

        compiler_map = {"c": c_compiler, "cpp": cxx_compiler, "fortran": f_compiler}
        log_file     = self.graph.root / "compiler_opt_perflens.log"
        opt_flags    = _opt_flags(c_compiler)

        for sf in self.graph.source_files:
            if sf.is_header or sf.language == "python":
                continue
            comp = compiler_map.get(sf.language)
            if not comp:
                continue

            obj = sf.path.with_suffix(".o")
            flags = opt_flags + [f"-fopt-info-vec-missed={log_file}"]
            cmd   = [comp] + flags + ["-c", str(sf.path), "-o", str(obj)]
            try:
                subprocess.run(cmd, capture_output=True, timeout=60)
            except (subprocess.TimeoutExpired, FileNotFoundError):
                pass

            self.graph.compile_commands[sf.path] = CompileCommand(
                file=sf.path, directory=self.graph.root,
                command=" ".join(cmd), arguments=cmd,
            )

        if log_file.exists():
            self.graph.build_flags = [f"log={log_file}"]
        return True

    # ── Attach compiler feedback ──────────────────────────────────────────────

    def _attach_compiler_feedback(self) -> None:
        """Parse collected opt-info and attach to each SourceFile."""
        from perflens.compiler_feedback.gcc_parser import GCCFeedbackParser
        from perflens.compiler_feedback.clang_parser import ClangFeedbackParser

        # Global log file (Make / bare / CMake GCC path)
        log_path: Optional[Path] = None
        for flag in self.graph.build_flags:
            if flag.startswith("log="):
                log_path = Path(flag[4:])

        global_report = None
        if log_path and log_path.exists():
            global_report = GCCFeedbackParser()._parse_text(
                log_path.read_text(errors="replace"),
                source=self.graph.root,
            )

        for sf in self.graph.files.values():
            if sf.is_header or sf.language == "python":
                continue

            if global_report:
                # Filter global report to remarks for this file
                from perflens.compiler_feedback.models import CompilerFeedbackReport
                file_remarks = [
                    r for r in global_report.remarks
                    if r.source_file and Path(r.source_file).name == sf.path.name
                ]
                if file_remarks:
                    sf.compiler_feedback = CompilerFeedbackReport(
                        source=sf.path,
                        compiler=global_report.compiler,
                        remarks=file_remarks,
                    )
            else:
                # Fall back to per-file compile
                cc = self.graph.compile_commands.get(sf.path)
                feedback = self._compile_one_for_feedback(sf.path, cc)
                if feedback:
                    sf.compiler_feedback = feedback

    def _compile_one_for_feedback(self, path: Path, cc: Optional[CompileCommand]):
        """Compile one file with opt-info flags and return the feedback report."""
        from perflens.compiler_feedback import collect_feedback
        try:
            extra = list(self.extra_cflags)
            return collect_feedback(path, compiler=None, extra_flags=extra)
        except Exception:
            return None

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _find_binaries(self, search_dir: Path) -> None:
        """Find likely executable binaries in build output."""
        for p in search_dir.rglob("*"):
            if p.is_file() and not p.suffix and os.access(str(p), os.X_OK):
                if p.stat().st_size > 1024:   # skip tiny files
                    self.graph.binary_paths.append(p)

    def _infer_compile_commands_from_make_output(self, output: str) -> None:
        """Extract compile invocations from Make -n output."""
        cc_pattern = re.compile(
            r"(?:gcc|g\+\+|clang\+\+|clang|gfortran|icx|ifort)\s+.*?-c\s+(\S+\.(?:c|cpp|f90|f))\b"
        )
        for m in cc_pattern.finditer(output):
            src = Path(m.group(1))
            if not src.is_absolute():
                src = self.graph.root / src
            if src.exists() and src not in self.graph.compile_commands:
                self.graph.compile_commands[src] = CompileCommand(
                    file=src, directory=self.graph.root,
                    command=m.group(0), arguments=m.group(0).split(),
                )


def _nproc() -> int:
    try:
        import multiprocessing
        return multiprocessing.cpu_count()
    except Exception:
        return 4
