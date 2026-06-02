from __future__ import annotations

import json
import os
import platform
from importlib import resources
from pathlib import Path

from .models import HardwareSpec


class HardwareDB:
    def __init__(self, user_db: str | Path | None = None) -> None:
        self._specs: dict[str, HardwareSpec] = {}
        self._load_builtin()
        if user_db:
            self.load_file(user_db)

    def _load_builtin(self) -> None:
        data_file = resources.files("perflens").joinpath("data/hardware.json")
        data = json.loads(data_file.read_text(encoding="utf-8"))
        for item in data["hardware"]:
            spec = HardwareSpec.from_dict(item)
            self._specs[spec.id] = spec

    def load_file(self, path: str | Path) -> None:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        entries = data.get("hardware", data if isinstance(data, list) else [])
        for item in entries:
            spec = HardwareSpec.from_dict(item)
            self._specs[spec.id] = spec

    def list_specs(self) -> list[HardwareSpec]:
        return [self._specs[key] for key in sorted(self._specs)]

    def get(self, hardware_id: str) -> HardwareSpec:
        try:
            return self._specs[hardware_id]
        except KeyError as exc:
            choices = ", ".join(sorted(self._specs))
            raise KeyError(f"Unknown hardware id '{hardware_id}'. Choices: {choices}") from exc

    def probe_local(self) -> HardwareSpec:
        return HardwareSpec(
            id="local-probe",
            vendor=platform.processor() or platform.machine() or "unknown",
            model=platform.platform(),
            kind="cpu",
            cores=os.cpu_count(),
            threads=os.cpu_count(),
            simd=[],
            memory={},
            gpu={},
            compilers=[],
            tune_hints=[
                "Use this local probe as a starting point; add SIMD, cache, memory, and compiler details for better tuning.",
                "Run compiler vectorization reports and profiler exports on the target HPC node, not only on a login node.",
            ],
        )

