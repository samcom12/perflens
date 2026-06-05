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

## Quickstart — No API Key Needed

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

# Auto-tune tile sizes empirically (no key)
perflens autotune examples/c/stencil_optimized_iter0.c --param tile

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

- [ ] LLVM IR-level analysis pass
- [ ] Polyhedral model integration (isl / Pluto)
- [ ] Auto-tuning parameter sweep (OpenTuner integration)
- [ ] MLIR codegen backend
- [ ] CI/CD GitHub Actions workflow template
- [ ] Roofline model auto-generation from hardware profiles

---

## License

MIT License © 2025 Samir — [samcom12](https://github.com/samcom12)
