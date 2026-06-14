# Changelog

All notable changes to PerfLens are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/).

---

## [0.3.1] — Correctness Fixes (main-branch audit)

This release fixes a class of bugs where the framework could emit
non-compiling or numerically-wrong "optimized" code and still report success.
The central fix makes validation **fail closed**: a semantics-changing patch
is never accepted unless its correctness is positively established.

### Fixed
- **Validator fail-closed gate** (`validator/models.py`): `ValidationReport.passed`
  previously treated `SKIP`/`WARNING` as success. It now fails when a *critical*
  check is skipped, and when a patch may change numerical results but correctness
  was not verified. Added `verdict` (`passed`/`failed`/`unverified`).
- **Automatic test-harness generation** (`validator/harness.py`, new): compiled
  C/C++ kernels are now verified for numerical equivalence by synthesising a
  seeded driver, compiling original+harness and patched+harness, running both,
  and comparing outputs — instead of silently skipping unless a hand-written
  `perflens_driver.sh` happened to exist.
- **Portable validation builds** (`validator/checker.py`): dropped
  `-march=…/-mavx512…/-ffast-math` (could SIGILL on the build host and perturb
  FP results); validation now uses `-O0 -fno-fast-math` + IEEE math.
- **`OpenMPParallelRule`** (`optimizer/rules/c_rules.py`): now annotates only the
  *outermost* loop of a nest and **skips loops containing reductions** (e.g.
  `sum += …`) that would race without a `reduction` clause. Defers to GPU
  offload on GPU targets to avoid stacking conflicting pragmas.
- **`DivisionHoistRule`**: no longer matches C keywords (`double`), pointers, or
  indexed/called expressions as divisors; only hoists genuinely loop-invariant
  scalar divisors. Comments and string literals are stripped before analysis so
  tokens like `O` in `/* I/O */` are never rewritten. Output now compiles.
- **`OpenMPOffloadRule`**: emits valid `map(tofrom:array[0:n])` clauses for the
  arrays actually accessed in the loop body, instead of the invalid
  `map(tofrom:n[0:n])` on the scalar loop bound.
- **`FortranOpenMPDoRule`**: correctly pairs each outermost `DO` with its
  matching `END DO`, emitting balanced `!$OMP PARALLEL DO` / `!$OMP END PARALLEL
  DO` (previously unbalanced and non-compiling on nested loops).
- **`TileSearchTuner`** (`autotuner/tile_tuner.py`): supports `build_command`/
  `run_command` for real multi-file projects; in single-file mode it now detects
  a missing `main()` and reports a clear reason instead of silently failing every
  trial. Uses portable build flags.
- **Shared-header protection enforced in code** (`optimizer/project_optimizer.py`):
  header files and headers shared by ≥3 files are now skipped by the optimizer,
  rather than relying on a prompt comment the rules backend never saw.

### Tests
- `tests/unit/test_correctness_fixes.py` — 16 regression tests pinning every fix
  above, including live `gcc`/`gfortran` compile checks and harness accept/reject.
- Total: 286 passing (was 270).

---


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
