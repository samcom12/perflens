#!/usr/bin/env bash
# vtune_profile.sh — Collect a VTune Hotspot + Memory Access report and export to CSV
#
# Usage:
#   ./scripts/vtune_profile.sh <binary> [args...]
#
# Output:
#   vtune_results/r<N>hs/hotspots.csv
#   vtune_results/r<N>hs/memory_access.csv
#
# Requires: Intel VTune Profiler (vtune command in PATH)

set -euo pipefail

BINARY="${1:-}"
if [[ -z "$BINARY" || ! -x "$BINARY" ]]; then
    echo "Usage: $0 <executable> [args...]" >&2
    echo "Example: $0 ./solver 1024 200" >&2
    exit 1
fi
shift
ARGS=("$@")

# ── Sanity checks ─────────────────────────────────────────────────────────────
if ! command -v vtune &>/dev/null; then
    echo "ERROR: vtune not found. Source the Intel oneAPI environment:" >&2
    echo "  source /opt/intel/oneapi/setvars.sh" >&2
    exit 1
fi

RESULTS_BASE="vtune_results"
mkdir -p "$RESULTS_BASE"

# Find next available result number
N=1
while [[ -d "$RESULTS_BASE/r$(printf '%03d' $N)hs" ]]; do
    N=$((N+1))
done
RESULT_ID="r$(printf '%03d' $N)hs"
RESULT_DIR="$RESULTS_BASE/$RESULT_ID"

echo "============================================================"
echo " VTune Profiling"
echo " Binary  : $BINARY ${ARGS[*]:-}"
echo " Result  : $RESULT_DIR"
echo "============================================================"

# ── Step 1: Hotspot analysis ──────────────────────────────────────────────────
echo ""
echo "[1/3] Collecting Hotspot profile..."
vtune \
    -collect hotspots \
    -knob sampling-mode=hw \
    -knob enable-stack-collection=false \
    -result-dir "$RESULT_DIR" \
    -- "$BINARY" "${ARGS[@]}"

# ── Step 2: Export hotspot CSV ────────────────────────────────────────────────
echo ""
echo "[2/3] Exporting hotspot CSV..."
vtune \
    -report hotspots \
    -r "$RESULT_DIR" \
    -format csv \
    -csv-delimiter comma \
    -report-output "$RESULT_DIR/hotspots.csv"

echo "      Written: $RESULT_DIR/hotspots.csv"

# ── Step 3: Memory access analysis (optional) ─────────────────────────────────
echo ""
echo "[3/3] Collecting Memory Access profile..."
MEMORY_DIR="${RESULT_DIR}_mem"
vtune \
    -collect memory-access \
    -result-dir "$MEMORY_DIR" \
    -- "$BINARY" "${ARGS[@]}" 2>/dev/null || {
    echo "      (memory-access collection skipped — may need root or /proc/sys/kernel/perf_event_paranoid=0)"
}

if [[ -d "$MEMORY_DIR" ]]; then
    vtune \
        -report hotspots \
        -r "$MEMORY_DIR" \
        -format csv \
        -csv-delimiter comma \
        -report-output "$RESULT_DIR/memory_access.csv" 2>/dev/null || true
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo " Profile collected: $RESULT_DIR"
echo ""
echo " To run PerfLens with this profile:"
echo "   perflens optimize <source.c> \\"
echo "       --hw auto \\"
echo "       --profile $RESULT_DIR/hotspots.csv"
echo "============================================================"
