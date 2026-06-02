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
| `perflens.profiler` | VTune XML/CSV and HPCToolkit database parsers — hotspot extraction, roofline data collection |
| `perflens.hardware` | Hardware capability database — cache hierarchy, SIMD width, memory bandwidth, GPU SM counts, roofline peaks |
| `perflens.optimizer` | LLM-powered code transformation engine — loop tiling, vectorization, OpenMP offload, memory layout changes |
| `perflens.validator` | Automatic patch validator — compile check, test harness execution, numerical diff, regression gate |
| `perflens.dashboard` | FastAPI + Plotly benchmark comparison dashboard — runtime charts, roofline plots, iteration history |
| `perflens.pipeline` | Orchestrator that wires all modules into a single `perflens optimize` CLI run |

---

## Quickstart

```bash
# Install
pip install -e ".[dev]"

# Detect hardware profile
perflens hw detect

# Scan a source file for optimization opportunities
perflens scan src/solver.c

# Full optimization pipeline (scan → profile → optimize → validate)
perflens optimize src/solver.c --hw a100 --profile vtune_report.csv

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
