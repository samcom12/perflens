"""
heat_solver.py — 2-D explicit heat equation solver

Anti-patterns for PerfLens to detect:
  1. Explicit for-loop over array indices instead of NumPy vectorised ops
  2. math.sqrt / math.exp inside a loop (scalar, not vectorised)
  3. np.zeros allocation inside the time loop
  4. pandas.iterrows() for post-processing
  5. Python threading instead of multiprocessing / mpi4py
  6. .apply(lambda) on a DataFrame row-by-row
"""

from __future__ import annotations

import math
import time
import threading
from typing import Optional

import numpy as np
import pandas as pd


# ─────────────────────────────────────────────────────────────────────────────
# ANTI-PATTERN 1: explicit loop instead of NumPy slice operations
# ─────────────────────────────────────────────────────────────────────────────

def laplacian_loop(u: np.ndarray) -> np.ndarray:
    """Compute 5-pt Laplacian using an explicit Python loop — extremely slow."""
    ny, nx = u.shape
    lap = np.zeros_like(u)                    # allocation OK here (outside loop)
    for i in range(1, ny - 1):
        for j in range(1, nx - 1):
            lap[i, j] = (u[i+1, j] + u[i-1, j] +
                         u[i, j+1] + u[i, j-1] - 4.0 * u[i, j])
    return lap


# ─────────────────────────────────────────────────────────────────────────────
# ANTI-PATTERN 2: scalar math.sqrt / math.exp inside a loop
# ─────────────────────────────────────────────────────────────────────────────

def apply_source_loop(u: np.ndarray, dt: float, t: float) -> np.ndarray:
    """Add a Gaussian source term — uses scalar math functions."""
    ny, nx = u.shape
    for i in range(ny):
        for j in range(nx):
            r2 = (i - ny // 2) ** 2 + (j - nx // 2) ** 2
            # ANTI-PATTERN: math.exp, math.sqrt in inner loop
            u[i, j] += dt * math.exp(-r2 / 50.0) * math.sin(t)
    return u


# ─────────────────────────────────────────────────────────────────────────────
# ANTI-PATTERN 3: array allocation inside the time loop
# ─────────────────────────────────────────────────────────────────────────────

def time_advance_bad(u: np.ndarray, alpha: float, dt: float, dx: float, nsteps: int) -> np.ndarray:
    """Advance the heat equation — allocates a temp array each step."""
    r = alpha * dt / dx**2
    for _ in range(nsteps):
        # ANTI-PATTERN: new allocation every iteration → GC pressure
        u_new = np.zeros_like(u)
        u_new[1:-1, 1:-1] = (u[1:-1, 1:-1]
                              + r * (u[2:, 1:-1] + u[:-2, 1:-1]
                                     + u[1:-1, 2:] + u[1:-1, :-2]
                                     - 4.0 * u[1:-1, 1:-1]))
        u = u_new
    return u


# ─────────────────────────────────────────────────────────────────────────────
# ANTI-PATTERN 4: pandas.iterrows() for post-processing
# ─────────────────────────────────────────────────────────────────────────────

def compute_stats_iterrows(df: pd.DataFrame) -> dict:
    """Compute per-row statistics using iterrows — N times slower than vectorised."""
    results = []
    for idx, row in df.iterrows():          # ANTI-PATTERN: iterrows
        val = row["temperature"]
        results.append({
            "idx":  idx,
            "norm": math.sqrt(val ** 2 + 1e-12),
            "exp":  math.exp(-val),
        })
    return results


# ─────────────────────────────────────────────────────────────────────────────
# ANTI-PATTERN 5: threading (GIL-bound) for CPU-intensive work
# ─────────────────────────────────────────────────────────────────────────────

def parallel_laplacian_threading(chunks: list[np.ndarray]) -> list[np.ndarray]:
    """Apply Laplacian to multiple chunks using threads — GIL prevents parallelism."""
    results = [None] * len(chunks)

    def worker(i: int, chunk: np.ndarray) -> None:
        results[i] = laplacian_loop(chunk)   # ANTI-PATTERN: threading for CPU work

    threads = [threading.Thread(target=worker, args=(i, c)) for i, c in enumerate(chunks)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


# ─────────────────────────────────────────────────────────────────────────────
# ANTI-PATTERN 6: .apply(lambda) row-by-row
# ─────────────────────────────────────────────────────────────────────────────

def normalise_df_apply(df: pd.DataFrame) -> pd.DataFrame:
    """Normalise temperature column using apply(lambda) — much slower than vectorised."""
    df["norm_temp"] = df.apply(                       # ANTI-PATTERN: apply(lambda)
        lambda row: row["temperature"] / (math.sqrt(row["temperature"]**2 + 1.0)),
        axis=1,
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Benchmark harness — callable as `run()` for PerfLens numerical diff
# ─────────────────────────────────────────────────────────────────────────────

def run(nx: int = 128, ny: int = 128, nsteps: int = 50) -> np.ndarray:
    """Entry point used by PerfLens validator for numerical comparison."""
    alpha = 0.01
    dt    = 0.001
    dx    = 1.0 / nx

    u = np.zeros((ny, nx))
    # Warm boundary: left edge = 1.0
    u[:, 0] = 1.0

    u = time_advance_bad(u, alpha=alpha, dt=dt, dx=dx, nsteps=nsteps)
    return u


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Heat solver — PerfLens example")
    parser.add_argument("--nx",     type=int, default=256)
    parser.add_argument("--ny",     type=int, default=256)
    parser.add_argument("--nsteps", type=int, default=100)
    args = parser.parse_args()

    t0 = time.perf_counter()
    result = run(nx=args.nx, ny=args.ny, nsteps=args.nsteps)
    elapsed = time.perf_counter() - t0

    print(f"Grid: {args.nx}×{args.ny}  steps={args.nsteps}")
    print(f"Elapsed: {elapsed*1000:.1f} ms")
    print(f"Centre temperature: {result[args.ny//2, args.nx//2]:.6e}")
    print(f"Max temperature:    {result.max():.6e}")
