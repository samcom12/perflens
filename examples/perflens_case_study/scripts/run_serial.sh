#!/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

NX="${1:-128}"
NY="${2:-128}"
STEPS="${3:-20}"

exec "$ROOT/build/heat_solver" "$NX" "$NY" "$STEPS"
