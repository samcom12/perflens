# perflens

perflens is an automation framework for finding, explaining, validating, and tracking performance optimizations in HPC codebases. The initial case-study version supports C, C++, Fortran, and Python projects.

The project starts with a conservative workflow:

1. Scan source code for static performance signals.
2. Parse HPCToolkit or Intel VTune profile exports.
3. Match findings with hardware capabilities.
4. Generate ranked optimization recommendations and LLM-ready prompt bundles.
5. Validate proposed changes with project test and benchmark commands.
6. Render a static dashboard for iteration history.

## Current Capabilities

- Static scanner for C, C++, Fortran, and Python.
- Optional Clang diagnostics for C/C++ files when `clang` is available.
- VTune CSV parser and HPCToolkit text parser.
- Built-in hardware database for generic x86, AMD Zen 4, Intel Sapphire Rapids, NVIDIA H100, and AMD MI300A.
- Rule-based optimization engine with an adapter for external LLM patch generators.
- Patch validator that runs configured tests and benchmarks before accepting changes.
- Static benchmark comparison dashboard with no server requirement.

## Quick Start

From the repository root:

```powershell
$env:PYTHONPATH = "src"
python -m perflens scan examples/mini_app -o .perflens/scan.json
python -m perflens parse-profile examples/profiles/vtune_hotspots.csv -o .perflens/profile.json
python -m perflens recommend --scan .perflens/scan.json --profile .perflens/profile.json --hardware amd-zen4 -o .perflens/plan.json
python -m perflens validate --config examples/mini_app/perflens.yml -o .perflens/validation.json
python -m perflens dashboard --scan .perflens/scan.json --profile .perflens/profile.json --plan .perflens/plan.json --validation .perflens/validation.json -o reports/perflens
```

Open `reports/perflens/index.html` to view the dashboard.

## CLI

```text
perflens scan PATH
perflens parse-profile PROFILE
perflens hardware list
perflens hardware show HARDWARE_ID
perflens hardware probe
perflens recommend --scan scan.json [--profile profile.json] [--hardware amd-zen4]
perflens validate --config perflens.yml
perflens dashboard --scan scan.json --plan plan.json
perflens analyze PATH [--profile profile.csv] [--config perflens.yml]
```

## LLM Optimization Flow

The first implementation does not apply source rewrites automatically by default. It creates structured optimization actions and prompt bundles that can be sent to an external LLM-backed patch generator.

Set `PERFLENS_LLM_COMMAND` to an executable command if you want to plug in your own model runner. The command receives a JSON request on stdin and must return a JSON response containing candidate patches.

```json
{
  "patches": [
    {
      "title": "Vectorize stencil loop",
      "diff": "...",
      "rationale": "..."
    }
  ]
}
```

Patch candidates should always be validated with `perflens validate`.

## Configuration

perflens accepts JSON, TOML, and a small YAML subset for validation configs.

```yaml
project:
  name: mini-app
  root: .
validation:
  commands:
    - name: python-smoke
      command: "{python} vector_loop.py"
benchmark:
  repeat: 3
  commands:
    - name: python-loop
      command: "{python} vector_loop.py --benchmark"
```

## Roadmap

- Compile database ingestion for stronger Clang AST analysis.
- OpenMP, MPI, CUDA, HIP, and OpenACC-specific analysis passes.
- Direct HPCToolkit XML and database import.
- Patch application in isolated git worktrees.
- Numerical tolerance checks for floating-point regression validation.
- Iterative optimization planner with rollback and benchmark history.
