# Changelog

All notable changes to PerfLens are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

---

## [0.3.0] — Project-Level Workflow

### Added
- **`perflens project` command group** — whole-codebase optimization workflow
  - `scan`     — crawl project, show file list and dependency graph
  - `build`    — compile and auto-collect compiler optimization reports
  - `optimize` — full 7-step pipeline (crawl→build→profile→scan→plan→optimize→validate)
  - `status`   — show which files have patches ready
  - `diff`     — unified diff of all patches
- **`perflens/project/` module** — new codebase analysis layer
  - `crawler.py` — build-system detection (CMake/Make/Meson/Autoconf/bare/Python),
    recursive file discovery, `#include`/`USE`/`import` dependency parsing
  - `build_system.py` — `BuildDriver` for CMake/Make/Meson/bare; injects
    `-fopt-info`/`-Rpass`/`-qopt-report` flags automatically
  - `dependency_graph.py` — topological sort, transitive-dependent BFS,
    shared-header detection (≥N callers), optimization batch ordering,
    Graphviz DOT export
  - `models.py` — `ProjectGraph`, `SourceFile` (priority scoring), `OptimizationPhase`,
    `ProjectOptimizationPlan`, `ProjectOptimizationResult`
- **`perflens/optimizer/project_optimizer.py`** — phase-based multi-file optimizer;
  unified context (hotspot%+compiler misses+aliasing+dependency role) per file;
  writes patches to `perflens_patches/` mirroring source tree
- **`perflens/pipeline/project_pipeline.py`** — 7-step orchestrator using
  `ThreadPoolExecutor` for parallel scanning
- **`examples/project_hello/`** — 3-file SWE solver case study with intentional
  anti-patterns across `flux.c`, `solver.c`, `io.c`
- 34 new tests in `tests/unit/project/test_project.py`
- 49 CLI tests in `tests/unit/test_cli.py` (covers all 11 commands)

### Fixed
- `perflens/cli.py`: `NameError: _version_callback not defined` — orphaned function
  body from previous patch session

---

## [0.2.0] — Multi-Backend System + Zero-Key Rule Engine

### Added
- **`perflens/optimizer/backends/`** — abstract `LLMBackend` interface with 5 backends
  - `RuleEngineBackend` — zero LLM, no API key, fully offline
  - `OllamaBackend` — local Ollama `/api/chat` (codellama, deepseek-coder, llama3 …)
  - `OpenAICompatBackend` — vLLM, LM Studio, llama.cpp, Groq, Together, OpenRouter
  - `AnthropicBackend` — refactored from previous engine
  - `registry.py` — `create_backend()` + `list_backends()` with live availability
- **`perflens/optimizer/rules/`** — 14 zero-LLM transformation rules
  - C/C++ (6): loop tiling, OpenMP parallel/SIMD/offload, MPI non-blocking, division hoist
  - Python (4): scalar math→numpy, preallocate, numba annotate, pandas vectorise
  - Fortran (4): IMPLICIT NONE, OMP DO, OMP SIMD, MPI non-blocking
- **`perflens/compiler_feedback/`** — GCC `-fopt-info`, Clang `-Rpass`, ICX `.optrpt` parsers
- **`perflens/autotuner/`** — empirical tile size + thread count sweep
- New CLI commands: `backends`, `autotune`, `compiler`
- `--backend` flag on `optimize` command
- Dashboard: `/api/backends` endpoint + backend status panel

### Changed
- `OptimizationEngine` refactored to be backend-agnostic
- Default backend changed from `anthropic` to `rules` (no key required)
- `PerfLensPipeline` wired through new backend system

---

## [0.1.0] — Initial Release

### Added
- **`perflens/scanner/`** — Clang AST + regex scanner (C/C++/Fortran/Python)
  - 20+ anti-pattern detectors across 4 languages
- **`perflens/profiler/`** — VTune CSV/XML + HPCToolkit experiment.xml parsers
- **`perflens/hardware/`** — 9 built-in hardware profiles
  (A100, H100, V100, Intel SPR/ICX, AMD Genoa/Milan, A64FX, Graviton3)
- **`perflens/optimizer/`** — LLM optimization engine (Anthropic API)
- **`perflens/validator/`** — compile + test + numerical diff + sanity check
- **`perflens/dashboard/`** — FastAPI + Plotly benchmark dashboard
- **`perflens/pipeline/`** — single-file pipeline orchestrator
- CLI commands: `scan`, `profile`, `optimize`, `validate`, `dashboard`, `hw`
- 5 example files with intentional HPC anti-patterns
- 115 unit + integration tests
- GitHub Actions CI with 4 parallel jobs
