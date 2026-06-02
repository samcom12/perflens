from __future__ import annotations

from pathlib import Path
from typing import Any

from .dashboard import generate_dashboard
from .hardware import HardwareDB
from .io import write_json
from .models import ProfileReport, ValidationReport
from .optimizer import recommend_optimizations
from .profiles import parse_profile
from .scanner import scan_path
from .validator import run_validation


def analyze_project(
    path: str | Path,
    profile_path: str | Path | None = None,
    profile_kind: str = "auto",
    hardware_id: str = "generic-x86-64",
    config_path: str | Path | None = None,
    out_dir: str | Path = ".perflens",
    dashboard_dir: str | Path | None = None,
    use_clang: str = "auto",
) -> dict[str, Any]:
    output = Path(out_dir)
    output.mkdir(parents=True, exist_ok=True)

    scan = scan_path(path, use_clang=use_clang)
    scan_path_json = write_json(output / "scan.json", scan)

    profile: ProfileReport | None = None
    profile_json = None
    if profile_path:
        profile = parse_profile(profile_path, kind=profile_kind)
        profile_json = write_json(output / "profile.json", profile)

    hardware = HardwareDB().get(hardware_id)
    plan = recommend_optimizations(scan, profile=profile, hardware=hardware)
    plan_json = write_json(output / "plan.json", plan)

    validation: ValidationReport | None = None
    validation_json = None
    if config_path:
        validation = run_validation(config_path)
        validation_json = write_json(output / "validation.json", validation)

    dashboard_output = None
    if dashboard_dir:
        dashboard_output = generate_dashboard(
            dashboard_dir,
            scan=scan,
            profile=profile,
            plan=plan,
            validation=validation,
        )

    return {
        "scan": str(scan_path_json),
        "profile": str(profile_json) if profile_json else None,
        "plan": str(plan_json),
        "validation": str(validation_json) if validation_json else None,
        "dashboard": str(dashboard_output) if dashboard_output else None,
    }

