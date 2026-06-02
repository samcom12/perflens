"""
shallow_water.py — Simplified shallow water equations solver

Inspired by ANUGA hydrodynamic framework patterns.
Contains realistic HPC anti-patterns for PerfLens optimization.

Anti-patterns:
  1. Python-level loop over triangular mesh cells
  2. linecache-based rainfall loading (line-by-line file read in loop)
  3. np.ma (masked array) overhead in inner loop
  4. file_function boundary interpolation called every timestep
  5. Redundant recomputation of bed slope each iteration
"""

from __future__ import annotations

import math
import time
from pathlib import Path
from typing import Optional

import numpy as np


# ─────────────────────────────────────────────────────────────────────────────
# Mesh and state containers
# ─────────────────────────────────────────────────────────────────────────────

class TriangularMesh:
    """Minimal triangular mesh for the SWE solver."""
    def __init__(self, ncells: int, seed: int = 42):
        rng = np.random.default_rng(seed)
        self.ncells    = ncells
        self.areas     = rng.uniform(0.5, 2.0, ncells)
        # Each cell has 3 neighbours (−1 = boundary)
        self.neighbours = np.where(
            rng.random((ncells, 3)) > 0.05,
            rng.integers(0, ncells, (ncells, 3)),
            -1,
        )
        self.bed_elev   = rng.uniform(-1.0, 0.5, ncells)
        self.edge_len   = rng.uniform(0.5, 1.5, (ncells, 3))


class SWEState:
    def __init__(self, ncells: int):
        self.stage    = np.zeros(ncells)   # water surface elevation (η)
        self.xmom     = np.zeros(ncells)   # x-momentum (uh)
        self.ymom     = np.zeros(ncells)   # y-momentum (vh)
        self.height   = np.zeros(ncells)   # h = η − z


# ─────────────────────────────────────────────────────────────────────────────
# ANTI-PATTERN 1: Python loop over cells for flux computation
# ─────────────────────────────────────────────────────────────────────────────

def compute_fluxes_loop(mesh: TriangularMesh, state: SWEState,
                        dt: float, g: float = 9.81) -> np.ndarray:
    """Compute inter-cell fluxes — explicit Python loop (should use Cython/C kernel)."""
    dU = np.zeros(mesh.ncells)
    for k in range(mesh.ncells):                    # ANTI-PATTERN: Python loop
        h_k = state.height[k]
        if h_k < 1e-6:
            continue
        for n in range(3):
            nb = mesh.neighbours[k, n]
            if nb < 0:
                continue
            h_nb = state.height[nb]
            deta = state.stage[nb] - state.stage[k]
            # Roe-averaged wave speed estimate
            c_k  = math.sqrt(g * max(h_k,  1e-10))  # ANTI-PATTERN: scalar math.sqrt
            c_nb = math.sqrt(g * max(h_nb, 1e-10))
            s_max = max(abs(state.xmom[k] / max(h_k, 1e-10)) + c_k,
                        abs(state.xmom[nb] / max(h_nb, 1e-10)) + c_nb)
            flux = -0.5 * s_max * deta * mesh.edge_len[k, n]
            dU[k] += flux * dt / mesh.areas[k]
    return dU


# ─────────────────────────────────────────────────────────────────────────────
# ANTI-PATTERN 2: linecache line-by-line rainfall loading inside timestep loop
# ─────────────────────────────────────────────────────────────────────────────

def load_rainfall_linecache(rainfall_file: Path, timestep: int) -> float:
    """Load rainfall rate for current timestep using linecache — very slow."""
    import linecache
    # ANTI-PATTERN: linecache.getline called every timestep
    line = linecache.getline(str(rainfall_file), timestep + 2)  # skip header
    if not line.strip():
        return 0.0
    try:
        return float(line.strip().split(",")[1])
    except (IndexError, ValueError):
        return 0.0


# ─────────────────────────────────────────────────────────────────────────────
# ANTI-PATTERN 3: numpy.ma overhead in inner loop
# ─────────────────────────────────────────────────────────────────────────────

def update_height_masked(state: SWEState, mesh: TriangularMesh) -> None:
    """Update water height using numpy.ma — mask evaluation overhead per element."""
    import numpy.ma as ma
    # ANTI-PATTERN: creating a masked array each call instead of plain array ops
    stage_ma  = ma.masked_less(state.stage, mesh.bed_elev)
    height_ma = stage_ma - mesh.bed_elev
    state.height = np.where(height_ma.mask if hasattr(height_ma, 'mask') else False,
                            0.0, np.asarray(height_ma.filled(0.0)))


# ─────────────────────────────────────────────────────────────────────────────
# ANTI-PATTERN 4: boundary interpolation called every timestep
# ─────────────────────────────────────────────────────────────────────────────

class TideBoundary:
    """Simulate ANUGA file_function tide boundary — reads and interpolates each call."""

    def __init__(self, times: np.ndarray, values: np.ndarray):
        self._times  = times
        self._values = values

    def __call__(self, t: float) -> float:
        # ANTI-PATTERN: np.searchsorted + interp called every timestep
        idx = np.searchsorted(self._times, t)
        if idx == 0:
            return float(self._values[0])
        if idx >= len(self._times):
            return float(self._values[-1])
        t0, t1 = self._times[idx-1], self._times[idx]
        v0, v1 = self._values[idx-1], self._values[idx]
        alpha  = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
        return float(v0 + alpha * (v1 - v0))


# ─────────────────────────────────────────────────────────────────────────────
# ANTI-PATTERN 5: recompute bed slope every iteration instead of caching
# ─────────────────────────────────────────────────────────────────────────────

def bed_slope_force(mesh: TriangularMesh, state: SWEState,
                    g: float = 9.81) -> np.ndarray:
    """Compute bed slope source term — recomputed each iteration (should be cached)."""
    # ANTI-PATTERN: this only depends on mesh.bed_elev (static) but is recomputed
    dz = np.zeros((mesh.ncells, 3))
    for k in range(mesh.ncells):               # ANTI-PATTERN: Python loop again
        for n in range(3):
            nb = mesh.neighbours[k, n]
            if nb >= 0:
                dz[k, n] = mesh.bed_elev[nb] - mesh.bed_elev[k]
    slope_force = -g * state.height * np.sum(dz, axis=1) / 3.0
    return slope_force


# ─────────────────────────────────────────────────────────────────────────────
# Solver loop
# ─────────────────────────────────────────────────────────────────────────────

def run(ncells: int = 5000, nsteps: int = 20, dt: float = 0.01) -> np.ndarray:
    """Main solver loop — entry point for PerfLens validator numerical diff."""
    mesh  = TriangularMesh(ncells)
    state = SWEState(ncells)

    # Initial condition: dome of water in centre cells
    centre = ncells // 2
    state.stage[max(0, centre-50):min(ncells, centre+50)] = 0.5
    state.height[:] = np.maximum(state.stage - mesh.bed_elev, 0.0)

    # Dummy tide boundary
    tide = TideBoundary(
        times=np.linspace(0, nsteps * dt, 100),
        values=0.1 * np.sin(np.linspace(0, 2 * math.pi, 100)),
    )

    for step in range(nsteps):
        t = step * dt

        # Apply boundary
        state.stage[0]  = tide(t)
        state.stage[-1] = tide(t)

        # Height update
        update_height_masked(state, mesh)

        # Fluxes
        dU = compute_fluxes_loop(mesh, state, dt)

        # Bed slope
        sf = bed_slope_force(mesh, state)

        # Update stage
        state.stage += dU + sf * dt

        # Enforce non-negative depth
        state.height[:] = np.maximum(state.stage - mesh.bed_elev, 0.0)

    return state.stage


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Shallow water solver — PerfLens example")
    parser.add_argument("--ncells", type=int, default=5000)
    parser.add_argument("--nsteps", type=int, default=20)
    args = parser.parse_args()

    t0  = time.perf_counter()
    out = run(ncells=args.ncells, nsteps=args.nsteps)
    dt  = time.perf_counter() - t0

    print(f"ncells={args.ncells}  nsteps={args.nsteps}")
    print(f"Elapsed: {dt*1000:.1f} ms")
    print(f"Max stage:  {out.max():.4f}")
    print(f"Mean stage: {out.mean():.6f}")
