#!/usr/bin/env bash
# benchmark_run.sh — Run a PerfLens optimization cycle and record timings
#
# Usage:
#   ./scripts/benchmark_run.sh <source_file> [hw_profile] [iterations]
#
# Environment variables:
#   ANTHROPIC_API_KEY   — required for LLM optimizer
#   PERFLENS_HW         — hardware profile override (default: auto)
#   PERFLENS_ITERS      — max optimization iterations (default: 3)
#   VTUNE_REPORT        — path to VTune CSV report (optional)
#   RESULTS_DIR         — output directory (default: ./perflens_results)

set -euo pipefail

# ── Argument handling ─────────────────────────────────────────────────────────
SOURCE="${1:-}"
if [[ -z "$SOURCE" ]]; then
    echo "Usage: $0 <source_file> [hw_profile] [iterations]" >&2
    exit 1
fi
HW="${2:-${PERFLENS_HW:-auto}}"
ITERS="${3:-${PERFLENS_ITERS:-3}}"
RESULTS_DIR="${RESULTS_DIR:-./perflens_results}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BASENAME=$(basename "$SOURCE" | sed 's/\.[^.]*$//')

# ── Setup ─────────────────────────────────────────────────────────────────────
mkdir -p "$RESULTS_DIR/$BASENAME/$TIMESTAMP"
LOG="$RESULTS_DIR/$BASENAME/$TIMESTAMP/perflens.log"

echo "============================================================" | tee -a "$LOG"
echo " PerfLens Benchmark Runner" | tee -a "$LOG"
echo " Source  : $SOURCE" | tee -a "$LOG"
echo " HW      : $HW" | tee -a "$LOG"
echo " Iters   : $ITERS" | tee -a "$LOG"
echo " Results : $RESULTS_DIR/$BASENAME/$TIMESTAMP" | tee -a "$LOG"
echo " Time    : $(date)" | tee -a "$LOG"
echo "============================================================" | tee -a "$LOG"

# ── Check dependencies ────────────────────────────────────────────────────────
check_cmd() {
    if ! command -v "$1" &>/dev/null; then
        echo "WARNING: '$1' not found — some features may be limited" | tee -a "$LOG"
    fi
}
check_cmd perflens
check_cmd python3
check_cmd gcc
check_cmd gfortran

if [[ -z "${ANTHROPIC_API_KEY:-}" ]]; then
    echo "ERROR: ANTHROPIC_API_KEY not set. Export it before running." | tee -a "$LOG"
    exit 1
fi

# ── Step 1: Static scan ───────────────────────────────────────────────────────
SCAN_OUTPUT="$RESULTS_DIR/$BASENAME/$TIMESTAMP/scan.json"
echo "" | tee -a "$LOG"
echo "[1/4] Running static scan..." | tee -a "$LOG"
perflens scan "$SOURCE" --output "$SCAN_OUTPUT" 2>&1 | tee -a "$LOG" || true

NFINDINGS=$(python3 -c "import json; d=json.load(open('$SCAN_OUTPUT')); print(len(d))" 2>/dev/null || echo "?")
echo "      Findings: $NFINDINGS" | tee -a "$LOG"

# ── Step 2: Baseline benchmark ────────────────────────────────────────────────
echo "" | tee -a "$LOG"
echo "[2/4] Running baseline benchmark..." | tee -a "$LOG"
EXT="${SOURCE##*.}"
BASELINE_TIME=""

case "$EXT" in
    py)
        BASELINE_TIME=$(python3 -c "
import time, importlib.util, sys
spec = importlib.util.spec_from_file_location('m', '$SOURCE')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
if hasattr(m, 'run'):
    t0 = time.perf_counter()
    m.run()
    print(f'{(time.perf_counter()-t0)*1000:.2f}')
else:
    print('N/A')
" 2>/dev/null || echo "N/A")
        ;;
    c|cpp|cxx)
        TMPBIN="/tmp/perflens_baseline_$$"
        COMPILER="gcc"
        [[ "$EXT" == "cpp" || "$EXT" == "cxx" ]] && COMPILER="g++"
        if $COMPILER -O2 -fopenmp -lm "$SOURCE" -o "$TMPBIN" 2>/dev/null; then
            BASELINE_TIME=$((/usr/bin/time -f "%e" "$TMPBIN" 2>&1 | tail -1) || echo "N/A")
            rm -f "$TMPBIN"
        fi
        ;;
    f90|f|for|f95|f03|f08)
        TMPBIN="/tmp/perflens_baseline_$$"
        if gfortran -O2 -fopenmp "$SOURCE" -o "$TMPBIN" 2>/dev/null; then
            BASELINE_TIME=$((/usr/bin/time -f "%e" "$TMPBIN" 2>&1 | tail -1) || echo "N/A")
            rm -f "$TMPBIN"
        fi
        ;;
esac

echo "      Baseline time: ${BASELINE_TIME} ms/s" | tee -a "$LOG"

# ── Step 3: LLM optimization ──────────────────────────────────────────────────
echo "" | tee -a "$LOG"
echo "[3/4] Running LLM optimization ($ITERS iterations)..." | tee -a "$LOG"

OPT_ARGS="$SOURCE --hw $HW --iterations $ITERS"
[[ -n "${VTUNE_REPORT:-}" ]] && OPT_ARGS="$OPT_ARGS --profile $VTUNE_REPORT"

perflens optimize $OPT_ARGS 2>&1 | tee -a "$LOG" || {
    echo "Optimizer returned non-zero exit — check log" | tee -a "$LOG"
}

# ── Step 4: Collect optimized files and benchmark them ───────────────────────
echo "" | tee -a "$LOG"
echo "[4/4] Benchmarking optimized variants..." | tee -a "$LOG"

SUMMARY_CSV="$RESULTS_DIR/$BASENAME/$TIMESTAMP/summary.csv"
echo "label,source,runtime_ms,speedup" > "$SUMMARY_CSV"
echo "baseline,$SOURCE,$BASELINE_TIME,1.0" >> "$SUMMARY_CSV"

for OPT_FILE in ${BASENAME}_optimized_iter*.${EXT} 2>/dev/null; do
    [[ -f "$OPT_FILE" ]] || continue
    ITER=$(echo "$OPT_FILE" | grep -oP 'iter\d+')
    OPT_TIME=""

    case "$EXT" in
        py)
            OPT_TIME=$(python3 -c "
import time, importlib.util
spec = importlib.util.spec_from_file_location('m', '$OPT_FILE')
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
if hasattr(m, 'run'):
    t0 = time.perf_counter()
    m.run()
    print(f'{(time.perf_counter()-t0)*1000:.2f}')
" 2>/dev/null || echo "N/A")
            ;;
    esac

    SPEEDUP="N/A"
    if [[ "$BASELINE_TIME" != "N/A" && "$OPT_TIME" != "N/A" && -n "$OPT_TIME" ]]; then
        SPEEDUP=$(python3 -c "print(f'{float($BASELINE_TIME)/float($OPT_TIME):.3f}')" 2>/dev/null || echo "N/A")
    fi

    echo "$ITER,$OPT_FILE,$OPT_TIME,$SPEEDUP" >> "$SUMMARY_CSV"
    echo "      $ITER: ${OPT_TIME}ms  speedup=${SPEEDUP}×" | tee -a "$LOG"

    # Move to results dir
    mv -f "$OPT_FILE" "$RESULTS_DIR/$BASENAME/$TIMESTAMP/" 2>/dev/null || true
done

# ── Done ─────────────────────────────────────────────────────────────────────
echo "" | tee -a "$LOG"
echo "============================================================" | tee -a "$LOG"
echo " Done. Results: $RESULTS_DIR/$BASENAME/$TIMESTAMP/" | tee -a "$LOG"
echo " Summary CSV : $SUMMARY_CSV" | tee -a "$LOG"
echo " Launch dashboard: perflens dashboard --port 8080" | tee -a "$LOG"
echo "============================================================" | tee -a "$LOG"
