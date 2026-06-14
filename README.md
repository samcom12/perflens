# 🔬 PerfLens

**Automated HPC Code Optimization Framework**

PerfLens is an end-to-end automation framework that statically analyzes, profiles, transforms, validates, and benchmarks C, C++, Fortran, and Python HPC codebases — with an LLM-driven optimization engine at its core.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        PerfLens Pipeline                         │
│                                                                   │
│  Source Code                                                      │
│      │                                                            │
│      ▼                                                            │
│  ┌─────────┐    ┌──────────┐    ┌──────────────┐                 │
│  │ Scanner │───▶│ Profiler │───▶│  HW Database │                 │
│  │ (Clang/ │    │(VTune /  │    │  (A100,V100, │                 │
│  │  LLVM)  │    │HPCToolkit│    │  Intel Xeon…)│                 │
│  └────┬────┘    └────┬─────┘    └──────┬───────┘                 │
│       │              │                  │                         │
│       └──────────────▼──────────────────┘                        │
│                       │                                           │
│               ┌───────▼────────┐                                  │
│               │  LLM Optimizer │  ◀── Anthropic Claude API        │
│               │  (Transform    │                                   │
│               │   Engine)      │                                   │
│               └───────┬────────┘                                  │
│                        │                                           │
│               ┌────────▼───────┐                                  │
│               │ Patch Validator│  (compile + test + diff)         │
│               └────────┬───────┘                                  │
│                        │                                           │
│               ┌────────▼───────┐                                  │
│               │   Benchmark    │  (Plotly dashboard)              │
│               │   Dashboard    │                                   │
│               └────────────────┘                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## Modules

| Module | Description |
|--------|-------------|
| `perflens.scanner` | Clang AST / libclang static analysis — loop patterns, memory access, vectorization hints, OpenMP/MPI idioms |
| `perflens.profiler` | VTune XML/CSV and HPCToolkit database parsers — hotspot extraction, roofline data |
| `perflens.hardware` | Hardware capability database — cache hierarchy, SIMD width, memory bandwidth, GPU SM counts, roofline peaks |
| `perflens.optimizer.rules` | **Zero-LLM rule engine** — 14 source-level transforms for C/C++/Python/Fortran; no key required |
| `perflens.optimizer.backends` | Multi-backend system: `rules` \| `ollama` \| `lmstudio` \| `llamacpp` \| `vllm` \| `groq` \| `anthropic` |
| `perflens.optimizer` | Backend-agnostic optimization engine — iterative, multi-round |
| `perflens.compiler_feedback` | GCC `-fopt-info`, Clang `-Rpass`, ICX `.optrpt` parsers — missed vectorizations, aliasing |
| `perflens.autotuner` | Empirical tile size and thread count sweep — compile + run + compare |
| `perflens.validator` | Automatic patch validator — compile check, test harness, numerical diff, regression gate |
| `perflens.dashboard` | FastAPI + Plotly benchmark dashboard — runtime charts, roofline, backend status panel |
| `perflens.pipeline` | Orchestrator that wires all modules into a single `perflens optimize` CLI run |

---

## Whole-Project Optimization

For large HPC codebases with many files:

```bash
# Discover files and dependencies
perflens project scan ./my_solver --deps

# Build + auto-collect compiler optimization reports
perflens project build ./my_solver --hw a100

# Full pipeline — rule engine, zero API key
perflens project optimize ./my_solver --backend rules --hw a100

# Review diffs before applying
perflens project diff ./my_solver

# Apply validated patches back to source tree
perflens project optimize ./my_solver --backend rules --apply
```

The project pipeline runs 7 steps automatically:
**Crawl → Build+CompilerReports → Profile → Scan → Plan → Optimize → Validate**

Files are prioritized by a combined score: `60% hotspot CPU% + 25% compiler missed vectorizations + 15% scanner severity`.

## Single-File Optimization — No API Key Needed



```bash
# Install
git clone https://github.com/samcom12/perflens && cd perflens
pip install -e .

# Option A: Rule engine — zero LLM, fully offline
perflens optimize examples/c/stencil.c --backend rules --hw a100
perflens optimize examples/python/heat_solver.py --backend rules

# Option B: Local Ollama (pull a model once)
ollama pull codellama:34b
perflens optimize examples/c/stencil.c --backend ollama

# Option C: Groq free tier (fast, only needs GROQ_API_KEY)
export GROQ_API_KEY=gsk_...
perflens optimize examples/c/stencil.c --backend groq

# Option D: Anthropic Claude (highest quality)
export ANTHROPIC_API_KEY=sk-ant-...
perflens optimize examples/c/stencil.c --backend anthropic --hw a100

# See which backends are ready on your machine
perflens backends

# Auto-tune tile sizes empirically (no key) — tiling fires on nested loops:
perflens optimize examples/cpp/matmul.cpp --backend rules --output /tmp/matmul_tiled.cpp
perflens autotune /tmp/matmul_tiled.cpp --param tile

# Collect compiler missed-vectorization feedback (no key)
perflens compiler examples/c/stencil.c --compiler gcc

# Launch benchmark dashboard
perflens dashboard --port 8080
```

---

## Installation

```bash
git clone https://github.com/samcom12/perflens.git
cd perflens
pip install -e ".[dev]"

# Optional: install libclang for full AST scanning
apt-get install clang libclang-dev   # Ubuntu/Debian
# or
pip install libclang
```

### Environment Variables

```bash
export ANTHROPIC_API_KEY=sk-ant-...   # Required for LLM optimizer
export PERFLENS_HW_PROFILE=a100       # Default hardware target
export PERFLENS_LOG_LEVEL=INFO
```

---

## Supported Languages

| Language | Scanner | Optimizer | Validator |
|----------|---------|-----------|-----------|
| C        | ✅ libclang AST | ✅ | ✅ gcc/clang compile |
| C++      | ✅ libclang AST | ✅ | ✅ g++/clang++ compile |
| Fortran  | ✅ regex + fparser2 | ✅ | ✅ gfortran compile |
| Python   | ✅ ast module | ✅ | ✅ pytest harness |

---

## Supported Hardware Profiles

| Profile ID | Hardware | SIMD | Peak FLOP/s | Mem BW |
|-----------|----------|------|-------------|--------|
| `a100` | NVIDIA A100 80GB | CUDA | 77.6 TF (bf16) | 2 TB/s |
| `v100` | NVIDIA V100 32GB | CUDA | 14 TF (fp32) | 900 GB/s |
| `h100` | NVIDIA H100 80GB | CUDA | 133.8 TF (bf16) | 3.35 TB/s |
| `intel_spr` | Intel Sapphire Rapids | AVX-512 | ~6.7 TF/socket | 307 GB/s |
| `amd_genoa` | AMD EPYC Genoa | AVX-512 | ~6.1 TF/socket | 460 GB/s |
| `a64fx` | Fujitsu A64FX | SVE-512 | 3.07 TF | 1 TB/s |

---

## Roadmap

- [x] Multi-backend system (rules / Ollama / LM Studio / Groq / Anthropic)
- [x] Zero-API-key rule engine (14 transforms, 4 languages)
- [x] GCC / Clang / ICX compiler feedback parsers
- [x] Empirical auto-tuner (tile size + thread count)
- [x] Whole-project pipeline (crawl → build → profile → scan → optimize → validate)
- [x] Build system integration (CMake / Make / Meson / bare)
- [x] Dependency graph analysis + topological optimization order
- [x] Benchmark dashboard (FastAPI + Plotly)
- [ ] LLVM IR-level analysis pass
- [ ] Polyhedral model integration (Pluto / isl)
- [ ] AMD MI300X hardware profile
- [ ] MLIR codegen backend
- [ ] OpenTuner parameter sweep integration
- [ ] Persistent optimization history across runs

---

## License

MIT License © 2025 Samir — [samcom12](https://github.com/samcom12)
