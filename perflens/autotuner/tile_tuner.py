"""
PerfLens Auto-Tuner.

Empirically searches for the best values of tunable parameters
(tile size, thread count, prefetch distance) by compiling and
running micro-benchmark variants.

Currently supports:
  - Tile size search for loop-tiling rule (C/C++/Fortran)
  - OpenMP thread count sweep
  - Prefetch distance sweep

Usage::

    from perflens.autotuner import TileSearchTuner
    from pathlib import Path

    tuner = TileSearchTuner(source=Path("stencil.c"), hardware=hw)
    best  = tuner.run(tile_candidates=[8, 16, 32, 64, 128])
    print(f"Best tile size: {best.tile_size}  ({best.runtime_ms:.1f} ms)")
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn


@dataclass
class TunePoint:
    """Result of one parameter configuration trial."""
    tile_size: Optional[int]    = None
    thread_count: Optional[int] = None
    prefetch_dist: Optional[int] = None
    runtime_ms: float           = float("inf")
    speedup: float              = 1.0
    compile_ok: bool            = False
    run_ok: bool                = False
    compiler_output: str        = ""


@dataclass
class TuneResult:
    """Best configuration found by the tuner."""
    best: TunePoint
    all_points: list[TunePoint] = field(default_factory=list)
    baseline_ms: float          = 0.0
    param_name: str             = ""

    def summary(self) -> str:
        if not self.best.run_ok:
            return "Auto-tuner: no valid configuration found"
        lines = [
            f"Auto-tuner result ({self.param_name}):",
            f"  Baseline   : {self.baseline_ms:.1f} ms",
            f"  Best value : {self.best.tile_size or self.best.thread_count}",
            f"  Best time  : {self.best.runtime_ms:.1f} ms",
            f"  Speedup    : {self.best.speedup:.2f}×",
        ]
        return "\n".join(lines)


class TileSearchTuner:
    """
    Empirically find the best TILE size for a loop-tiled C/C++ source.

    Expects the source to already contain ``#define TILE <N>`` (injected by
    the LoopTilingRule).  Replaces TILE value across candidates, compiles,
    runs, and reports the fastest.

    Args:
        source:           Tiled source file (must have ``#define TILE``)
        hardware:         HardwareProfile for compiler flags
        driver:           Optional driver binary/script that exercises the kernel
        timeout_s:        Max wall-time per trial (default 30s)
        warmup_runs:      Number of warm-up executions before timing (default 1)
        timed_runs:       Number of timed executions to average (default 3)
        console:          Rich Console for progress output
    """

    def __init__(
        self,
        source: Path,
        hardware,                  # HardwareProfile
        driver: Optional[Path] = None,
        timeout_s: int         = 30,
        warmup_runs: int       = 1,
        timed_runs: int        = 3,
        console: Optional[Console] = None,
    ):
        self.source      = source
        self.hardware    = hardware
        self.driver      = driver
        self.timeout_s   = timeout_s
        self.warmup_runs = warmup_runs
        self.timed_runs  = timed_runs
        self.console     = console or Console()

    # ── Public API ────────────────────────────────────────────────────────────

    def run(
        self,
        tile_candidates: Optional[list[int]] = None,
    ) -> TuneResult:
        """Search *tile_candidates* and return the best configuration."""
        if tile_candidates is None:
            tile_candidates = self._default_candidates()

        source_text = self.source.read_text(errors="replace")
        if "#define TILE" not in source_text:
            self.console.print(
                "[yellow]Auto-tuner: source does not contain #define TILE — "
                "apply LoopTilingRule first.[/yellow]"
            )
            return TuneResult(best=TunePoint(), param_name="tile_size")

        all_points: list[TunePoint] = []
        baseline_ms = float("inf")

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=self.console,
            transient=True,
        ) as progress:
            task = progress.add_task("Auto-tuning tile size…", total=len(tile_candidates))

            for tile in tile_candidates:
                progress.update(task, description=f"TILE={tile}  …")
                pt = self._trial(source_text, tile_size=tile)
                all_points.append(pt)
                if pt.run_ok and pt.runtime_ms < baseline_ms:
                    baseline_ms = pt.runtime_ms
                progress.advance(task)

        valid = [p for p in all_points if p.run_ok]
        if not valid:
            return TuneResult(best=TunePoint(), all_points=all_points,
                              param_name="tile_size")

        best = min(valid, key=lambda p: p.runtime_ms)
        first_runtime = valid[0].runtime_ms if valid else best.runtime_ms
        for pt in valid:
            pt.speedup = first_runtime / pt.runtime_ms if pt.runtime_ms > 0 else 1.0
        best.speedup = first_runtime / best.runtime_ms if best.runtime_ms > 0 else 1.0

        self.console.print(f"[green]Best tile: {best.tile_size}  "
                           f"{best.runtime_ms:.1f} ms  "
                           f"({best.speedup:.2f}× vs TILE={tile_candidates[0]})[/green]")
        return TuneResult(
            best=best,
            all_points=all_points,
            baseline_ms=first_runtime,
            param_name="tile_size",
        )

    # ── Thread count sweep ────────────────────────────────────────────────────

    def sweep_threads(
        self,
        thread_counts: Optional[list[int]] = None,
    ) -> TuneResult:
        """Sweep OMP_NUM_THREADS and return the best thread count."""
        if thread_counts is None:
            max_t = self.hardware.total_threads
            thread_counts = [1, 2, 4, 8, 16, 32, max_t]
            thread_counts = sorted(set(t for t in thread_counts if 0 < t <= max_t))

        source_text = self.source.read_text(errors="replace")
        all_points: list[TunePoint] = []
        first_runtime: Optional[float] = None

        for nthreads in thread_counts:
            pt = self._trial(source_text, tile_size=None, num_threads=nthreads)
            all_points.append(pt)
            if pt.run_ok and first_runtime is None:
                first_runtime = pt.runtime_ms

        valid = [p for p in all_points if p.run_ok]
        best  = min(valid, key=lambda p: p.runtime_ms) if valid else TunePoint()
        if first_runtime and valid:
            for pt in valid:
                pt.speedup = first_runtime / pt.runtime_ms if pt.runtime_ms > 0 else 1.0

        return TuneResult(
            best=best, all_points=all_points,
            baseline_ms=first_runtime or 0.0,
            param_name="thread_count",
        )

    # ── Internal trial runner ─────────────────────────────────────────────────

    def _trial(
        self,
        source_text: str,
        tile_size: Optional[int],
        num_threads: Optional[int] = None,
    ) -> TunePoint:
        pt = TunePoint(tile_size=tile_size, thread_count=num_threads)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_src = Path(tmpdir) / self.source.name
            tmp_bin = Path(tmpdir) / "perflens_trial"

            # Substitute tile size
            text = source_text
            if tile_size is not None:
                text = re.sub(r"#define\s+TILE\s+\d+", f"#define TILE {tile_size}", text)
            tmp_src.write_text(text)

            # Compile
            flags  = list(self.hardware.recommended_cflags) + ["-lm"]
            ext    = self.source.suffix.lower()
            compiler = self._pick_compiler(ext)
            if compiler is None:
                return pt

            cmd = [compiler] + flags + [str(tmp_src), "-o", str(tmp_bin)]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                pt.compiler_output = proc.stderr[:300]
                if proc.returncode != 0:
                    return pt
                pt.compile_ok = True
            except (subprocess.TimeoutExpired, FileNotFoundError):
                return pt

            # Determine run command
            if self.driver and self.driver.exists():
                run_cmd = [str(self.driver), str(tmp_bin)]
            else:
                run_cmd = [str(tmp_bin)]

            # Build environment
            import os
            env = dict(os.environ)
            if num_threads is not None:
                env["OMP_NUM_THREADS"] = str(num_threads)

            # Warm-up
            for _ in range(self.warmup_runs):
                try:
                    subprocess.run(run_cmd, capture_output=True,
                                   timeout=self.timeout_s, env=env)
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    return pt

            # Timed runs
            times: list[float] = []
            for _ in range(self.timed_runs):
                t0 = time.perf_counter()
                try:
                    proc = subprocess.run(run_cmd, capture_output=True,
                                          timeout=self.timeout_s, env=env)
                    if proc.returncode != 0:
                        return pt
                    times.append((time.perf_counter() - t0) * 1000)
                except (subprocess.TimeoutExpired, FileNotFoundError):
                    return pt

            pt.runtime_ms = min(times)   # best-of-N
            pt.run_ok     = True

        return pt

    def _pick_compiler(self, ext: str) -> Optional[str]:
        candidates = {
            ".c":   ["gcc", "clang", "icx"],
            ".cpp": ["g++", "clang++", "icpx"],
            ".cxx": ["g++", "clang++"],
            ".f90": ["gfortran", "ifx", "ifort"],
            ".f":   ["gfortran", "ifort"],
        }.get(ext, ["gcc"])
        return next((c for c in candidates if shutil.which(c)), None)

    def _default_candidates(self) -> list[int]:
        """Derive tile size candidates from hardware L1 cache."""
        import math
        l1_bytes = self.hardware.l1d_kb * 1024
        max_tile = int((l1_bytes / 8) ** (1 / 3))
        candidates = []
        t = 8
        while t <= max_tile * 2:
            candidates.append(t)
            t *= 2
        return candidates or [8, 16, 32, 64]
