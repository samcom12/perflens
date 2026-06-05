# Running PerfLens Without an API Key

PerfLens is designed to be fully useful **without any cloud API keys**.
This guide walks through every key-free optimization path.

---

## Option 1 — Rule Engine (Zero LLM, Fully Offline)

The fastest path: no LLM, no network, no key.

```bash
# Scan + optimize in one command
perflens optimize solver.c --backend rules --hw a100

# Python example
perflens optimize examples/python/heat_solver.py --backend rules

# Fortran + collect compiler feedback at the same time
perflens optimize examples/fortran/jacobi.f90 --backend rules --compiler-feedback
```

**What the rule engine applies automatically:**

| Language | Rules fired |
|----------|-------------|
| C/C++ | Loop tiling, `#pragma omp parallel for`, `#pragma omp simd`, OpenMP GPU offload, MPI non-blocking, division hoisting |
| Python | `math.*` → `np.*`, allocation hoisting, `@numba.njit`, `.iterrows()` hints |
| Fortran | `IMPLICIT NONE`, `!$OMP PARALLEL DO`, `!$OMP SIMD`, non-blocking MPI |

---

## Option 2 — Local Ollama (No Key, Runs on Your GPU)

Install Ollama once, then run any open-weight model:

```bash
# Install
curl -fsSL https://ollama.com/install.sh | sh

# Pull the best model for HPC code
ollama pull codellama:34b        # best for C/C++/Fortran
ollama pull deepseek-coder:33b   # strong alternative
ollama pull llama3:8b            # fast, lower VRAM

# Optimize
perflens optimize solver.c --backend ollama --hw a100
perflens optimize solver.c --backend ollama:llama3:8b
```

Check what's available on your system:
```bash
perflens backends   # shows which backends are ready
ollama list         # shows pulled models
```

---

## Option 3 — LM Studio (GUI-Friendly, No Key)

1. Download LM Studio: https://lmstudio.ai
2. Pull a GGUF model (e.g. `deepseek-coder-33b-instruct`)
3. Start the local server in LM Studio (port 1234)
4. Run PerfLens:

```bash
perflens optimize solver.c --backend lmstudio
```

---

## Option 4 — llama.cpp Server (Lightweight, CPU+GPU)

```bash
# Build and run
git clone https://github.com/ggerganov/llama.cpp && cd llama.cpp
cmake -B build && cmake --build build -j$(nproc)
./build/bin/llama-server -m DeepSeek-Coder-V2-Instruct-Q4_K_M.gguf --port 8080

# Use from PerfLens
perflens optimize solver.c --backend llamacpp
```

---

## Option 5 — Groq Cloud (Free Tier, No Anthropic Key)

Groq offers a generous free tier with very fast inference:

```bash
# Get a free API key at https://console.groq.com/keys
export GROQ_API_KEY=gsk_...

perflens optimize solver.c --backend groq --hw a100
```

Available models: `llama3-70b-8192`, `llama3-8b-8192`, `mixtral-8x7b-32768`

---

## Option 6 — vLLM (GPU-Accelerated, No Key)

Best for teams running large models on on-premise GPUs:

```bash
pip install vllm
python -m vllm.entrypoints.openai.api_server \
    --model deepseek-ai/deepseek-coder-33b-instruct \
    --port 8000

# Use from PerfLens
perflens optimize solver.c --backend vllm \
    --compat-model deepseek-ai/deepseek-coder-33b-instruct
```

---

## Checking Backend Availability

```bash
perflens backends
```

Output:
```
╭──────────────────┬──────────────┬───────────┬───────┬──────────────────────────╮
│ Backend          │ Available    │ Needs Key │ Local │ Notes                    │
├──────────────────┼──────────────┼───────────┼───────┼──────────────────────────┤
│ rules            │ ✓            │ no        │ yes   │ Zero-LLM rule engine     │
│ ollama           │ ✓            │ no        │ yes   │ codellama:34b pulled     │
│ groq             │ ✗            │ yes       │ cloud │ Set GROQ_API_KEY         │
│ lmstudio         │ ✗            │ no        │ yes   │ Start LM Studio server   │
│ anthropic        │ ✗            │ yes       │ cloud │ Set ANTHROPIC_API_KEY    │
╰──────────────────┴──────────────┴───────────┴───────┴──────────────────────────╯
```

---

## Full Workflow: Rules + Auto-Tuning (Zero Keys)

```bash
# Step 1: Scan for issues
perflens scan solver.c

# Step 2: Apply rule-based optimizations
perflens optimize solver.c --backend rules --hw a100

# Step 3: Collect compiler feedback (optional but free)
perflens compiler solver.c --compiler gcc

# Step 4: Auto-tune the tile size empirically
perflens autotune solver_optimized_iter0.c \
    --param tile --tiles 8,16,32,64,128

# Step 5: Validate correctness
perflens validate solver.c solver_optimized_iter0.c

# Step 6: View results in the dashboard
perflens dashboard --port 8080
```

---

## CDAC Param Prabha (A100 cluster) — Recommended Setup

```bash
# Clone repo on the cluster
git clone https://github.com/samcom12/perflens && cd perflens
pip install -e . --user

# Use rule engine (works without internet on compute nodes)
perflens optimize src/anuga_solver.c --backend rules \
    --hw a100 --compiler-feedback --feedback-compiler gcc

# Auto-tune tile size on actual A100 hardware
perflens autotune src/anuga_solver_optimized_iter0.c \
    --hw a100 --param tile

# View results
perflens dashboard &   # open http://localhost:8080 via SSH tunnel
```
