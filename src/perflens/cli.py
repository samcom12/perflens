from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .dashboard import generate_dashboard
from .hardware import HardwareDB
from .io import read_json, write_json
from .models import OptimizationPlan, ProfileReport, ScanReport, ValidationReport, to_plain_data
from .optimizer import ExternalLLMOptimizer, recommend_optimizations
from .profiles import parse_profile
from .scanner import scan_path
from .validator import run_validation
from .workflow import analyze_project


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except BrokenPipeError:
        return 1
    except Exception as exc:  # pragma: no cover - CLI guard
        print(f"perflens: error: {exc}", file=sys.stderr)
        return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="perflens",
        description="HPC performance optimization analysis workflow.",
    )
    parser.add_argument("--version", action="version", version=f"perflens {__version__}")
    sub = parser.add_subparsers(required=True)

    scan = sub.add_parser("scan", help="Scan a C/C++/Fortran/Python source tree.")
    scan.add_argument("path")
    scan.add_argument("-o", "--output")
    scan.add_argument("--clang", default="auto", choices=["auto", "true", "false"])
    scan.set_defaults(func=_cmd_scan)

    parse = sub.add_parser("parse-profile", help="Parse HPCToolkit or VTune exports.")
    parse.add_argument("profile")
    parse.add_argument("--kind", default="auto", choices=["auto", "vtune", "hpctoolkit", "json"])
    parse.add_argument("-o", "--output")
    parse.set_defaults(func=_cmd_parse_profile)

    hardware = sub.add_parser("hardware", help="Inspect hardware database.")
    hardware_sub = hardware.add_subparsers(required=True)
    hardware_list = hardware_sub.add_parser("list", help="List hardware ids.")
    hardware_list.add_argument("-o", "--output")
    hardware_list.set_defaults(func=_cmd_hardware_list)
    hardware_show = hardware_sub.add_parser("show", help="Show one hardware entry.")
    hardware_show.add_argument("hardware_id")
    hardware_show.add_argument("-o", "--output")
    hardware_show.set_defaults(func=_cmd_hardware_show)
    hardware_probe = hardware_sub.add_parser("probe", help="Probe local machine basics.")
    hardware_probe.add_argument("-o", "--output")
    hardware_probe.set_defaults(func=_cmd_hardware_probe)

    recommend = sub.add_parser("recommend", help="Create an optimization plan.")
    recommend.add_argument("--scan", required=True)
    recommend.add_argument("--profile")
    recommend.add_argument("--hardware", default="generic-x86-64")
    recommend.add_argument("--hardware-db")
    recommend.add_argument("--llm", action="store_true", help="Invoke PERFLENS_LLM_COMMAND for patch candidates.")
    recommend.add_argument("-o", "--output")
    recommend.set_defaults(func=_cmd_recommend)

    validate = sub.add_parser("validate", help="Run validation and benchmark commands.")
    validate.add_argument("--config", required=True)
    validate.add_argument("--timeout", type=int, default=300)
    validate.add_argument("-o", "--output")
    validate.set_defaults(func=_cmd_validate)

    dashboard = sub.add_parser("dashboard", help="Generate a static HTML dashboard.")
    dashboard.add_argument("--scan", required=True)
    dashboard.add_argument("--plan", required=True)
    dashboard.add_argument("--profile")
    dashboard.add_argument("--validation")
    dashboard.add_argument("-o", "--output-dir", default="reports/perflens")
    dashboard.set_defaults(func=_cmd_dashboard)

    analyze = sub.add_parser("analyze", help="Run scan, profile parse, recommendations, validation, and dashboard.")
    analyze.add_argument("path")
    analyze.add_argument("--profile")
    analyze.add_argument("--profile-kind", default="auto", choices=["auto", "vtune", "hpctoolkit", "json"])
    analyze.add_argument("--hardware", default="generic-x86-64")
    analyze.add_argument("--config")
    analyze.add_argument("--out-dir", default=".perflens")
    analyze.add_argument("--dashboard-dir", default="reports/perflens")
    analyze.add_argument("--clang", default="auto", choices=["auto", "true", "false"])
    analyze.set_defaults(func=_cmd_analyze)

    return parser


def _cmd_scan(args: argparse.Namespace) -> int:
    report = scan_path(args.path, use_clang=args.clang)
    return _emit(report, args.output)


def _cmd_parse_profile(args: argparse.Namespace) -> int:
    report = parse_profile(args.profile, kind=args.kind)
    return _emit(report, args.output)


def _cmd_hardware_list(args: argparse.Namespace) -> int:
    specs = HardwareDB().list_specs()
    payload = [{"id": spec.id, "vendor": spec.vendor, "model": spec.model, "kind": spec.kind} for spec in specs]
    return _emit(payload, args.output)


def _cmd_hardware_show(args: argparse.Namespace) -> int:
    spec = HardwareDB().get(args.hardware_id)
    return _emit(spec, args.output)


def _cmd_hardware_probe(args: argparse.Namespace) -> int:
    spec = HardwareDB().probe_local()
    return _emit(spec, args.output)


def _cmd_recommend(args: argparse.Namespace) -> int:
    scan = ScanReport.from_dict(read_json(args.scan))
    profile = ProfileReport.from_dict(read_json(args.profile)) if args.profile else None
    hardware = HardwareDB(args.hardware_db).get(args.hardware)
    plan = recommend_optimizations(scan, profile=profile, hardware=hardware)
    if args.llm:
        plan.prompt_bundle["llm_response"] = ExternalLLMOptimizer().generate_patches(plan.prompt_bundle)
    return _emit(plan, args.output)


def _cmd_validate(args: argparse.Namespace) -> int:
    report = run_validation(args.config, timeout=args.timeout)
    _emit(report, args.output)
    return 0 if report.passed else 1


def _cmd_dashboard(args: argparse.Namespace) -> int:
    scan = ScanReport.from_dict(read_json(args.scan))
    plan = OptimizationPlan.from_dict(read_json(args.plan))
    profile = ProfileReport.from_dict(read_json(args.profile)) if args.profile else None
    validation = ValidationReport.from_dict(read_json(args.validation)) if args.validation else None
    path = generate_dashboard(
        args.output_dir,
        scan=scan,
        profile=profile,
        plan=plan,
        validation=validation,
    )
    print(path)
    return 0


def _cmd_analyze(args: argparse.Namespace) -> int:
    result = analyze_project(
        args.path,
        profile_path=args.profile,
        profile_kind=args.profile_kind,
        hardware_id=args.hardware,
        config_path=args.config,
        out_dir=args.out_dir,
        dashboard_dir=args.dashboard_dir,
        use_clang=args.clang,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


def _emit(value: Any, output: str | None) -> int:
    if output:
        write_json(Path(output), value)
        print(output)
    else:
        print(json.dumps(to_plain_data(value), indent=2, sort_keys=True))
    return 0

