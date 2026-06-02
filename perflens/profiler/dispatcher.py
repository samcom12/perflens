"""Route profile parsing to the correct backend."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from perflens.profiler.models import ProfileData


def parse_profile(
    tool: str,
    report_path: Optional[Path],
    source: Optional[Path] = None,
) -> ProfileData:
    tool = tool.lower().strip()

    if tool == "vtune":
        from perflens.profiler.vtune_parser import VTuneParser
        return VTuneParser().parse(report_path=report_path, source=source)

    elif tool in ("hpctoolkit", "hpc"):
        from perflens.profiler.hpctoolkit_parser import HPCToolkitParser
        return HPCToolkitParser().parse(report_path=report_path, source=source)

    else:
        raise ValueError(f"Unknown profiling tool: '{tool}'. Supported: vtune, hpctoolkit")
