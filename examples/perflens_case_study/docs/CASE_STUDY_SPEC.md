# PerfLens Case Study — Specification

## 1. Purpose

Create a small but production-oriented HPC application that can be used to
systematically evaluate the PerfLens framework.

The application must provide controlled, reproducible cases for static analysis,
compiler feedback, profiling, optimization, validation, autotuning, project
workflow, and error handling.

---

## 2. Application

Application: 2D Heat Diffusion Solver

Language: C

Build system: CMake

Parallel models:
- Serial
- OpenMP
- MPI where supported

Primary output:
- Numerical solution
- Runtime measurements
- Deterministic reference output

---

## 3. Required Project Characteristics

The project must be:

- multi-file
- CMake-based
- dependency-aware
- compilable with the available HPC toolchain
- runnable in serial
- runnable with OpenMP
- capable of an MPI variant
- deterministic for fixed input
- scalable with problem size
- suitable for CPU profiling

---

## 4. Controlled Optimization Cases

### CASE-01 — Vectorizable loop

Provide a loop with independent iterations.

Purpose:
- compiler vectorization
- scanner analysis
- SIMD optimization

PerfLens areas:
- compiler feedback
- static scanner
- optimizer

---

### CASE-02 — Missed vectorization

Provide a loop where vectorization is prevented by a deliberate
dependency or unsuitable access pattern.

Purpose:
- verify missed-vectorization reporting
- compare compiler decision with ground truth

---

### CASE-03 — Aliasing

Provide a kernel using pointers where aliasing may prevent or complicate
vectorization.

Purpose:
- compiler aliasing feedback
- optimizer planning

---

### CASE-04 — Loop-carried dependency

Provide a recurrence where iteration N depends on iteration N-1.

Purpose:
- dependency detection
- missed vectorization

---

### CASE-05 — Division in loop

Provide a loop containing a loop-invariant divisor.

Purpose:
- DIVISION_IN_LOOP detection
- division-hoisting rule
- before/after correctness testing

---

### CASE-06 — Expensive mathematical function

Provide a controlled loop containing sqrt/pow or another expensive math
operation.

Purpose:
- transcendental-function detection
- compiler feedback
- optimization testing

---

### CASE-07 — Nested loops

Provide a computational kernel with nested loops.

Purpose:
- SIMD
- parallelization
- loop tiling
- autotuning

---

### CASE-08 — OpenMP opportunity

Provide a safe independent loop without OpenMP initially.

Purpose:
- OpenMP parallelization rule
- thread-count tuning
- scaling benchmark

---

### CASE-09 — TILE parameter

Provide a kernel containing:

#define TILE <value>

Purpose:
- loop tiling
- autotune tile parameter

---

### CASE-10 — Blocking MPI communication

Provide an optional MPI implementation containing blocking
MPI_Send/MPI_Recv halo communication.

Purpose:
- MPI scanner
- MPI nonblocking optimization
- MPI validation

---

### CASE-11 — I/O inside loop

Provide a controlled I/O loop.

Purpose:
- I/O-in-loop detection
- optimization analysis
- negative/realistic performance case

---

### CASE-12 — Numerical reference

Provide deterministic output suitable for comparison before and after
optimization.

Purpose:
- validator
- regression testing
- numerical tolerance testing

---

## 5. Source File Responsibilities

### main.c

- Parse input/configuration
- Initialize arrays
- Select execution mode
- Run solver
- Print deterministic summary
- Report runtime

### heat.c

- Main heat-diffusion kernel
- Nested computational loops
- OpenMP opportunity
- Tile parameter
- Main performance hotspot

### heat.h

- Shared declarations
- Header dependency for project discovery

### kernels.c

- Controlled compiler-analysis kernels
- vectorizable case
- missed-vectorization case
- aliasing case
- dependency case
- division case
- expensive math case

### kernels.h

- Kernel declarations
- dependency graph target

### io.c

- Controlled output routines
- loop-based I/O case

### mpi_heat.c

- MPI heat solver variant
- halo exchange
- blocking communication case

---

## 6. Workload Sizes

At minimum:

- Small
- Medium
- Large

The exact dimensions will be selected after establishing the baseline so that
runs are long enough for meaningful profiling without unnecessarily consuming
cluster resources.

---

## 7. Correctness Requirements

For a fixed input:

- serial reference must be deterministic
- optimized serial result must match reference within defined tolerance
- OpenMP result must match reference within defined tolerance
- MPI result must match reference within defined tolerance where MPI is tested
- invalid optimizations must be detected by validation

---

## 8. Benchmark Requirements

Record:

- wall-clock runtime
- user/system time where available
- thread count
- problem size
- compiler
- compiler flags
- hardware/node
- correctness result
- profiling result
- PerfLens findings
- optimization result
- validation result

Repeated runs must be recorded to assess variability.

---

## 9. Production-Oriented Negative Tests

The case study must support testing of:

- invalid source path
- invalid project path
- malformed source
- unsupported language selection
- invalid hardware profile
- invalid backend
- unavailable profiler
- missing compiler
- malformed compiler report
- malformed profiler report
- missing TILE definition
- invalid autotuner candidate values
- invalid thread counts
- intentionally incorrect optimized source
- numerical mismatch

---

## 10. Ground Truth

Before PerfLens analysis, each controlled case will be documented with:

- source location
- intentional behavior
- expected compiler behavior
- expected scanner finding
- expected optimizer applicability
- expected validation behavior

PerfLens results will be compared against this ground truth.

---

## 11. Reproducibility

Every experiment must record:

- Git commit
- Git branch
- hostname
- hardware
- compiler version
- CMake version
- PerfLens version
- command executed
- environment/tool modules where relevant
- input parameters
- output
- result classification

---

## 12. Evaluation Principle

The case study is not intended to demonstrate only successful PerfLens behavior.

It must be capable of exposing:

- missed detections
- false positives
- incorrect optimizations
- unsafe transformations
- parser failures
- hardware-detection errors
- validation gaps
- performance regressions
- reproducibility problems
- error-handling problems

A finding is not considered confirmed until it is reproduced and investigated.

