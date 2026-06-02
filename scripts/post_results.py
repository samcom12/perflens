#!/usr/bin/env python3
"""
post_results.py — Post benchmark results to the PerfLens dashboard REST API.

Usage:
    python3 scripts/post_results.py summary.csv --hw a100 --source solver.c
    python3 scripts/post_results.py --vtune-csv hotspots.csv --hw a100 --source solver.c
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    import urllib.request as _urllib
    requests = None  # type: ignore[assignment]


def post_json(url: str, payload: dict) -> int:
    """POST JSON payload; returns HTTP status code."""
    body = json.dumps(payload).encode()
    if requests:
        r = requests.post(url, json=payload, timeout=10)
        return r.status_code
    else:
        req = _urllib.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with _urllib.urlopen(req, timeout=10) as resp:
            return resp.status


def post_summary_csv(path: Path, hw: str, source: str, api_url: str) -> None:
    """Read a perflens summary.csv and POST each row to the dashboard."""
    with open(path) as f:
        rows = list(csv.DictReader(f))

    for row in rows:
        label  = row.get("label", "unknown")
        rt_ms  = float(row["runtime_ms"]) if row.get("runtime_ms", "N/A") != "N/A" else None
        spd    = float(row["speedup"])    if row.get("speedup", "N/A") not in ("N/A", "1.0") else None

        payload = {
            "label":       label,
            "source_file": source,
            "hw_profile":  hw,
            "iteration":   _parse_iter(label),
            "runtime_ms":  rt_ms,
            "speedup":     spd,
        }

        try:
            status = post_json(f"{api_url}/api/runs", payload)
            print(f"  POST {label}: HTTP {status}")
        except Exception as exc:
            print(f"  ERROR posting {label}: {exc}", file=sys.stderr)


def post_vtune_csv(path: Path, hw: str, source: str, api_url: str) -> None:
    """Parse a VTune hotspot CSV and POST hotspot data to the dashboard."""
    from perflens.profiler.vtune_parser import VTuneParser
    pd = VTuneParser().parse(report_path=path, source=Path(source) if source else None)

    hotspots = [
        {
            "function": h.function,
            "cpu_pct":  h.cpu_time_pct,
            "cpu_ms":   h.cpu_time_ms,
            "ai":       h.arithmetic_intensity,
            "gflops":   h.gflops,
        }
        for h in pd.top_hotspots(15)
    ]

    roofline = [
        {
            "label":  r.label,
            "ai":     r.arithmetic_intensity,
            "gflops": r.achieved_gflops,
        }
        for r in pd.roofline_points
    ]

    payload = {
        "label":       f"vtune:{path.stem}",
        "source_file": source,
        "hw_profile":  hw,
        "iteration":   0,
        "runtime_ms":  pd.total_time_ms or None,
        "hotspots":    hotspots,
        "roofline_points": roofline,
    }

    try:
        status = post_json(f"{api_url}/api/runs", payload)
        print(f"  POST vtune profile: HTTP {status}  ({len(hotspots)} hotspots)")
    except Exception as exc:
        print(f"  ERROR: {exc}", file=sys.stderr)


def _parse_iter(label: str) -> int:
    import re
    m = re.search(r"iter[_\s]*(\d+)", label, re.IGNORECASE)
    return int(m.group(1)) if m else 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Post PerfLens results to dashboard")
    parser.add_argument("summary_csv", nargs="?", help="perflens summary.csv path")
    parser.add_argument("--vtune-csv", help="VTune hotspot CSV to post as profiler data")
    parser.add_argument("--hw",     default="auto",  help="Hardware profile ID")
    parser.add_argument("--source", default="",      help="Source file path label")
    parser.add_argument("--api",    default="http://localhost:8080",
                        help="Dashboard API base URL")
    args = parser.parse_args()

    if not args.summary_csv and not args.vtune_csv:
        parser.print_help()
        sys.exit(1)

    if args.summary_csv:
        p = Path(args.summary_csv)
        if not p.exists():
            print(f"ERROR: {p} not found", file=sys.stderr)
            sys.exit(1)
        print(f"Posting summary: {p}")
        post_summary_csv(p, hw=args.hw, source=args.source, api_url=args.api)

    if args.vtune_csv:
        p = Path(args.vtune_csv)
        if not p.exists():
            print(f"ERROR: {p} not found", file=sys.stderr)
            sys.exit(1)
        print(f"Posting VTune profile: {p}")
        post_vtune_csv(p, hw=args.hw, source=args.source, api_url=args.api)

    print("Done.")


if __name__ == "__main__":
    main()
