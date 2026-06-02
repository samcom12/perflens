"""
Build structured prompts for the LLM optimization engine.

The prompts are designed to elicit:
  1. A structured list of proposed transformations (JSON)
  2. The full rewritten source file
  3. An explanation of each change
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from perflens.hardware.models import HardwareProfile
from perflens.profiler.models import ProfileData
from perflens.scanner.models import Finding


_SYSTEM_PROMPT = """\
You are PerfLens, an expert HPC performance engineer with deep knowledge of:
- C, C++, Fortran, and Python scientific computing
- Loop transformations (tiling, interchange, fusion, unrolling)
- SIMD vectorization (AVX-512, SVE, CUDA)
- OpenMP parallelization and GPU offloading
- MPI communication patterns (blocking vs non-blocking)
- Memory hierarchy optimization (cache blocking, prefetching, layout)
- NumPy/SciPy vectorization and Numba JIT compilation
- Roofline model analysis

Your task is to analyze HPC source code and produce concrete, compilable,
performance-improving transformations. Always:
1. Preserve exact numerical semantics (same floating-point results within tolerance)
2. Maintain MPI/OpenMP correctness (no race conditions introduced)
3. Keep the same function signatures / API surface
4. Explain the expected speedup with quantitative reasoning
5. Return a valid JSON block followed by the complete rewritten source

Output format (strictly follow this):
```json
{
  "patches": [
    {
      "transform_kind": "<TransformKind value>",
      "description": "<one-line summary>",
      "start_line": <int>,
      "end_line": <int>,
      "rationale": "<why this helps>",
      "expected_speedup": "<range, e.g. 2-4x>"
    }
  ],
  "explanation": "<overall optimization strategy>"
}
```
Then output the complete rewritten source file between:
<optimized_source>
... complete source ...
</optimized_source>
"""


def build_optimization_prompt(
    source: Path,
    source_text: str,
    language: str,
    hardware: HardwareProfile,
    findings: list[Finding],
    profile_data: Optional[ProfileData],
    iteration: int,
) -> list[dict]:
    """Return the messages list for the Anthropic API call."""

    # Format findings
    findings_block = ""
    if findings:
        findings_block = "\n## Static Analysis Findings\n"
        for i, f in enumerate(findings[:20], 1):  # cap at 20 to stay within context
            findings_block += (
                f"\n{i}. [{f.severity.value.upper()}] Line {f.line}: {f.message}\n"
                f"   → {f.suggestion}\n"
            )

    # Format profiler hotspots
    profile_block = ""
    if profile_data and profile_data.hotspots:
        profile_block = "\n## Profiler Hotspots\n"
        for h in profile_data.top_hotspots(5):
            profile_block += (
                f"\n- `{h.function}` — {h.cpu_time_pct:.1f}% CPU time"
            )
            if h.cpi:
                profile_block += f", CPI={h.cpi:.2f}"
            if h.llc_miss_rate:
                profile_block += f", LLC-miss={h.llc_miss_rate*100:.1f}%"
            if h.mem_bound_pct:
                profile_block += f", Mem-bound={h.mem_bound_pct*100:.1f}%"
            profile_block += "\n"

    # Hardware context
    simd_str = hardware.simd.instruction_set if hardware.simd else "scalar"
    gpu_str  = (f"\nGPU: {hardware.gpu.name} — {hardware.gpu.memory_bandwidth_gbs} GB/s HBM, "
                f"FP64={hardware.gpu.peak_fp64_tflops} TFLOPs, CC={hardware.gpu.compute_capability}"
                if hardware.gpu else "No GPU")

    hw_block = f"""
## Target Hardware: {hardware.name}
- CPU: {hardware.total_cores} cores ({hardware.sockets} sockets × {hardware.cores_per_socket}C)
- SIMD: {simd_str} ({hardware.simd.vector_width_bits if hardware.simd else 0}-bit vectors)
- Cache: L1d={hardware.l1d_kb}KB  L2={hardware.l2_kb}KB  L3={hardware.l3_mb}MB
- Memory: {hardware.memory_bandwidth_gbs} GB/s {hardware.memory_type}
- Peak FP64: {hardware.peak_dp_gflops_socket * hardware.sockets / 1000:.1f} TFLOP/s (CPU){gpu_str}
- Recommended flags: {' '.join(hardware.recommended_cflags[:6])}
"""

    user_message = f"""
# PerfLens Optimization Request (Iteration {iteration})

## Source File: `{source.name}` ({language.upper()})
{hw_block}
{findings_block}
{profile_block}

## Source Code
```{language}
{source_text}
```

Please analyze this code and produce:
1. The JSON patch list (as specified in your system prompt)
2. The complete rewritten source between <optimized_source> tags

Focus on the highest-impact transformations for the target hardware above.
Prioritize: {"GPU offload and memory coalescing" if hardware.gpu else "AVX-512 vectorization and cache blocking"}.
"""

    return [
        {"role": "user", "content": user_message},
    ]
