"""Auto-detect hardware and return the best matching profile."""

from __future__ import annotations

import platform
import re
import shutil
import subprocess
from pathlib import Path
from typing import Optional

from perflens.hardware.database import HardwareDatabase
from perflens.hardware.models import HardwareProfile


def _read_cpuinfo() -> str:
    try:
        return Path("/proc/cpuinfo").read_text()
    except Exception:
        return ""


def _run(cmd: list[str]) -> str:
    try:
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True)
    except Exception:
        return ""


def _detect_gpu() -> Optional[str]:
    """Return a profile_id hint based on detected GPU."""
    nvidia_smi = shutil.which("nvidia-smi")
    if not nvidia_smi:
        return None
    out = _run([nvidia_smi, "--query-gpu=name", "--format=csv,noheader"])
    if not out:
        return None
    name = out.splitlines()[0].lower()
    if "a100" in name:
        return "a100"
    if "h100" in name:
        return "h100"
    if "v100" in name:
        return "v100"
    if "a30" in name or "a40" in name or "a10" in name:
        return "a100"  # close enough for optimization hints
    return None


def _detect_cpu_profile() -> Optional[str]:
    """Map CPU model name to a profile_id."""
    cpuinfo = _read_cpuinfo()
    model_line = ""
    for line in cpuinfo.splitlines():
        if "model name" in line.lower():
            model_line = line.lower()
            break
    if not model_line:
        # macOS fallback
        model_line = _run(["sysctl", "-n", "machdep.cpu.brand_string"]).lower()

    if "a64fx" in model_line:
        return "a64fx"
    if re.search(r"(8480|8462|8468|sapphire)", model_line):
        return "intel_spr"
    if re.search(r"(8352|8360|8358|ice lake|icelake)", model_line):
        return "intel_icx"
    if re.search(r"(9654|9534|9454|epyc 9)", model_line):
        return "amd_genoa"
    if re.search(r"(7763|7713|7543|epyc 7)", model_line):
        return "amd_milan"
    if re.search(r"(graviton3|neoverse v1)", model_line):
        return "graviton3"
    return None


def detect_hardware() -> HardwareProfile:
    """
    Detect the current system hardware and return the best matching profile.

    Detection order:
      1. GPU (nvidia-smi) — GPU profiles take precedence on GPU clusters
      2. CPU model name — matched against known CPUs
      3. Fallback to intel_icx (common baseline)
    """
    db = HardwareDatabase()

    gpu_hint = _detect_gpu()
    cpu_hint = _detect_cpu_profile()

    # Prefer GPU-tier profiles when a known GPU is present
    profile_id = gpu_hint or cpu_hint or "intel_icx"

    profile = db.get(profile_id)
    assert profile is not None  # all built-ins guaranteed to exist
    return profile
