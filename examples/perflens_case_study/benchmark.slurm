#!/bin/bash
#SBATCH --job-name=perflens-bench
#SBATCH --partition=small
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --time=00:45:00
#SBATCH --output=benchmark_%j.out
#SBATCH --error=benchmark_%j.err

set -euo pipefail

ROOT="$HOME/perflens_work/source/perflens/examples/perflens_case_study"
BIN="$ROOT/build_corrected/heat_solver"
OUT="$ROOT/benchmark_results_${SLURM_JOB_ID}.csv"

cd "$ROOT"

export OMP_DYNAMIC=FALSE
export OMP_PROC_BIND=close
export OMP_PLACES=cores

echo "Hostname: $(hostname)"
echo "Date: $(date)"
echo "CPUs allocated: $SLURM_CPUS_PER_TASK"
lscpu | grep -E 'Model name|Socket|Core|Thread|CPU\(s\)' | head -8

echo "mode,threads,grid,steps,repeat,runtime,checksum,centre" > "$OUT"

run_case() {
    local mode="$1"
    local threads="$2"
    local n="$3"
    local steps="$4"
    local repeat="$5"

    local result
    result=$(OMP_NUM_THREADS="$threads" "$BIN" \
        --mode "$mode" "$n" "$n" "$steps")

    local runtime checksum centre
    runtime=$(echo "$result" | awk '/Runtime:/ {print $2}')
    checksum=$(echo "$result" | awk '/Checksum:/ {print $2}')
    centre=$(echo "$result" | awk '/Centre:/ {print $2}')

    echo "$mode,$threads,$n,$steps,$repeat,$runtime,$checksum,$centre" >> "$OUT"
}

# Grid and step combinations
for spec in "256 1000" "512 500" "1024 200" "2048 100"; do
    read -r n steps <<< "$spec"

    echo "Benchmarking ${n}x${n}, steps=$steps"

    # Serial
    run_case serial 1 "$n" "$steps" 0
    for r in $(seq 1 7); do
        run_case serial 1 "$n" "$steps" "$r"
    done

    # OpenMP: 1, 2, 4 and 8 threads
    for t in 1 2 4 8; do
        run_case openmp "$t" "$n" "$steps" 0
        for r in $(seq 1 7); do
            run_case openmp "$t" "$n" "$steps" "$r"
        done
    done

    # Tiled
    run_case tiled 1 "$n" "$steps" 0
    for r in $(seq 1 7); do
        run_case tiled 1 "$n" "$steps" "$r"
    done
done

echo "Benchmark complete."
echo "CSV: $OUT"
echo "Rows: $(($(wc -l < "$OUT") - 1))"
