# PerfLens Case Study — Source Design

## main.c

Functions:
- main()
- read_config()
- allocate_grid()
- initialize_grid()
- run_serial()
- run_openmp()
- run_mpi()
- compute_checksum()
- print_results()

Purpose:
Application control, reproducible execution, mode selection,
baseline execution, correctness output, and end-to-end testing.

## heat.c

Functions:
- heat_step()
- heat_step_tiled()
- heat_step_openmp()
- apply_boundary()
- compute_error()

Purpose:
Primary computational workload and runtime hotspot.

Controlled features:
- nested loops
- vectorization opportunity
- OpenMP opportunity
- loop tiling
- numerical computation
- measurable runtime

## kernels.c

Functions:
- vectorizable_kernel()
- missed_vectorization_kernel()
- aliasing_kernel()
- dependency_kernel()
- division_kernel()
- expensive_math_kernel()

Purpose:
Controlled ground-truth compiler and static-analysis cases.

## io.c

Functions:
- write_field()
- write_field_elementwise()
- write_summary()

Purpose:
File I/O testing, especially I/O inside loops.

## mpi_heat.c

Functions:
- mpi_initialize()
- exchange_halo_blocking()
- exchange_halo_nonblocking()
- mpi_heat_step()
- mpi_finalize()

Purpose:
MPI project support and MPI optimization testing.

Controlled feature:
- blocking MPI_Send/MPI_Recv halo communication.

## heat.h

Exports heat solver declarations and creates real header dependencies.

## kernels.h

Exports controlled compiler-test kernel declarations.

## Ground Truth

Each controlled function must have a known expected PerfLens behavior
documented before testing.

## Runtime Execution Model

### Serial mode

`heat_solver --mode serial`

Uses:
- `heat_step()`
- serial baseline execution
- deterministic numerical result

Purpose:
- baseline correctness
- baseline performance
- profiling reference

### OpenMP mode

`heat_solver --mode openmp`

Uses:
- `heat_step_openmp()`
- OpenMP parallel loop

Purpose:
- OpenMP correctness
- thread scaling
- compiler feedback
- optimization comparison

### Tiled mode

`heat_solver --mode tiled`

Uses:
- `heat_step_tiled()`
- `TILE` compile-time parameter

Purpose:
- loop tiling
- cache-related optimization
- autotuner tile search

### Kernel test mode

`heat_solver --mode kernel --kernel <name>`

Supported kernels:

- vector
- missed
- alias
- dependency
- division
- math

Purpose:
- isolated ground-truth tests
- compiler feedback
- static scanner testing
- optimization-rule testing

### MPI mode

`heat_solver_mpi`

Uses:
- MPI initialization/finalization
- blocking halo exchange
- nonblocking halo exchange

Purpose:
- MPI static analysis
- MPI optimization
- MPI correctness
- MPI scaling

### Ground-truth principle

Each runtime mode must have:
- deterministic inputs
- deterministic or numerically reproducible output
- an independently known expected behavior
- a clear relationship to one or more PerfLens tests


## MPI Scope

The initial MPI target is a controlled MPI communication fixture rather than
a fully distributed production heat solver.

Its purpose is to exercise:
- blocking MPI communication detection
- nonblocking MPI transformation
- MPI compiler/build handling
- MPI validation behavior

A true domain-decomposed MPI heat solver may be added later if required by
the testing matrix.
