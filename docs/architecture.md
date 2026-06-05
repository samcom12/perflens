# PerfLens Architecture

## Overview

PerfLens is a seven-layer HPC code optimization pipeline. Every layer is
independently usable via CLI or Python API. **No API key is required** —
the rule-based engine optimizes code entirely offline.

```
Source Code  (C / C++ / Fortran / Python)
        │
        ▼
┌──────────────────────────────────────────────────────────┐
│  Layer 1 · Scanner  (perflens.scanner)                   │
│  C/C++: libclang AST walk + regex                        │
│  Fortran: fparser2 AST + line regex                      │
│  Python: ast.NodeVisitor + pandas/numpy heuristics       │
│  → List[Finding] (kind, severity, location, suggestion)  │
└──────────────────────┬───────────────────────────────────┘
                       │
        ┌──────────────▼──────────────┐
        │  Layer 2 · Profiler         │  ← optional
        │  VTune CSV/XML parser       │
        │  HPCToolkit experiment.xml  │
        │  → ProfileData (hotspots,   │
        │    roofline points)         │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │  Layer 3 · Compiler Feedback│  ← optional
        │  GCC  -fopt-info            │
        │  Clang -Rpass               │
        │  ICX  .optrpt               │
        │  → CompilerFeedbackReport   │
        │    (missed vectorizations,  │
        │     aliasing failures)      │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │  Layer 4 · Hardware DB      │
        │  9 built-in profiles        │
        │  (A100/H100/V100, SPR/ICX,  │
        │   Genoa/Milan, A64FX,       │
        │   Graviton3)                │
        │  Auto-detect via nvidia-smi │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────────────────────────┐
        │  Layer 5 · Optimizer  (perflens.optimizer)       │
        │                                                  │
        │  ┌─────────────────────────────────────────┐     │
        │  │  Backend Registry                       │     │
        │  │  rules      → RuleEngine (NO LLM) ✓    │     │
        │  │  ollama     → Local Ollama server  ✓    │     │
        │  │  lmstudio   → LM Studio local     ✓    │     │
        │  │  llamacpp   → llama.cpp server    ✓    │     │
        │  │  vllm       → vLLM local          ✓    │     │
        │  │  groq       → Groq cloud (free)   ✓    │     │
        │  │  openrouter → OpenRouter           ~    │     │
        │  │  anthropic  → Claude API           *    │     │
        │  │  ✓=no key  ~=free tier  *=paid         │     │
        │  └─────────────────────────────────────────┘     │
        │                                                  │
        │  Rule Engine  (zero-LLM path):                   │
        │   C/C++:  loop_tiling, openmp_parallel,          │
        │            openmp_simd, openmp_offload,           │
        │            mpi_nonblocking, division_hoist        │
        │   Python: scalar_math→numpy, preallocate,         │
        │            numba_annotate, pandas_vectorise       │
        │   Fortran: implicit_none, openmp_do,              │
        │             openmp_simd, mpi_nonblocking           │
        │                                                  │
        │  LLM path: structured prompt → JSON patches      │
        │            → optimized source                    │
        └──────────────┬───────────────────────────────────┘
                       │
        ┌──────────────▼──────────────┐
        │  Layer 6 · Auto-Tuner       │  ← optional
        │  Tile size sweep            │
        │  Thread count sweep         │
        │  Compile + time + compare   │
        │  → TuneResult (best params) │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │  Layer 7 · Validator        │
        │  Compile check              │
        │  pytest / ctest runner      │
        │  Numerical diff (run())     │
        │  Diff sanity gate           │
        │  → ValidationReport         │
        └──────────────┬──────────────┘
                       │
        ┌──────────────▼──────────────┐
        │  Layer 8 · Dashboard        │
        │  FastAPI REST API           │
        │  SQLite persistence         │
        │  Plotly: timeline, speedup, │
        │  roofline, hotspot flame,   │
        │  backend status panel       │
        └─────────────────────────────┘
```

---

## Module Map

```
perflens/
├── cli.py                          Typer CLI (scan/profile/optimize/validate/
│                                   dashboard/backends/autotune/compiler/hw)
├── scanner/
│   ├── models.py                   Finding, FindingKind, Severity
│   ├── dispatcher.py               Language routing
│   ├── clang_scanner.py            libclang AST + regex (C/C++)
│   ├── fortran_scanner.py          fparser2 + line regex
│   ├── python_scanner.py           ast.NodeVisitor
│   └── report.py                   Rich terminal output
├── profiler/
│   ├── models.py                   ProfileData, Hotspot, RooflinePoint
│   ├── dispatcher.py               Tool routing
│   ├── vtune_parser.py             VTune CSV+XML (2021–2024 column aliases)
│   └── hpctoolkit_parser.py        HPCToolkit experiment.xml + CSV
├── hardware/
│   ├── models.py                   HardwareProfile, GPU/SIMD capability
│   ├── database.py                 9 built-in profiles
│   └── detector.py                 nvidia-smi + /proc/cpuinfo
├── optimizer/
│   ├── backends/
│   │   ├── base.py                 LLMBackend ABC + BackendCapabilities
│   │   ├── anthropic_backend.py    Claude API (needs ANTHROPIC_API_KEY)
│   │   ├── ollama_backend.py       Local Ollama (no key, /api/chat)
│   │   ├── openai_compat_backend.py  vLLM/LM Studio/Groq/Together/…
│   │   └── registry.py            create_backend() + list_backends()
│   ├── rules/
│   │   ├── base_rule.py            TransformRule ABC + RuleContext
│   │   ├── c_rules.py              6 C/C++ rules
│   │   ├── python_rules.py         4 Python rules
│   │   ├── fortran_rules.py        4 Fortran rules
│   │   └── rule_engine.py          RuleEngine + RuleEngineBackend shim
│   ├── engine.py                   OptimizationEngine (backend-agnostic)
│   ├── models.py                   Patch, TransformKind, OptimizationResult
│   └── prompt_builder.py           Structured LLM prompt construction
├── compiler_feedback/
│   ├── __init__.py                 collect_feedback() dispatcher
│   ├── models.py                   CompilerFeedbackReport, CompilerRemark
│   ├── gcc_parser.py               GCC -fopt-info parser
│   └── clang_parser.py             Clang -Rpass + ICX .optrpt parser
├── autotuner/
│   ├── __init__.py
│   └── tile_tuner.py               TileSearchTuner + thread sweep
├── validator/
│   ├── models.py                   ValidationReport, CheckResult
│   └── checker.py                  Compile/test/diff/sanity checks
├── dashboard/
│   └── app.py                      FastAPI + Plotly + backend status panel
└── pipeline/
    └── orchestrator.py             PerfLensPipeline (all layers wired)
```

---

## Backend Selection Guide

| Backend | Key needed | Model | Best for |
|---------|-----------|-------|----------|
| `rules` | ❌ None | n/a | Fast, safe, offline, all HPC patterns |
| `ollama` | ❌ None | codellama:34b | Best local quality for C/Fortran |
| `ollama:llama3:8b` | ❌ None | llama3:8b | Fast local, good Python |
| `lmstudio` | ❌ None | any | GUI-friendly local server |
| `llamacpp` | ❌ None | GGUF models | Low-RAM local inference |
| `vllm` | ❌ None | any HF model | GPU-accelerated local |
| `groq` | `GROQ_API_KEY` | llama3-70b | Free tier, very fast |
| `openrouter` | `OPENROUTER_API_KEY` | any | Free tier for many models |
| `anthropic` | `ANTHROPIC_API_KEY` | claude-opus-4-5 | Highest quality |

### Recommended models per language

| Language | Recommended | Notes |
|----------|-------------|-------|
| C/C++ | `codellama:34b` or `deepseek-coder:33b` | Best for low-level optimizations |
| Fortran | `codellama:34b` | Trained on Fortran scientific codes |
| Python | `llama3:70b` or `qwen2.5-coder:32b` | Strong NumPy/Numba reasoning |
| Mixed | `deepseek-coder:33b` | Balanced across all languages |

---

## Rule Engine — Zero-LLM Path

The rule engine applies deterministic, safe source-level transformations:

### C/C++ Rules (6)
| Rule | What it does | Expected speedup |
|------|-------------|-----------------|
| `loop_tiling` | Tile triple-nested loops; tile size from L1 cache | 2–8× |
| `openmp_parallel` | `#pragma omp parallel for` on outer loops | up to N_cores× |
| `openmp_simd` | `#pragma omp simd` on inner loops | 2–8× |
| `openmp_offload` | `#pragma omp target teams distribute` (GPU clusters) | 5–50× |
| `mpi_nonblocking` | `MPI_Send/Recv` → `MPI_Isend/Irecv + MPI_Waitall` | 1.3–3× |
| `division_hoist` | Hoist `/x` → `inv_x = 1.0/x` before loop | 1.2–3× |

### Python Rules (4)
| Rule | What it does | Expected speedup |
|------|-------------|-----------------|
| `scalar_math_to_numpy` | `math.sin(x)` → `np.sin(x)` | 2–10× on arrays |
| `preallocate_numpy` | Hoist `np.zeros` allocation before loop | 1.5–3× |
| `numba_annotate` | `@njit(parallel=True)` on hot functions | 10–100× |
| `pandas_vectorise` | Flag `.iterrows()`, insert vectorisation hints | 10–1000× |

### Fortran Rules (4)
| Rule | What it does | Expected speedup |
|------|-------------|-----------------|
| `implicit_none` | Insert `IMPLICIT NONE` | 1.0–1.3× (compiler quality) |
| `fortran_openmp_do` | `!$OMP PARALLEL DO` on DO loops | up to N_cores× |
| `fortran_omp_simd` | `!$OMP SIMD` on inner DO loops | 2–8× |
| `fortran_mpi_nonblocking` | `MPI_SEND/RECV` → non-blocking | 1.3–3× |

---

## Compiler Feedback Integration

```bash
# Collect GCC missed-vectorization report alongside optimization:
perflens optimize solver.c --backend rules --compiler-feedback

# Or pre-collect and feed in:
gcc -O3 -fopt-info-vec-missed solver.c -c 2> gcc.log
perflens compiler solver.c --report gcc.log

# ICX (Intel):
icx -O3 -qopt-report=5 -qopt-report-file=solver.optrpt solver.c
perflens compiler solver.c --compiler icx --report solver.optrpt
```

The parser extracts missed vectorizations, aliasing failures, and dependency
issues, then injects them as additional context into the optimizer prompt.

---

## Auto-Tuner

```bash
# First apply loop tiling (inserts #define TILE):
perflens optimize solver.c --backend rules

# Then sweep tile sizes empirically:
perflens autotune solver_optimized_iter0.c --param tile --tiles 8,16,32,64,128

# Sweep thread count:
perflens autotune solver.c --param threads --threads 1,2,4,8,16,32

# Output best config to JSON:
perflens autotune solver.c --output tune_result.json
```

---

## Extending PerfLens

### Add a new rule

```python
# perflens/optimizer/rules/c_rules.py

class PrefetchRule(TransformRule):
    supported_languages = {"c", "cpp"}

    @property
    def name(self) -> str:
        return "prefetch"

    @property
    def transform_kind(self) -> TransformKind:
        return TransformKind.PREFETCH

    def applies(self, ctx: RuleContext) -> bool:
        return ctx.language in self.supported_languages and ctx.hardware.l2_kb >= 512

    def apply(self, ctx: RuleContext) -> Optional[tuple[str, list[Patch]]]:
        # Insert __builtin_prefetch before inner loops
        ...
```

Then add it to `_load_all_rules()` in `rule_engine.py`.

### Add a new backend

```python
# perflens/optimizer/backends/my_backend.py

class MyBackend(LLMBackend):
    @property
    def capabilities(self) -> BackendCapabilities:
        return BackendCapabilities(
            name="my-backend", requires_api_key=False, local=True,
        )

    def generate(self, system, messages, max_tokens=4096) -> str:
        # Call your inference server
        ...
```

Then add a case to `create_backend()` in `registry.py`.

### Add a new hardware profile

```python
# perflens/hardware/database.py — inside _build_profiles()
profiles["mi300x"] = HardwareProfile(
    profile_id="mi300x",
    name="AMD Instinct MI300X",
    vendor="amd", arch="cdna3",
    ...
    gpu=GPUCapability(name="MI300X", arch="cdna3", sm_count=304, ...),
)
```
