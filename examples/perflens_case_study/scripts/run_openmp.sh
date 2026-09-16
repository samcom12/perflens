#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

THREADS="${OMP_NUM_THREADS:-4}"
NX="${1:-128}"
NY="${2:-128}"
STEPS="${3:-20}"

export OMP_NUM_THREADS="$THREADS"

exec "$ROOT/build/heat_solver" "$NX" "$NY" "$STEPS"
