# PerfLens Case Study — Test Log

| Test ID | Phase | Command / Option | Test Case | Expected | Actual | Result | Evidence | Problem / Observation |
|---|---|---|---|---|---|---|---|---|

| BUILD-001 | Case Study Setup | Created `src/heat.c` | Establish primary heat solver kernels | `heat.c` exists with serial, tiled, OpenMP, boundary, initialization and error functions | File created and inspected | PASS | `examples/perflens_case_study/src/heat.c` | No issue observed during creation |
| BUILD-002 | Case Study Build | `cmake --build build -j4` | First complete build | Executable links successfully | Link failed with undefined references to `sin` and `sqrt` | FAIL | `~/perflens_work/benchmark_results/case_study_setup/build_output.txt` | Math library not linked |
