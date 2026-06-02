# perflens Architecture

perflens is organized as a set of loosely coupled stages so the framework can optimize large HPC projects without assuming a single build system, compiler, profiler, or language.

## Pipeline

```text
source tree -> static scanner -> scan report
profile export -> profile parser -> hotspot report
hardware db/probe -> hardware spec
scan + profile + hardware -> optimization plan
patch candidates -> validator -> accepted/rejected iteration
iteration artifacts -> dashboard
```

## Modules

- `scanner.py`: language detection, static findings, optional Clang diagnostics.
- `profiles.py`: HPCToolkit and VTune export parsers.
- `hardware.py`: built-in and user-supplied hardware capability data.
- `optimizer.py`: ranked optimization recommendations and external LLM adapter.
- `validator.py`: test and benchmark command runner.
- `dashboard.py`: static HTML report generator.
- `workflow.py`: end-to-end orchestration used by `perflens analyze`.
- `cli.py`: command-line interface.

## Safety Model

The first version prefers recommendations and patch candidates over direct mutation. Automatic rewrites should run in a throwaway git worktree, then pass project validation and benchmark comparison before being proposed for merge.

Future versions can add source-to-source transformations once the validator has enough project-specific coverage and numerical tolerance checks.

