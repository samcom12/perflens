# PerfLens Case Study — 2D Heat Diffusion

A controlled HPC application used to rigorously evaluate the PerfLens
optimization framework.

## Purpose

The project provides controlled examples for:

- vectorization
- missed vectorization
- aliasing
- dependencies
- division inside loops
- expensive mathematical functions
- nested loops
- OpenMP parallelism
- MPI communication
- I/O in loops
- loop tiling
- numerical validation
- thread/tile autotuning

## Project Structure

- `src/` — application source
- `input/` — reproducible workload configurations
- `scripts/` — execution drivers
- `tests/` — correctness/regression tests
- `results/` — case-study-generated results
- `docs/` — study plan, test matrix, log, and findings

## Important

This application is a controlled evaluation workload for PerfLens.
It is intentionally designed to contain both optimization opportunities
and negative/edge cases.
