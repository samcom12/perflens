from __future__ import annotations

import json
import os
import subprocess
from collections import defaultdict
from pathlib import PurePosixPath
from typing import Any

from .io import utc_now
from .models import (
    HardwareSpec,
    Hotspot,
    OptimizationAction,
    OptimizationPlan,
    ProfileReport,
    ScanReport,
    SourceFinding,
)


SEVERITY_WEIGHT = {
    "error": 90,
    "warning": 70,
    "info": 40,
}

KIND_GUIDANCE = {
    "allocation-in-loop": (
        "Move allocation out of hot loops",
        "memory",
        "Move heap allocation outside repeated kernels, reuse scratch buffers, and validate lifetimes.",
    ),
    "dynamic-list-growth": (
        "Replace dynamic list growth in hot Python loops",
        "python",
        "Preallocate arrays or express the loop as NumPy operations, Numba kernels, or native extensions.",
    ),
    "expensive-scalar-op": (
        "Strengthen scalar math in hot loops",
        "compute",
        "Replace fixed small powers with multiplies and let the compiler vectorize the loop body.",
    ),
    "scalar-math-in-loop": (
        "Batch scalar math in Python loops",
        "python",
        "Use NumPy ufuncs, Numba, or a native kernel for scalar math repeated across large arrays.",
    ),
    "io-in-loop": (
        "Remove I/O from benchmarked loops",
        "runtime",
        "Buffer, sample, or gate diagnostics so timing reflects computation rather than output.",
    ),
    "openmp-loop": (
        "Tune OpenMP loop behavior",
        "parallelism",
        "Measure schedule, chunk size, thread affinity, and NUMA placement with representative inputs.",
    ),
    "mpi-call": (
        "Correlate MPI communication with rank imbalance",
        "parallelism",
        "Use rank-level profiling to find serialization, barriers, and collective imbalance.",
    ),
    "loop": (
        "Inspect hot loop for vectorization and locality",
        "loop",
        "Use profile data, vectorization reports, and cache behavior to decide on tiling, SIMD, or parallelism.",
    ),
    "clang-diagnostic": (
        "Resolve compiler diagnostic before rewriting",
        "correctness",
        "Fix or account for compiler diagnostics before applying source transformations.",
    ),
}


def recommend_optimizations(
    scan: ScanReport,
    profile: ProfileReport | None = None,
    hardware: HardwareSpec | None = None,
    max_actions: int = 30,
) -> OptimizationPlan:
    hardware_id = hardware.id if hardware else "unspecified"
    hotspot_index = _build_hotspot_index(profile)
    actions: list[OptimizationAction] = []

    for number, finding in enumerate(scan.findings, start=1):
        title, category, suggested_change = KIND_GUIDANCE.get(
            finding.kind,
            (
                f"Review {finding.kind}",
                "general",
                finding.recommendation or "Inspect this finding with profile context.",
            ),
        )
        matched_hotspots = _matching_hotspots(finding, hotspot_index)
        priority = _priority(finding, matched_hotspots)
        evidence = [
            f"{finding.path}:{finding.line}: {finding.message}",
        ]
        for hotspot in matched_hotspots[:3]:
            location = _format_hotspot_location(hotspot)
            evidence.append(
                f"profile {hotspot.metric}={hotspot.value:g}{hotspot.unit} at {location}"
            )
        if hardware and hardware.tune_hints:
            evidence.append(f"hardware {hardware.id}: {hardware.tune_hints[0]}")
        actions.append(
            OptimizationAction(
                id=f"opt-{number:03d}",
                title=title,
                priority=priority,
                category=category,
                rationale=_rationale(finding, matched_hotspots, hardware),
                files=[finding.path],
                evidence=evidence,
                suggested_change=finding.recommendation or suggested_change,
                validation_notes=[
                    "Run existing unit/regression tests.",
                    "Compare benchmark wall time across at least three runs for noisy kernels.",
                    "For floating-point kernels, compare numerical outputs with tolerance.",
                ],
                confidence=finding.confidence,
            )
        )

    if profile:
        actions.extend(_profile_only_actions(profile, scan, len(actions) + 1))

    deduped = _dedupe_actions(actions)
    ranked = sorted(deduped, key=lambda item: (-item.priority, item.id))[:max_actions]
    plan = OptimizationPlan(
        hardware_id=hardware_id,
        actions=ranked,
        generated_at=utc_now(),
    )
    plan.prompt_bundle = build_prompt_bundle(scan, profile, hardware, plan)
    return plan


def build_prompt_bundle(
    scan: ScanReport,
    profile: ProfileReport | None,
    hardware: HardwareSpec | None,
    plan: OptimizationPlan,
) -> dict[str, Any]:
    return {
        "role": "HPC performance optimization assistant",
        "instructions": [
            "Propose source transformations as unified diffs only.",
            "Preserve numerical behavior unless an explicit tolerance is provided.",
            "Prefer small, testable patches over broad rewrites.",
            "Explain benchmark and validation commands required before accepting a patch.",
        ],
        "hardware": _hardware_summary(hardware),
        "top_findings": [
            {
                "path": item.path,
                "line": item.line,
                "language": item.language,
                "kind": item.kind,
                "message": item.message,
                "snippet": item.snippet,
            }
            for item in scan.findings[:50]
        ],
        "top_hotspots": [
            {
                "function": hotspot.function,
                "file": hotspot.file,
                "line": hotspot.line,
                "metric": hotspot.metric,
                "value": hotspot.value,
                "unit": hotspot.unit,
            }
            for hotspot in (profile.hotspots[:25] if profile else [])
        ],
        "ranked_actions": [
            {
                "id": action.id,
                "title": action.title,
                "priority": action.priority,
                "files": action.files,
                "suggested_change": action.suggested_change,
            }
            for action in plan.actions
        ],
    }


class ExternalLLMOptimizer:
    """Adapter for a user-supplied LLM command.

    The command is read from PERFLENS_LLM_COMMAND. It receives a JSON prompt
    bundle on stdin and should return a JSON object with patch candidates.
    """

    def __init__(self, command: str | None = None) -> None:
        self.command = command or os.getenv("PERFLENS_LLM_COMMAND")

    def available(self) -> bool:
        return bool(self.command)

    def generate_patches(self, prompt_bundle: dict[str, Any], timeout: int = 120) -> dict[str, Any]:
        if not self.command:
            return {"patches": [], "message": "PERFLENS_LLM_COMMAND is not set"}
        completed = subprocess.run(
            self.command,
            input=json.dumps(prompt_bundle),
            capture_output=True,
            text=True,
            shell=True,
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0:
            return {
                "patches": [],
                "message": "LLM command failed",
                "exit_code": completed.returncode,
                "stderr": completed.stderr[-4000:],
            }
        try:
            return json.loads(completed.stdout)
        except json.JSONDecodeError:
            return {
                "patches": [],
                "message": "LLM command did not return JSON",
                "stdout": completed.stdout[-4000:],
            }


def _build_hotspot_index(
    profile: ProfileReport | None,
) -> dict[str, list[Hotspot]]:
    index: dict[str, list[Hotspot]] = defaultdict(list)
    if profile is None:
        return index
    for hotspot in profile.hotspots:
        if hotspot.file:
            normalized = hotspot.file.replace("\\", "/")
            index[normalized].append(hotspot)
            index[PurePosixPath(normalized).name].append(hotspot)
    return index


def _matching_hotspots(
    finding: SourceFinding, index: dict[str, list[Hotspot]]
) -> list[Hotspot]:
    matches = list(index.get(finding.path, []))
    matches.extend(index.get(PurePosixPath(finding.path).name, []))
    close: list[Hotspot] = []
    for hotspot in matches:
        if hotspot.line is None or abs(hotspot.line - finding.line) <= 12:
            close.append(hotspot)
    return sorted(close, key=lambda item: item.value, reverse=True)


def _priority(finding: SourceFinding, hotspots: list[Hotspot]) -> int:
    priority = SEVERITY_WEIGHT.get(finding.severity, 40)
    if hotspots:
        priority += min(25, int(max(item.value for item in hotspots)))
    if finding.kind in {"allocation-in-loop", "io-in-loop"}:
        priority += 10
    if finding.kind == "loop" and not hotspots:
        priority -= 10
    return max(1, min(priority, 100))


def _rationale(
    finding: SourceFinding,
    hotspots: list[Hotspot],
    hardware: HardwareSpec | None,
) -> str:
    parts = [finding.message]
    if hotspots:
        parts.append("The finding overlaps with profiler hotspots, so it is likely worth benchmarking.")
    if hardware:
        parts.append(
            f"Target hardware '{hardware.id}' suggests tuning for {', '.join(hardware.simd) or hardware.kind}."
        )
    return " ".join(parts)


def _profile_only_actions(
    profile: ProfileReport,
    scan: ScanReport,
    start_index: int,
) -> list[OptimizationAction]:
    known_files = {item.path for item in scan.files}
    known_names = {PurePosixPath(item.path).name for item in scan.files}
    actions: list[OptimizationAction] = []
    index = start_index
    for hotspot in profile.hotspots[:10]:
        if hotspot.file:
            normalized = hotspot.file.replace("\\", "/")
            name = PurePosixPath(normalized).name
            if normalized in known_files or name in known_names:
                continue
        actions.append(
            OptimizationAction(
                id=f"opt-{index:03d}",
                title="Investigate profiler hotspot without static match",
                priority=min(90, 50 + int(hotspot.value)),
                category="profile",
                rationale=(
                    "The profiler reported a hot function that was not matched to a scanned source location. "
                    "This often means missing debug symbols, generated code, library time, or path mismatch."
                ),
                files=[hotspot.file] if hotspot.file else [],
                evidence=[f"{hotspot.function}: {hotspot.value:g}{hotspot.unit} {hotspot.metric}"],
                suggested_change="Rebuild with debug symbols and export source file/line data for this hotspot.",
                validation_notes=["Confirm source attribution before applying transformations."],
                confidence=0.55,
            )
        )
        index += 1
    return actions


def _dedupe_actions(actions: list[OptimizationAction]) -> list[OptimizationAction]:
    best: dict[tuple[str, tuple[str, ...], str], OptimizationAction] = {}
    for action in actions:
        key = (action.title, tuple(action.files), action.category)
        existing = best.get(key)
        if existing is None or action.priority > existing.priority:
            best[key] = action
    return list(best.values())


def _format_hotspot_location(hotspot: Hotspot) -> str:
    if hotspot.file and hotspot.line:
        return f"{hotspot.file}:{hotspot.line}"
    if hotspot.file:
        return hotspot.file
    return hotspot.function


def _hardware_summary(hardware: HardwareSpec | None) -> dict[str, Any]:
    if hardware is None:
        return {"id": "unspecified"}
    return {
        "id": hardware.id,
        "vendor": hardware.vendor,
        "model": hardware.model,
        "kind": hardware.kind,
        "simd": hardware.simd,
        "memory": hardware.memory,
        "gpu": hardware.gpu,
        "tune_hints": hardware.tune_hints,
    }

