# project_hello — SWE Solver Example

A minimal 3-file shallow-water equations solver designed as a
PerfLens case study. Every file contains intentional anti-patterns.

## Files

| File | Anti-patterns |
|------|--------------|
| `src/flux.c` | `sqrt()` in loop, division in loop, no `#pragma omp simd` |
| `src/solver.c` | Blocking MPI halo exchange, `printf` in time loop, missing OpenMP |
| `src/io.c` | `fwrite` per element, `pow(x,2)` instead of `x*x`, 3-pass stats |

## Run PerfLens on this project

```bash
# Zero API key — rule engine only
perflens project optimize examples/project_hello --backend rules --no-build

# With build (requires gcc/cmake)
perflens project optimize examples/project_hello --backend rules

# See what changed
perflens project diff examples/project_hello

# Apply patches back to source tree
perflens project optimize examples/project_hello --backend rules --apply
```

## Build manually

```bash
cmake -B build -DCMAKE_BUILD_TYPE=RelWithDebInfo
cmake --build build -j$(nproc)
./build/swe_solver
```
