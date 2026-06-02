# perflens Roadmap

## Milestone 1: Case Study Framework

- Multi-language scanner for C, C++, Python, and Fortran.
- VTune and HPCToolkit parser basics.
- Hardware database and hardware-aware recommendation ranking.
- Validation and benchmark runner.
- Static HTML dashboard.

## Milestone 2: Stronger Compiler Intelligence

- `compile_commands.json` ingestion.
- Clang AST loop extraction and source ranges.
- OpenMP and vectorization remark ingestion.
- Fortran parser integration through fparser or compiler diagnostics.

## Milestone 3: Automated Patch Loop

- Isolated git worktree patch application.
- LLM candidate generation with structured prompts.
- Test, benchmark, and numerical tolerance gates.
- Patch ranking by speedup, correctness risk, and portability.

## Milestone 4: HPC Runtime Awareness

- MPI rank-level profile correlation.
- GPU kernel and memory-transfer analysis.
- Roofline-style hardware saturation estimates.
- Slurm/PBS integration for repeatable cluster benchmarking.

