# Getting Started with PerfLens

This guide gets you from zero to optimizing HPC code in under 10 minutes,
with no API key required.

---

## 1. Install

```bash
git clone https://github.com/samcom12/perflens
cd perflens
pip install -e .
```

Verify:
```bash
perflens --version    # perflens 0.3.0
perflens hw detect    # shows your detected hardware
perflens backends     # shows available optimization backends
```

---

## 2. Optimise a single file (zero key)

```bash
# Scan for anti-patterns
perflens scan examples/c/stencil.c

# Apply rule-based transformations (no LLM needed)
perflens optimize examples/c/stencil.c --backend rules --hw intel_spr

# Check what changed
diff examples/c/stencil.c examples/c/stencil_optimized_iter0.c
```

**What the rule engine applies to `stencil.c`:**
- `#pragma omp parallel for` on the outer loop
- `#pragma omp simd` on the inner loop
- Division `/ norm` → reciprocal `* inv_norm` before the loop

---

## 3. Optimise a whole project

```bash
# Crawl the example project and see its structure
perflens project scan examples/project_hello --deps

# Run the full pipeline (no build, no LLM, no key)
perflens project optimize examples/project_hello \
    --backend rules \
    --no-build \
    --hw a100

# Review all the diffs
perflens project diff examples/project_hello

# Apply patches back to the source tree
perflens project optimize examples/project_hello \
    --backend rules --no-build --apply
```

**What the pipeline does automatically:**
1. Discovers `flux.c`, `solver.c`, `io.c` and parses `#include` links
2. Collects GCC `-fopt-info` missed-vectorization reports
3. Scans each file in parallel (ThreadPoolExecutor)
4. Scores files by hotspot% + compiler misses + scanner severity
5. Applies rules to highest-priority files first
6. Compile-validates each patch before keeping it

---

## 4. Add Ollama for richer transforms (no key)

```bash
# Install Ollama once
curl -fsSL https://ollama.com/install.sh | sh
ollama pull codellama:34b          # best for C/C++/Fortran

# Optimize with the local LLM
perflens optimize examples/c/stencil.c \
    --backend ollama:codellama:34b \
    --hw a100

# Or for the whole project
perflens project optimize examples/project_hello \
    --backend ollama \
    --no-build \
    --top-n 3
```

---

## 5. Collect compiler optimization feedback

```bash
# GCC live compile + collect feedback
perflens compiler examples/c/stencil.c --compiler gcc

# Or parse an existing log file
gcc -O3 -fopt-info-vec-missed examples/c/stencil.c -c 2> gcc.log
perflens compiler examples/c/stencil.c --report gcc.log

# Combine with optimization (--compiler-feedback flag)
perflens optimize examples/c/stencil.c \
    --backend rules \
    --compiler-feedback
```

---

## 6. Empirically tune tile sizes

```bash
# First apply loop tiling (inserts #define TILE N)
perflens optimize examples/c/stencil.c --backend rules

# Then sweep tile sizes on real hardware
perflens autotune examples/c/stencil_optimized_iter0.c \
    --param tile \
    --tiles 8,16,32,64,128 \
    --output tile_result.json
```

---

## 7. Launch the benchmark dashboard

```bash
perflens dashboard --port 8080
# Open http://localhost:8080
```

The dashboard shows:
- Runtime timeline across optimization iterations
- Speedup bar chart per run
- Roofline model chart
- Top hotspot flame chart
- Live backend availability status

---

## 8. Use with VTune profiler data

```bash
# Profile your binary
vtune -collect hotspots -result-dir vtune_r001 -- ./build/solver
vtune -report hotspots -r vtune_r001 -format csv -report-output hotspots.csv

# Feed into PerfLens
perflens optimize src/solver.c \
    --backend rules \
    --profile hotspots.csv \
    --hw a100
```

---

## Command Reference

```
perflens scan     <file>              Static analysis
perflens profile  <file>              Parse VTune/HPCToolkit report
perflens optimize <file>              Single-file optimization pipeline
perflens validate <orig> <patched>    Validate a patch
perflens backends                     List available backends
perflens compiler <file>              Compiler optimization feedback
perflens autotune <file>              Empirical tile/thread tuning
perflens dashboard                    Benchmark web dashboard
perflens hw list|detect|show          Hardware database

perflens project scan     <dir>       Crawl project
perflens project build    <dir>       Build + collect compiler reports
perflens project optimize <dir>       Full project pipeline
perflens project status   <dir>       Show patch status
perflens project diff     <dir>       Unified diff of all patches
```

Full documentation: [docs/architecture.md](architecture.md) | [docs/no_api_key_guide.md](no_api_key_guide.md)
