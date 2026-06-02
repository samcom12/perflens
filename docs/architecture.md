# PerfLens Architecture

## Overview

PerfLens is structured as a six-layer pipeline, each layer independently usable via CLI or Python API.

```
Source Code (C/C++/Fortran/Python)
        │
        ▼
┌───────────────────────────────────────────────────────┐
│  Layer 1: Scanner (perflens.scanner)                  │
│  ─────────────────────────────────────────────────── │
│  • C/C++: libclang AST walk + regex patterns          │
│  • Fortran: fparser2 AST + line-level regex           │
│  • Python: ast module visitor + pandas/numpy checks   │
│  Output: List[Finding] (kind, severity, location,     │
│          message, suggestion)                         │
└───────────────────┬───────────────────────────────────┘
                    │
                    ▼
┌───────────────────────────────────────────────────────┐
│  Layer 2: Profiler (perflens.profiler)                │
│  ─────────────────────────────────────────────────── │
│  • VTune: CSV/XML parser (hotspots, TMA columns)      │
│  • HPCToolkit: experiment.xml + hpcproftt CSV         │
│  • Auto-discover result directories                   │
│  Output: ProfileData (hotspots, roofline points,      │
│          total_time_ms)                               │
└───────────────────┬───────────────────────────────────┘
                    │
                    ▼
┌───────────────────────────────────────────────────────┐
│  Layer 3: Hardware DB (perflens.hardware)             │
│  ─────────────────────────────────────────────────── │
│  • Static profiles: A100, H100, V100, Intel SPR/ICX,  │
│    AMD Genoa/Milan, A64FX, Graviton3                  │
│  • Auto-detect via nvidia-smi + /proc/cpuinfo         │
│  • Exposes: SIMD width, cache sizes, peak FLOP/s,     │
│    memory bandwidth, GPU SM count, recommended flags  │
└───────────────────┬───────────────────────────────────┘
                    │
                    ▼
┌───────────────────────────────────────────────────────┐
│  Layer 4: LLM Optimizer (perflens.optimizer)          │
│  ─────────────────────────────────────────────────── │
│  • Builds structured prompt from: source + findings   │
│    + hotspots + hardware profile                      │
│  • Calls Anthropic Claude API (claude-opus-4-5)       │
│  • Parses JSON patch list from response               │
│  • Extracts full rewritten source                     │
│  • Iterates up to N rounds (feeds output back in)     │
│  Output: List[OptimizationResult]                     │
└───────────────────┬───────────────────────────────────┘
                    │
                    ▼
┌───────────────────────────────────────────────────────┐
│  Layer 5: Validator (perflens.validator)              │
│  ─────────────────────────────────────────────────── │
│  • Compile check (gcc/g++/gfortran/py_compile)        │
│  • Test suite (pytest / ctest)                        │
│  • Numerical diff (run() → compare arrays ≤ tol)      │
│  • Diff sanity (>80% change = WARNING)                │
│  • Compiler warning analysis (undefined, overflow)    │
│  Output: ValidationReport (passed, checks[])         │
└───────────────────┬───────────────────────────────────┘
                    │
                    ▼
┌───────────────────────────────────────────────────────┐
│  Layer 6: Dashboard (perflens.dashboard)              │
│  ─────────────────────────────────────────────────── │
│  • FastAPI REST API (/api/runs, /api/chart/*)         │
│  • SQLite persistence (benchmark_run, hotspot,        │
│    roofline_point tables)                             │
│  • Plotly charts: timeline, speedup, roofline,        │
│    hotspot flame bar                                  │
│  • Single-page HTML dashboard (auto-refresh 30s)     │
└───────────────────────────────────────────────────────┘
```

---

## Module Map

```
perflens/
├── cli.py                        Typer CLI — top-level commands
├── scanner/
│   ├── models.py                 Finding, FindingKind, Severity
│   ├── dispatcher.py             Language routing (ext → scanner)
│   ├── clang_scanner.py          libclang AST + regex (C/C++)
│   ├── fortran_scanner.py        fparser2 + line regex (Fortran)
│   ├── python_scanner.py         ast.NodeVisitor (Python)
│   └── report.py                 Rich terminal output
├── profiler/
│   ├── models.py                 ProfileData, Hotspot, RooflinePoint
│   ├── dispatcher.py             Tool routing
│   ├── vtune_parser.py           VTune CSV + XML parser
│   └── hpctoolkit_parser.py      HPCToolkit experiment.xml + CSV
├── hardware/
│   ├── models.py                 HardwareProfile, GPU/SIMD capability
│   ├── database.py               Built-in profile registry
│   └── detector.py               nvidia-smi + /proc/cpuinfo detection
├── optimizer/
│   ├── models.py                 Patch, TransformKind, OptimizationResult
│   ├── prompt_builder.py         Structured Claude prompt construction
│   └── engine.py                 Iterative LLM optimization loop
├── validator/
│   ├── models.py                 ValidationReport, CheckResult, CheckStatus
│   └── checker.py                Compile / test / diff / sanity checks
├── dashboard/
│   └── app.py                    FastAPI app + Plotly chart builders
└── pipeline/
    └── orchestrator.py           PerfLensPipeline (wires all layers)
```

---

## Data Flow

```
Source.c
  └─► scan_file()                    → List[Finding]
        └─► ClangScanner.scan()         (libclang AST + regex)

  └─► VTuneParser.parse()            → ProfileData
        └─► .hotspots[0].cpu_time_pct   e.g. compute_flux 45.3%

  └─► HardwareDatabase.get("a100")   → HardwareProfile
        └─► .gpu.memory_bandwidth_gbs   2000 GB/s

  └─► build_optimization_prompt()    → messages (Anthropic API format)
        └─► Includes: source + findings + hotspots + hw

  └─► OptimizationEngine.optimize()  → List[OptimizationResult]
        └─► result.optimized_source     Full rewritten source

  └─► PatchValidator.validate()      → ValidationReport
        └─► .passed = True/False

  └─► Dashboard POST /api/runs       → SQLite record
        └─► GET /api/chart/speedup      Plotly bar chart
```

---

## Prompt Structure

The LLM receives a structured prompt with four sections:

1. **Hardware context** — CPU cores, SIMD, cache sizes, memory BW, GPU specs, recommended compiler flags
2. **Static findings** — top-N findings from the scanner (severity, location, message, suggestion)
3. **Profiler hotspots** — top-10 by CPU%, with CPI, LLC miss rate, memory bound %, vectorisation %
4. **Source code** — full file between code fences

The response is expected in:
```json
{
  "patches": [{ "transform_kind": "loop_tiling", "start_line": 42, ... }],
  "explanation": "..."
}
```
Followed by `<optimized_source>…</optimized_source>`.

---

## Extending PerfLens

### Add a new hardware profile

```python
# perflens/hardware/database.py — inside _build_profiles()
profiles["my_hw"] = HardwareProfile(
    profile_id="my_hw",
    name="My Custom HPC Node",
    vendor="custom", arch="custom",
    cores_per_socket=64, sockets=2, threads_per_core=2,
    base_freq_ghz=2.4, boost_freq_ghz=3.6,
    l1d_kb=32, l1i_kb=32, l2_kb=512, l3_mb=128,
    memory_bandwidth_gbs=300.0, memory_capacity_gb=512,
    memory_type="DDR5",
    simd=SIMDCapability("AVX-512", 512),
    peak_dp_gflops_socket=4096.0,
    recommended_cflags=["-O3", "-march=native", "-fopenmp"],
)
```

### Add a new scanner pattern

```python
# perflens/scanner/clang_scanner.py — _REGEX_PATTERNS list
(
    re.compile(r"__builtin_expect"),
    FindingKind.GENERAL,
    Severity.LOW,
    "Manual branch-prediction hint found — verify it's still needed",
    "Profile first; modern CPUs predict well without manual hints",
),
```

### Add a new transform kind

```python
# perflens/optimizer/models.py — TransformKind enum
POLYHEDRAL_TRANSFORM = "polyhedral_transform"
```

Then add it to the `transform_priority` list in `configs/perflens.yaml`.
