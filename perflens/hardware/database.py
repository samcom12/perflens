"""
Built-in hardware profile database.

Profiles cover:
  - NVIDIA A100, V100, H100 (GPU cluster targets)
  - Intel Sapphire Rapids, Ice Lake, Skylake
  - AMD EPYC Genoa, Milan, Rome
  - Fujitsu A64FX (Fugaku)
  - AWS Graviton3 (ARM Neoverse V1)
"""

from __future__ import annotations

from typing import Optional

from rich.console import Console
from rich.table import Table
from rich import box

from perflens.hardware.models import GPUCapability, HardwareProfile, SIMDCapability


def _build_profiles() -> dict[str, HardwareProfile]:
    profiles: dict[str, HardwareProfile] = {}

    # ── NVIDIA A100 80GB node (2× Intel Xeon Platinum 8360Y + 4× A100) ──────
    profiles["a100"] = HardwareProfile(
        profile_id="a100",
        name="NVIDIA A100 80GB SXM4 Node",
        vendor="nvidia",
        arch="ampere",
        cores_per_socket=36, sockets=2, threads_per_core=2,
        base_freq_ghz=2.4, boost_freq_ghz=3.5,
        l1d_kb=48, l1i_kb=32, l2_kb=1280, l3_mb=54,
        memory_bandwidth_gbs=204.8, memory_capacity_gb=512,
        memory_type="DDR4-3200", numa_domains=2,
        simd=SIMDCapability("AVX-512", 512, fma_supported=True, double_throughput=2.0),
        gpu=GPUCapability(
            name="NVIDIA A100 SXM4 80GB",
            arch="ampere",
            sm_count=108, cuda_cores_per_sm=64, tensor_cores_per_sm=4,
            memory_type="HBM2e", vram_gb=80,
            memory_bandwidth_gbs=2000.0,
            peak_fp32_tflops=19.5,
            peak_fp64_tflops=9.7,
            peak_tf32_tflops=156.0,
            peak_bf16_tflops=312.0,
            nvlink_bandwidth_gbs=600.0,
            compute_capability="8.0",
        ),
        interconnect="NVLink 3.0 / InfiniBand HDR 200",
        interconnect_bandwidth_gbs=25.0,
        peak_dp_gflops_socket=4147.2,   # 36C × 2FMA × 8wide × 3.6GHz
        peak_sp_gflops_socket=8294.4,
        recommended_cflags=["-O3", "-march=icelake-server", "-fopenmp",
                             "-ffast-math", "-funroll-loops", "-mavx512f"],
        recommended_fflags=["-O3", "-march=icelake-server", "-fopenmp",
                             "-ffast-math", "-mavx512f"],
        notes="CDAC Param Prabha cluster node. Use -gpu=cc80 with nvc for OpenMP offload to A100.",
    )

    # ── NVIDIA H100 SXM5 ─────────────────────────────────────────────────────
    profiles["h100"] = HardwareProfile(
        profile_id="h100",
        name="NVIDIA H100 SXM5 80GB Node",
        vendor="nvidia",
        arch="hopper",
        cores_per_socket=48, sockets=2, threads_per_core=2,
        base_freq_ghz=2.0, boost_freq_ghz=3.5,
        l1d_kb=48, l1i_kb=32, l2_kb=2048, l3_mb=60,
        memory_bandwidth_gbs=307.2, memory_capacity_gb=1024,
        memory_type="DDR5-4800", numa_domains=2,
        simd=SIMDCapability("AVX-512", 512, fma_supported=True, double_throughput=2.0),
        gpu=GPUCapability(
            name="NVIDIA H100 SXM5 80GB",
            arch="hopper",
            sm_count=132, cuda_cores_per_sm=128, tensor_cores_per_sm=4,
            memory_type="HBM3", vram_gb=80,
            memory_bandwidth_gbs=3350.0,
            peak_fp32_tflops=67.0,
            peak_fp64_tflops=33.5,
            peak_tf32_tflops=494.7,
            peak_bf16_tflops=989.4,
            nvlink_bandwidth_gbs=900.0,
            compute_capability="9.0",
        ),
        interconnect="NVLink 4.0 / InfiniBand NDR 400",
        interconnect_bandwidth_gbs=50.0,
        peak_dp_gflops_socket=6553.6,
        peak_sp_gflops_socket=13107.2,
        recommended_cflags=["-O3", "-march=sapphirerapids", "-fopenmp", "-ffast-math", "-mavx512f"],
        recommended_fflags=["-O3", "-march=sapphirerapids", "-fopenmp", "-ffast-math", "-mavx512f"],
        notes="H100 SXM5 — use -gpu=cc90 with nvc for OpenMP offload / CUDA Hopper features.",
    )

    # ── NVIDIA V100 32GB ─────────────────────────────────────────────────────
    profiles["v100"] = HardwareProfile(
        profile_id="v100",
        name="NVIDIA V100 SXM2 32GB Node",
        vendor="nvidia",
        arch="volta",
        cores_per_socket=20, sockets=2, threads_per_core=2,
        base_freq_ghz=2.1, boost_freq_ghz=3.0,
        l1d_kb=32, l1i_kb=32, l2_kb=1024, l3_mb=27.5,
        memory_bandwidth_gbs=153.6, memory_capacity_gb=384,
        memory_type="DDR4-2666", numa_domains=2,
        simd=SIMDCapability("AVX-512", 512, fma_supported=True, double_throughput=2.0),
        gpu=GPUCapability(
            name="NVIDIA V100 SXM2 32GB",
            arch="volta",
            sm_count=80, cuda_cores_per_sm=64, tensor_cores_per_sm=8,
            memory_type="HBM2", vram_gb=32,
            memory_bandwidth_gbs=900.0,
            peak_fp32_tflops=14.0,
            peak_fp64_tflops=7.0,
            peak_tf32_tflops=14.0,
            peak_bf16_tflops=28.0,
            nvlink_bandwidth_gbs=300.0,
            compute_capability="7.0",
        ),
        interconnect="NVLink 2.0 / InfiniBand EDR",
        interconnect_bandwidth_gbs=12.5,
        peak_dp_gflops_socket=2150.0,
        peak_sp_gflops_socket=4300.0,
        recommended_cflags=["-O3", "-march=skylake-avx512", "-fopenmp", "-ffast-math", "-mavx512f"],
        recommended_fflags=["-O3", "-march=skylake-avx512", "-fopenmp", "-ffast-math"],
        notes="V100 SXM2 — use -gpu=cc70 with nvc. Tensor cores support FP16 only (no BF16 native).",
    )

    # ── Intel Sapphire Rapids ─────────────────────────────────────────────────
    profiles["intel_spr"] = HardwareProfile(
        profile_id="intel_spr",
        name="Intel Xeon Sapphire Rapids (8480+)",
        vendor="intel",
        arch="sapphire_rapids",
        cores_per_socket=60, sockets=2, threads_per_core=2,
        base_freq_ghz=2.0, boost_freq_ghz=3.8,
        l1d_kb=48, l1i_kb=32, l2_kb=2048, l3_mb=60,
        memory_bandwidth_gbs=307.2, memory_capacity_gb=1024,
        memory_type="DDR5-4800", numa_domains=2,
        simd=SIMDCapability("AVX-512", 512, fma_supported=True, double_throughput=2.0),
        interconnect="InfiniBand HDR 200",
        interconnect_bandwidth_gbs=25.0,
        peak_dp_gflops_socket=7680.0,   # 60C × 2FMA × 8wide FP64 × 4.0GHz
        peak_sp_gflops_socket=15360.0,
        recommended_cflags=["-O3", "-march=sapphirerapids", "-fopenmp",
                             "-ffast-math", "-funroll-loops", "-mavx512f",
                             "-mavx512bf16", "-mavx512vnni"],
        recommended_fflags=["-O3", "-march=sapphirerapids", "-fopenmp",
                             "-ffast-math", "-mavx512f"],
        notes="Use Intel ICX/IFORT compilers for best AVX-512 auto-vectorization. "
              "Enable -xCORE-AVX512 with icx.",
    )

    # ── Intel Ice Lake ────────────────────────────────────────────────────────
    profiles["intel_icx"] = HardwareProfile(
        profile_id="intel_icx",
        name="Intel Xeon Ice Lake (8352Y)",
        vendor="intel",
        arch="ice_lake",
        cores_per_socket=32, sockets=2, threads_per_core=2,
        base_freq_ghz=2.2, boost_freq_ghz=3.4,
        l1d_kb=48, l1i_kb=32, l2_kb=1280, l3_mb=48,
        memory_bandwidth_gbs=204.8, memory_capacity_gb=512,
        memory_type="DDR4-3200", numa_domains=2,
        simd=SIMDCapability("AVX-512", 512, fma_supported=True, double_throughput=2.0),
        peak_dp_gflops_socket=3686.4,
        peak_sp_gflops_socket=7372.8,
        recommended_cflags=["-O3", "-march=icelake-server", "-fopenmp", "-ffast-math", "-mavx512f"],
        recommended_fflags=["-O3", "-march=icelake-server", "-fopenmp", "-ffast-math"],
    )

    # ── AMD EPYC Genoa ────────────────────────────────────────────────────────
    profiles["amd_genoa"] = HardwareProfile(
        profile_id="amd_genoa",
        name="AMD EPYC Genoa (9654)",
        vendor="amd",
        arch="genoa",
        cores_per_socket=96, sockets=2, threads_per_core=2,
        base_freq_ghz=2.4, boost_freq_ghz=3.7,
        l1d_kb=32, l1i_kb=32, l2_kb=1024, l3_mb=384,
        memory_bandwidth_gbs=460.8, memory_capacity_gb=1536,
        memory_type="DDR5-4800", numa_domains=12,
        simd=SIMDCapability("AVX-512", 512, fma_supported=True, double_throughput=2.0),
        peak_dp_gflops_socket=5734.4,
        peak_sp_gflops_socket=11468.8,
        recommended_cflags=["-O3", "-march=znver4", "-fopenmp", "-ffast-math",
                             "-funroll-loops", "-mavx512f"],
        recommended_fflags=["-O3", "-march=znver4", "-fopenmp", "-ffast-math"],
        notes="Genoa has 12 NUMA domains per socket — pin MPI ranks carefully. "
              "Use numactl --localalloc for best memory bandwidth.",
    )

    # ── AMD EPYC Milan ────────────────────────────────────────────────────────
    profiles["amd_milan"] = HardwareProfile(
        profile_id="amd_milan",
        name="AMD EPYC Milan (7763)",
        vendor="amd",
        arch="milan",
        cores_per_socket=64, sockets=2, threads_per_core=2,
        base_freq_ghz=2.45, boost_freq_ghz=3.5,
        l1d_kb=32, l1i_kb=32, l2_kb=512, l3_mb=256,
        memory_bandwidth_gbs=204.8, memory_capacity_gb=512,
        memory_type="DDR4-3200", numa_domains=8,
        simd=SIMDCapability("AVX2", 256, fma_supported=True, double_throughput=1.0),
        peak_dp_gflops_socket=2867.2,
        peak_sp_gflops_socket=5734.4,
        recommended_cflags=["-O3", "-march=znver3", "-fopenmp", "-ffast-math"],
        recommended_fflags=["-O3", "-march=znver3", "-fopenmp", "-ffast-math"],
    )

    # ── Fujitsu A64FX (Fugaku) ────────────────────────────────────────────────
    profiles["a64fx"] = HardwareProfile(
        profile_id="a64fx",
        name="Fujitsu A64FX (Fugaku node)",
        vendor="fujitsu",
        arch="a64fx",
        cores_per_socket=48, sockets=1, threads_per_core=1,
        base_freq_ghz=2.0, boost_freq_ghz=2.2,
        l1d_kb=64, l1i_kb=64, l2_kb=8192, l3_mb=0,
        memory_bandwidth_gbs=1024.0, memory_capacity_gb=32,
        memory_type="HBM2", numa_domains=4,
        simd=SIMDCapability("SVE-512", 512, fma_supported=True, double_throughput=4.0),
        peak_dp_gflops_socket=3072.0,   # 48C × 2FMA × 8wide × 2.0GHz × 2 ports
        peak_sp_gflops_socket=6144.0,
        recommended_cflags=["-O3", "-mcpu=a64fx", "-fopenmp", "-ffast-math",
                             "-msve-vector-bits=512"],
        recommended_fflags=["-O3", "-mcpu=a64fx", "-fopenmp", "-ffast-math"],
        notes="No L3 cache — relies on HBM2 bandwidth. Use tofuchk for A64FX-specific profiling.",
    )

    # ── AWS Graviton3 (ARM Neoverse V1) ──────────────────────────────────────
    profiles["graviton3"] = HardwareProfile(
        profile_id="graviton3",
        name="AWS Graviton3 (Neoverse V1)",
        vendor="arm",
        arch="neoverse_v1",
        cores_per_socket=64, sockets=1, threads_per_core=1,
        base_freq_ghz=2.6, boost_freq_ghz=2.6,
        l1d_kb=64, l1i_kb=64, l2_kb=1024, l3_mb=32,
        memory_bandwidth_gbs=307.0, memory_capacity_gb=512,
        memory_type="DDR5", numa_domains=1,
        simd=SIMDCapability("SVE-256", 256, fma_supported=True, double_throughput=2.0),
        peak_dp_gflops_socket=2662.4,
        peak_sp_gflops_socket=5324.8,
        recommended_cflags=["-O3", "-march=armv8.4-a+sve", "-fopenmp", "-ffast-math"],
        recommended_fflags=["-O3", "-march=armv8.4-a+sve", "-fopenmp", "-ffast-math"],
        notes="Graviton3 has native BF16 support. Use -march=armv8.6-a+bf16 for BF16 workloads.",
    )

    return profiles


class HardwareDatabase:
    def __init__(self):
        self._profiles: dict[str, HardwareProfile] = _build_profiles()

    def get(self, profile_id: str) -> Optional[HardwareProfile]:
        return self._profiles.get(profile_id.lower())

    def list_ids(self) -> list[str]:
        return sorted(self._profiles.keys())

    def all(self) -> list[HardwareProfile]:
        return [self._profiles[k] for k in sorted(self._profiles)]

    def print_all(self, console: Console) -> None:
        table = Table(title="PerfLens Hardware Profiles", box=box.ROUNDED, show_lines=True)
        table.add_column("ID",            width=14, style="cyan bold")
        table.add_column("Name",          width=38)
        table.add_column("Vendor",        width=9)
        table.add_column("Cores",         width=7, justify="right")
        table.add_column("SIMD",          width=10)
        table.add_column("Mem BW (GB/s)", width=14, justify="right")
        table.add_column("GPU",           width=25)
        table.add_column("Peak FP64 (T)", width=14, justify="right")

        for hw in self.all():
            gpu_name = hw.gpu.name if hw.gpu else "—"
            peak_tf  = hw.peak_dp_gflops_socket * hw.sockets / 1000
            simd_str = hw.simd.instruction_set if hw.simd else "—"
            table.add_row(
                hw.profile_id,
                hw.name,
                hw.vendor,
                str(hw.total_cores),
                simd_str,
                f"{hw.memory_bandwidth_gbs:.0f}",
                gpu_name[:24],
                f"{peak_tf:.2f}",
            )
        console.print(table)
