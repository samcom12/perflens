# PerfLens Case Study — Master Test Plan

## Objective

Rigorously evaluate the PerfLens framework using a controlled HPC case-study
project from a production-oriented testing perspective.

The evaluation covers:
- every applicable CLI command
- every applicable command option
- normal operation
- invalid input
- edge cases
- failure handling
- correctness
- performance
- reproducibility
- regression behavior

---

## Test Result Categories

- PASS  : Expected behavior observed.
- FAIL  : Expected behavior not observed.
- OBS   : Behavior is notable but not necessarily a defect.
- BLOCK : Test cannot be executed because of environment/tool limitations.
- N/A   : Not applicable, with justification recorded.

---

## Test Record

Each test must record:

1. Test ID
2. PerfLens phase
3. Command
4. Option(s)
5. Purpose
6. Input / case
7. Expected result
8. Actual result
9. Result status
10. Evidence location
11. Problem observed
12. Investigation
13. Root cause
14. Impact
15. Next action

---

# Command Inventory

## Global CLI

- `perflens --help`
- `perflens --version`

## Static Scanner

- `perflens scan`
- `perflens scan --lang`
- `perflens scan --output`
- `perflens scan --verbose`

## Profiler

- `perflens profile`
- `perflens profile --tool`
- `perflens profile --report`
- `perflens profile --output`

## Optimizer

- `perflens optimize`
- `perflens optimize --hw`
- `perflens optimize --backend`
- `perflens optimize --profile`
- `perflens optimize --profile-tool`
- `perflens optimize --output`
- `perflens optimize --dry-run`
- `perflens optimize --iterations`
- `perflens optimize --ollama-model`
- `perflens optimize --ollama-host`
- `perflens optimize --compat-url`
- `perflens optimize --compat-model`
- `perflens optimize --compat-key`
- `perflens optimize --compiler-feedback`
- `perflens optimize --feedback-compiler`

## Validator

- `perflens validate`
- `perflens validate --tests`
- `perflens validate --tol`

## Dashboard

- `perflens dashboard`
- `perflens dashboard --port`
- `perflens dashboard --host`
- `perflens dashboard --db`

## Backends

- `perflens backends`

## Autotuner

- `perflens autotune`
- `perflens autotune --hw`
- `perflens autotune --driver`
- `perflens autotune --param tile`
- `perflens autotune --param threads`
- `perflens autotune --tiles`
- `perflens autotune --threads`
- `perflens autotune --output`

## Compiler Feedback

- `perflens compiler`
- `perflens compiler --compiler`
- `perflens compiler --report`
- `perflens compiler --output`

## Hardware

- `perflens hw detect`
- `perflens hw list`
- `perflens hw show`

## Whole-Project Workflow

- `perflens project scan`
- `perflens project build`
- `perflens project optimize`
- `perflens project status`
- `perflens project diff`

---

# Test Categories

For every applicable command:

## Functional
- Valid normal input
- Expected successful execution
- Correct output format
- Correct result values

## Negative
- Missing required argument
- Invalid path
- Invalid option value
- Unsupported file type
- Missing dependency/tool

## Boundary / Edge
- Empty input
- Minimal input
- Large input
- Already optimized input
- Repeated execution

## Performance
- Runtime
- Scaling
- Resource usage
- Profiling overhead where applicable

## Correctness
- Compilation
- Runtime correctness
- Numerical equivalence
- Regression checks

## Reproducibility
- Repeated runs
- Stable output
- Stable findings
- Stable benchmark behavior

## Integration
- Interaction with other PerfLens phases
- Output consumed by later phases
- End-to-end workflow

---

# Ground Truth Requirements

The case-study application must contain controlled examples for:

- loop vectorization
- missed vectorization
- aliasing
- data dependency
- nested loops
- loop tiling opportunity
- loop parallelization
- SIMD opportunity
- division inside loop
- expensive math inside loop
- I/O inside loop
- OpenMP
- MPI
- compiler feedback
- runtime hotspots
- numerical reference output
- tunable tile size
- tunable thread count

---

# Evidence Storage

Raw experiment evidence:

`~/perflens_work/benchmark_results/case_study_setup/`

Case-study-specific evidence:

`examples/perflens_case_study/results/`

Human-readable records:

`examples/perflens_case_study/docs/`

---

# Master Test Log

All executed tests will be recorded in:

`examples/perflens_case_study/docs/TEST_LOG.md`

---

# Confirmed Findings

All confirmed bugs, limitations, unexpected behavior, and important observations
will be recorded in:

`examples/perflens_case_study/docs/FINDINGS.md`

---

# Rule

Do not classify behavior as a bug from a single unexpected output.

Process:

Observe
-> Reproduce
-> Investigate
-> Identify root cause
-> Confirm
-> Record finding
-> Retest after any improvement
