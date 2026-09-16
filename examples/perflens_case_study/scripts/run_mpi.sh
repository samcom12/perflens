#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

RANKS="${1:-2}"
NX="${2:-128}"
NY="${3:-128}"
STEPS="${4:-20}"

exec mpirun -np "$RANKS" "$ROOT/build/heat_solver_mpi" \
    "$NX" "$NY" "$STEPS"
