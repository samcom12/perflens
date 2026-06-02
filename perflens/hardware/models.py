"""Hardware capability data models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from rich.console import Console
from rich.table import Table
from rich import box


@dataclass
class CacheLevel:
    level: str          # "L1d", "L1i", "L2", "L3"
    size_kb: int
    associativity: int
    line_bytes: int = 64
    shared_per_cores: int = 1


@dataclass
class SIMDCapability:
    instruction_set: str   # "AVX-512", "AVX2", "SVE-512", "NEON", "CUDA"
    vector_width_bits: int
    fma_supported: bool = True
    double_throughput: float = 1.0  # ops/cycle for FP64


@dataclass
class GPUCapability:
    name: str
    arch: str             # "ampere", "hopper", "ada", "volta"
    sm_count: int
    cuda_cores_per_sm: int
    tensor_cores_per_sm: int
    memory_type: str      # "HBM2e", "HBM3", "GDDR6X"
    vram_gb: int
    memory_bandwidth_gbs: float
    peak_fp32_tflops: float
    peak_fp64_tflops: float
    peak_tf32_tflops: float
    peak_bf16_tflops: float
    nvlink_bandwidth_gbs: Optional[float] = None
    compute_capability: str = ""


@dataclass
class HardwareProfile:
    """Full hardware capability descriptor for one target platform."""
    profile_id: str
    name: str
    vendor: str              # "intel", "amd", "arm", "nvidia", "fujitsu"
    arch: str                # "sapphire_rapids", "genoa", "a100", ...

    # CPU
    cores_per_socket: int
    sockets: int
    threads_per_core: int
    base_freq_ghz: float
    boost_freq_ghz: float
    l1d_kb: int
    l1i_kb: int
    l2_kb: int
    l3_mb: int
    cache_line_bytes: int = 64

    # Memory
    memory_bandwidth_gbs: float = 0.0
    memory_capacity_gb: int = 0
    memory_type: str = "DDR5"
    numa_domains: int = 1

    # SIMD
    simd: Optional[SIMDCapability] = None

    # GPU (optional)
    gpu: Optional[GPUCapability] = None

    # Network
    interconnect: str = "InfiniBand HDR"
    interconnect_bandwidth_gbs: float = 25.0

    # Roofline peaks (CPU)
    peak_dp_gflops_socket: float = 0.0    # GFLOPs per socket (FP64)
    peak_sp_gflops_socket: float = 0.0    # GFLOPs per socket (FP32)

    # Compiler flags
    recommended_cflags: list[str] = field(default_factory=list)
    recommended_fflags: list[str] = field(default_factory=list)

    # Extra metadata
    notes: str = ""

    @property
    def total_cores(self) -> int:
        return self.cores_per_socket * self.sockets

    @property
    def total_threads(self) -> int:
        return self.total_cores * self.threads_per_core

    def print_summary(self, console: Console) -> None:
        console.print(f"\n[bold cyan]Hardware Profile:[/bold cyan] {self.name} ({self.profile_id})")
        console.print(f"  Vendor/Arch : {self.vendor} / {self.arch}")
        console.print(f"  CPU Cores   : {self.total_cores} ({self.sockets}S × {self.cores_per_socket}C × {self.threads_per_core}T)")
        console.print(f"  Frequency   : {self.base_freq_ghz} GHz base / {self.boost_freq_ghz} GHz boost")
        console.print(f"  Cache       : L1d={self.l1d_kb}KB  L2={self.l2_kb}KB  L3={self.l3_mb}MB")
        console.print(f"  Memory      : {self.memory_capacity_gb}GB {self.memory_type}  BW={self.memory_bandwidth_gbs} GB/s")
        if self.simd:
            console.print(f"  SIMD        : {self.simd.instruction_set} ({self.simd.vector_width_bits}-bit)")
        if self.gpu:
            console.print(f"  GPU         : {self.gpu.name}  {self.gpu.vram_gb}GB  BW={self.gpu.memory_bandwidth_gbs}GB/s  "
                          f"FP64={self.gpu.peak_fp64_tflops}TF")
        console.print(f"  Peak FP64   : {self.peak_dp_gflops_socket * self.sockets / 1000:.2f} TFLOP/s (CPU)")

    def print_full(self, console: Console) -> None:
        self.print_summary(console)
        if self.recommended_cflags:
            console.print(f"\n  [bold]Recommended CFLAGS:[/bold] {' '.join(self.recommended_cflags)}")
        if self.recommended_fflags:
            console.print(f"  [bold]Recommended FFLAGS:[/bold] {' '.join(self.recommended_fflags)}")
        if self.notes:
            console.print(f"\n  [dim]{self.notes}[/dim]")

    def to_dict(self) -> dict:
        import dataclasses
        return dataclasses.asdict(self)
