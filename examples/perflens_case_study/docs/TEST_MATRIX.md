# PerfLens Case Study — Master Test Matrix

Status values:
- TODO
- PASS
- FAIL
- OBS
- BLOCK
- N/A

| Test ID | Phase | Command | Option | Test Purpose | Input / Scenario | Expected Result | Test Type | Status | Evidence |
|---|---|---|---|---|---|---|---|---|---|

## Global CLI

| CLI-001 | CLI | `perflens --help` | — | Verify top-level help | Normal invocation | Help displayed successfully | Positive | TODO | |
| CLI-002 | CLI | `perflens --version` | — | Verify version reporting | Normal invocation | Correct version displayed | Positive | TODO | |
| CLI-003 | CLI | `perflens --help` | — | Repeated invocation | Run multiple times | Stable output | Reproducibility | TODO | |

## Static Scanner

| SCN-001 | Scanner | `perflens scan <source>` | — | Basic static scan | Valid C source | Findings returned | Positive | TODO | |
| SCN-002 | Scanner | `perflens scan <source>` | `--lang c` | Explicit language selection | C source | C scanner used | Positive | TODO | |
| SCN-003 | Scanner | `perflens scan <source>` | `--output <file>` | JSON/output file generation | Valid source | Output file created | Functional | TODO | |
| SCN-004 | Scanner | `perflens scan <source>` | `--verbose` | Detailed scan output | Valid source | Verbose information displayed | Functional | TODO | |
| SCN-005 | Scanner | `perflens scan <directory>` | — | Directory scanning | Multi-file project | Relevant source files scanned | Integration | TODO | |
| SCN-006 | Scanner | `perflens scan <invalid>` | — | Invalid path handling | Missing path | Clear error / non-zero exit | Negative | TODO | |
| SCN-007 | Scanner | `perflens scan <source>` | invalid `--lang` | Invalid language handling | Unsupported language | Clear error | Negative | TODO | |

## Profiler

| PROF-001 | Profiler | `perflens profile <source>` | `--tool vtune` | Parse VTune profile | Real VTune result | Correct hotspots extracted | Positive | TODO | |
| PROF-002 | Profiler | `perflens profile <source>` | `--report <file>` | Parse supplied report | Saved VTune report | Correct data extracted | Positive | TODO | |
| PROF-003 | Profiler | `perflens profile <source>` | `--output <file>` | Save parsed profile | Valid report | Output generated | Functional | TODO | |
| PROF-004 | Profiler | `perflens profile <source>` | invalid `--tool` | Unknown profiler handling | Invalid tool | Clear error | Negative | TODO | |
| PROF-005 | Profiler | `perflens profile <source>` | malformed report | Parser robustness | Corrupt report | Controlled failure | Negative | TODO | |

## Optimizer

| OPT-001 | Optimizer | `perflens optimize <source>` | `--backend rules` | Rule-based optimization | Known optimization opportunities | Valid optimization result | Positive | TODO | |
| OPT-002 | Optimizer | `perflens optimize <source>` | `--hw` | Explicit hardware selection | Known hardware profile | Selected profile used | Positive | TODO | |
| OPT-003 | Optimizer | `perflens optimize <source>` | `--profile` | Use external profile | Saved profiler result | Hotspot data used | Integration | TODO | |
| OPT-004 | Optimizer | `perflens optimize <source>` | `--profile-tool` | Profile parser selection | VTune / applicable tool | Correct parser selected | Functional | TODO | |
| OPT-005 | Optimizer | `perflens optimize <source>` | `--output` | Save optimization output | Valid source | Output file generated | Functional | TODO | |
| OPT-006 | Optimizer | `perflens optimize <source>` | `--dry-run` | Verify no source modification | Valid source | No source overwrite | Safety | TODO | |
| OPT-007 | Optimizer | `perflens optimize <source>` | `--iterations` | Iteration control | 1 / multiple iterations | Requested iteration count honored | Boundary | TODO | |
| OPT-008 | Optimizer | `perflens optimize <source>` | `--compiler-feedback` | Include compiler feedback | Vectorization case | Compiler data incorporated | Integration | TODO | |
| OPT-009 | Optimizer | `perflens optimize <source>` | `--feedback-compiler` | Explicit compiler selection | GCC / available compiler | Requested compiler used | Functional | TODO | |
| OPT-010 | Optimizer | `perflens optimize <source>` | `--ollama-model` | Ollama model selection | Available/unavailable model | Correct handling | Backend | TODO | |
| OPT-011 | Optimizer | `perflens optimize <source>` | `--ollama-host` | Custom Ollama endpoint | Valid/invalid host | Correct connection behavior | Backend | TODO | |
| OPT-012 | Optimizer | `perflens optimize <source>` | `--compat-url` | OpenAI-compatible endpoint | Valid/invalid endpoint | Correct handling | Backend | TODO | |
| OPT-013 | Optimizer | `perflens optimize <source>` | `--compat-model` | Compatibility model selection | Valid model | Model passed correctly | Backend | TODO | |
| OPT-014 | Optimizer | `perflens optimize <source>` | `--compat-key` | API key handling | Test credential path safely | Correct key handling | Backend | TODO | |

## Validator

| VAL-001 | Validator | `perflens validate <original> <patched>` | — | Basic validation | Valid equivalent patch | Validation succeeds | Positive | TODO | |
| VAL-002 | Validator | `perflens validate <original> <patched>` | `--tests` | Run test suite | Case-study tests | Tests executed | Integration | TODO | |
| VAL-003 | Validator | `perflens validate <original> <patched>` | `--tol` | Numerical tolerance | Multiple tolerances | Correct tolerance behavior | Boundary | TODO | |
| VAL-004 | Validator | `perflens validate` | invalid original | Invalid input handling | Missing/bad file | Controlled failure | Negative | TODO | |
| VAL-005 | Validator | `perflens validate` | intentionally wrong patch | Correctness rejection | Wrong numerical result | Validation fails/skips appropriately | Negative | TODO | |

## Dashboard

| DASH-001 | Dashboard | `perflens dashboard` | — | Start dashboard | Valid DB/data | Dashboard starts | Positive | TODO | |
| DASH-002 | Dashboard | `perflens dashboard` | `--port` | Custom port | Free port | Server binds requested port | Functional | TODO | |
| DASH-003 | Dashboard | `perflens dashboard` | `--host` | Custom host | Valid host | Server binds requested host | Functional | TODO | |
| DASH-004 | Dashboard | `perflens dashboard` | `--db` | Alternate database | Valid DB | Correct data loaded | Functional | TODO | |
| DASH-005 | Dashboard | `perflens dashboard` | occupied port | Port conflict | Existing server | Clear failure | Negative | TODO | |

## Backends

| BACK-001 | Backend | `perflens backends` | — | Enumerate backends | Normal environment | Availability correctly reported | Positive | TODO | |
| BACK-002 | Backend | `perflens backends` | — | Missing external services | Ollama/API unavailable | Graceful unavailable status | Failure handling | TODO | |

## Autotuner

| AUTO-001 | Autotuner | `perflens autotune <source>` | `--param tile` | Tile tuning | Tunable tiled kernel | Best tile selected | Positive | TODO | |
| AUTO-002 | Autotuner | `perflens autotune <source>` | `--param threads` | Thread tuning | OpenMP workload | Best thread count selected | Positive | TODO | |
| AUTO-003 | Autotuner | `perflens autotune <source>` | `--hw` | Explicit hardware | Known profile | Hardware used | Functional | TODO | |
| AUTO-004 | Autotuner | `perflens autotune <source>` | `--driver` | External driver | Case-study driver | Driver executed correctly | Integration | TODO | |
| AUTO-005 | Autotuner | `perflens autotune <source>` | `--tiles` | Candidate tile list | 8,16,32,... | Candidates tested | Functional | TODO | |
| AUTO-006 | Autotuner | `perflens autotune <source>` | `--threads` | Candidate thread list | 1,2,4,... | Candidates tested | Functional | TODO | |
| AUTO-007 | Autotuner | `perflens autotune <source>` | `--output` | Save tuning result | Valid tuning | JSON/config generated | Functional | TODO | |
| AUTO-008 | Autotuner | `perflens autotune <source>` | missing TILE | Invalid source | No TILE definition | Controlled response | Negative | TODO | |

## Compiler Feedback

| CMP-001 | Compiler | `perflens compiler <source>` | `--compiler gcc` | GCC feedback | Vectorizable loop | Correct remarks extracted | Positive | TODO | |
| CMP-002 | Compiler | `perflens compiler <source>` | `--compiler auto` | Auto compiler selection | Normal environment | Suitable compiler selected | Functional | TODO | |
| CMP-003 | Compiler | `perflens compiler <source>` | `--report <file>` | Parse existing report | Saved compiler report | Correct remarks extracted | Positive | TODO | |
| CMP-004 | Compiler | `perflens compiler <source>` | `--output <file>` | Save feedback | Valid source | Output generated | Functional | TODO | |
| CMP-005 | Compiler | `perflens compiler <source>` | dependency case | Dependency detection | Loop-carried dependency | Dependency reported | Ground truth | TODO | |
| CMP-006 | Compiler | `perflens compiler <source>` | alias case | Aliasing detection | Potential alias | Aliasing reported appropriately | Ground truth | TODO | |

## Hardware

| HW-001 | Hardware | `perflens hw detect` | — | Detect actual node | Rudra compute node | Profile matches hardware | Positive | TODO | |
| HW-002 | Hardware | `perflens hw list` | — | List database | Normal environment | All profiles listed | Functional | TODO | |
| HW-003 | Hardware | `perflens hw show <id>` | — | Show profile | Valid ID | Correct profile shown | Functional | TODO | |
| HW-004 | Hardware | `perflens hw show <id>` | invalid ID | Invalid profile | Unknown ID | Controlled error | Negative | TODO | |

## Whole Project

| PROJ-001 | Project | `perflens project scan <dir>` | — | Discover project | Multi-file CMake project | Files/build system detected | Positive | TODO | |
| PROJ-002 | Project | `perflens project scan <dir>` | `--deps` | Dependency discovery | Header/include graph | Dependencies reported | Integration | TODO | |
| PROJ-003 | Project | `perflens project build <dir>` | — | Build project | Valid CMake project | Successful build / useful failure | Positive | TODO | |
| PROJ-004 | Project | `perflens project optimize <dir>` | `--backend rules` | End-to-end project optimization | Full case study | Pipeline completes appropriately | End-to-end | TODO | |
| PROJ-005 | Project | `perflens project status <dir>` | — | Optimization status | Before/after optimization | Correct status shown | Functional | TODO | |
| PROJ-006 | Project | `perflens project diff <dir>` | — | Show changes | Generated patch | Correct diff shown | Functional | TODO | |

## Cross-Cutting Tests

| CROSS-001 | Cross-cutting | Repeat same command | — | Determinism | Same input twice | Stable result where expected | Reproducibility | TODO | |
| CROSS-002 | Cross-cutting | Invalid input | — | Error quality | Multiple invalid inputs | Clear errors, no crash | Negative | TODO | |
| CROSS-003 | Cross-cutting | Large workload | — | Scalability | Large problem size | Completes and remains correct | Performance | TODO | |
| CROSS-004 | Cross-cutting | Optimized workload | — | Regression | Already optimized input | No harmful optimization | Regression | TODO | |
| CROSS-005 | Cross-cutting | Tool unavailable | — | Environment robustness | Missing profiler/compiler/backend | Controlled handling | Failure handling | TODO | |
