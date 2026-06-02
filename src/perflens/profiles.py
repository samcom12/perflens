from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from .io import utc_now
from .models import Hotspot, ProfileReport


def parse_profile(path: str | Path, kind: str = "auto") -> ProfileReport:
    target = Path(path)
    selected = kind.lower()
    if selected == "auto":
        selected = _detect_profile_kind(target)
    if selected == "vtune":
        return parse_vtune_csv(target)
    if selected == "hpctoolkit":
        return parse_hpctoolkit_text(target)
    if selected == "json":
        return parse_profile_json(target)
    raise ValueError(f"Unsupported profile kind: {kind}")


def parse_vtune_csv(path: str | Path) -> ProfileReport:
    target = Path(path)
    hotspots: list[Hotspot] = []
    with target.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            normalized = {_normalize_header(key): value for key, value in row.items()}
            function = _first(
                normalized,
                "function",
                "function stack",
                "symbol",
                "name",
            ) or "<unknown>"
            source_file = _first(
                normalized,
                "source file",
                "source",
                "file",
                "module",
            )
            line = _parse_int(_first(normalized, "line", "source line"))
            metric_name, value, unit = _extract_metric(normalized)
            if value is None:
                continue
            hotspots.append(
                Hotspot(
                    function=function,
                    file=source_file,
                    line=line,
                    metric=metric_name,
                    value=value,
                    unit=unit,
                    raw={key: value for key, value in row.items() if value not in {None, ""}},
                )
            )
    return ProfileReport(
        source=str(target),
        profiler="vtune",
        hotspots=_sort_hotspots(hotspots),
        generated_at=utc_now(),
        metadata={"format": "csv"},
    )


def parse_hpctoolkit_text(path: str | Path) -> ProfileReport:
    target = Path(path)
    hotspots: list[Hotspot] = []
    pattern = re.compile(
        r"(?P<percent>\d+(?:\.\d+)?)\s*%?\s+"
        r"(?P<seconds>\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?\s+"
        r"(?P<function>[A-Za-z_.$:<>\-][\w.$:<>\-]*)"
        r"(?:\s+(?P<file>[^:\s]+):(?P<line>\d+))?"
    )
    fallback_pattern = re.compile(
        r"(?P<file>[^:\s]+):(?P<line>\d+).*?"
        r"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>%|s|sec|seconds)"
    )
    for raw_line in target.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        match = pattern.search(line)
        if match:
            hotspots.append(
                Hotspot(
                    function=match.group("function"),
                    file=match.group("file"),
                    line=_parse_int(match.group("line")),
                    metric="cpu-time",
                    value=float(match.group("seconds")),
                    unit="s",
                    raw={"line": line, "percent": float(match.group("percent"))},
                )
            )
            continue
        fallback = fallback_pattern.search(line)
        if fallback:
            hotspots.append(
                Hotspot(
                    function="<unknown>",
                    file=fallback.group("file"),
                    line=_parse_int(fallback.group("line")),
                    metric="sample",
                    value=float(fallback.group("value")),
                    unit=fallback.group("unit"),
                    raw={"line": line},
                )
            )
    return ProfileReport(
        source=str(target),
        profiler="hpctoolkit",
        hotspots=_sort_hotspots(hotspots),
        generated_at=utc_now(),
        metadata={"format": "text"},
    )


def parse_profile_json(path: str | Path) -> ProfileReport:
    target = Path(path)
    data = json.loads(target.read_text(encoding="utf-8"))
    return ProfileReport.from_dict(data)


def _detect_profile_kind(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix == ".csv":
        text = path.read_text(encoding="utf-8-sig", errors="ignore")[:4096].lower()
        if "vtune" in text or "cpu time" in text or "function" in text:
            return "vtune"
    return "hpctoolkit"


def _normalize_header(header: str | None) -> str:
    return (header or "").strip().lower().replace("\ufeff", "")


def _first(row: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = row.get(key)
        if value not in {None, ""}:
            return value
    return None


def _extract_metric(row: dict[str, str]) -> tuple[str, float | None, str]:
    candidates = [
        ("cpu time: self", "cpu-time-self", "s"),
        ("cpu time", "cpu-time", "s"),
        ("self time", "self-time", "s"),
        ("time", "time", "s"),
        ("hotspot", "hotspot", ""),
        ("% of cpu time", "cpu-time-percent", "%"),
        ("cpu time %", "cpu-time-percent", "%"),
        ("samples", "samples", "samples"),
    ]
    for header, metric, unit in candidates:
        if header not in row:
            continue
        value = _parse_float(row.get(header))
        if value is not None:
            return metric, value, unit
    for header, value in row.items():
        parsed = _parse_float(value)
        if parsed is not None and any(token in header for token in ("time", "sample", "%")):
            unit = "%" if "%" in header else ""
            return header, parsed, unit
    return "unknown", None, ""


def _parse_float(value: str | None) -> float | None:
    if value is None:
        return None
    cleaned = value.strip().replace(",", "")
    if not cleaned:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", cleaned)
    if not match:
        return None
    return float(match.group(0))


def _parse_int(value: str | None) -> int | None:
    if value is None or not str(value).strip():
        return None
    try:
        return int(float(str(value).strip()))
    except ValueError:
        return None


def _sort_hotspots(hotspots: list[Hotspot]) -> list[Hotspot]:
    return sorted(hotspots, key=lambda item: item.value, reverse=True)

