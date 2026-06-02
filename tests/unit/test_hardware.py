"""Unit tests for perflens.hardware."""

from __future__ import annotations

import pytest

from perflens.hardware.database import HardwareDatabase
from perflens.hardware.models import HardwareProfile, GPUCapability, SIMDCapability


@pytest.fixture
def db():
    return HardwareDatabase()


# ── Database lookup ───────────────────────────────────────────────────────────

def test_all_builtin_profiles_loadable(db):
    ids = db.list_ids()
    assert len(ids) >= 7  # a100, h100, v100, intel_spr, intel_icx, amd_genoa, amd_milan, a64fx, graviton3


@pytest.mark.parametrize("profile_id", [
    "a100", "h100", "v100", "intel_spr", "intel_icx",
    "amd_genoa", "amd_milan", "a64fx", "graviton3",
])
def test_known_profiles_exist(db, profile_id):
    hw = db.get(profile_id)
    assert hw is not None, f"Profile '{profile_id}' not found"
    assert isinstance(hw, HardwareProfile)


def test_unknown_profile_returns_none(db):
    assert db.get("nonexistent_hw_xyz") is None


def test_case_insensitive_lookup(db):
    assert db.get("A100") is not None
    assert db.get("Intel_SPR") is not None


# ── A100 profile integrity ────────────────────────────────────────────────────

def test_a100_profile_gpu(db):
    hw = db.get("a100")
    assert hw.gpu is not None
    assert hw.gpu.compute_capability == "8.0"
    assert hw.gpu.memory_bandwidth_gbs == 2000.0
    assert hw.gpu.peak_fp64_tflops == 9.7
    assert hw.gpu.vram_gb == 80


def test_a100_profile_cpu(db):
    hw = db.get("a100")
    assert hw.total_cores == 72          # 2 sockets × 36 cores
    assert hw.total_threads == 144
    assert hw.simd is not None
    assert hw.simd.instruction_set == "AVX-512"
    assert hw.simd.vector_width_bits == 512


def test_a100_has_recommended_flags(db):
    hw = db.get("a100")
    flags = " ".join(hw.recommended_cflags)
    assert "-O3" in flags
    assert "-fopenmp" in flags
    assert "avx512" in flags.lower()


# ── H100 profile ──────────────────────────────────────────────────────────────

def test_h100_higher_bandwidth_than_a100(db):
    a100 = db.get("a100")
    h100 = db.get("h100")
    assert h100.gpu.memory_bandwidth_gbs > a100.gpu.memory_bandwidth_gbs
    assert h100.gpu.peak_fp64_tflops > a100.gpu.peak_fp64_tflops


def test_h100_compute_capability(db):
    hw = db.get("h100")
    assert hw.gpu.compute_capability == "9.0"


# ── Intel Sapphire Rapids ─────────────────────────────────────────────────────

def test_intel_spr_no_gpu(db):
    hw = db.get("intel_spr")
    assert hw.gpu is None


def test_intel_spr_core_count(db):
    hw = db.get("intel_spr")
    assert hw.cores_per_socket == 60
    assert hw.sockets == 2
    assert hw.total_cores == 120


def test_intel_spr_avx512(db):
    hw = db.get("intel_spr")
    assert hw.simd.instruction_set == "AVX-512"


# ── A64FX (Fugaku) ─────────────────────────────────────────────────────────────

def test_a64fx_hbm_bandwidth(db):
    hw = db.get("a64fx")
    # A64FX has very high memory bandwidth for an CPU node
    assert hw.memory_bandwidth_gbs >= 800.0


def test_a64fx_sve(db):
    hw = db.get("a64fx")
    assert hw.simd.instruction_set == "SVE-512"
    assert hw.simd.vector_width_bits == 512


def test_a64fx_single_socket(db):
    hw = db.get("a64fx")
    assert hw.sockets == 1


# ── HardwareProfile computed properties ───────────────────────────────────────

def test_total_cores_computed():
    hw = HardwareProfile(
        profile_id="test", name="Test", vendor="test", arch="test",
        cores_per_socket=16, sockets=4, threads_per_core=2,
        base_freq_ghz=2.0, boost_freq_ghz=3.0,
        l1d_kb=32, l1i_kb=32, l2_kb=256, l3_mb=16,
    )
    assert hw.total_cores == 64
    assert hw.total_threads == 128


def test_to_dict_serializable(db):
    import json
    hw = db.get("a100")
    d = hw.to_dict()
    # Must be JSON-serialisable
    json.dumps(d)
    assert d["profile_id"] == "a100"


# ── list_ids ordering ──────────────────────────────────────────────────────────

def test_list_ids_sorted(db):
    ids = db.list_ids()
    assert ids == sorted(ids)
