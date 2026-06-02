from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .io import load_structured_file, utc_now
from .models import CommandResult, ValidationReport


def run_validation(
    config_path: str | Path,
    timeout: int = 300,
) -> ValidationReport:
    config_file = Path(config_path).resolve()
    config = load_structured_file(config_file)
    project = config.get("project", {})
    root_value = project.get("root", ".") if isinstance(project, dict) else "."
    root = (config_file.parent / str(root_value)).resolve()
    validation_commands = _commands(config.get("validation", {}))
    benchmark_config = config.get("benchmark", {})
    benchmark_commands = _commands(benchmark_config)
    repeat = int(benchmark_config.get("repeat", 1)) if isinstance(benchmark_config, dict) else 1

    command_results = [
        _run_command(item["name"], item["command"], root, timeout, "validation")
        for item in validation_commands
    ]
    benchmark_results: list[CommandResult] = []
    for item in benchmark_commands:
        benchmark_results.extend(
            _run_command(
                f"{item['name']}#{iteration + 1}",
                item["command"],
                root,
                timeout,
                "benchmark",
            )
            for iteration in range(max(1, repeat))
        )

    passed = all(item.passed for item in command_results + benchmark_results)
    return ValidationReport(
        config=str(config_file),
        root=str(root),
        passed=passed,
        commands=command_results,
        benchmarks=benchmark_results,
        generated_at=utc_now(),
    )


def _commands(section: Any) -> list[dict[str, str]]:
    if not isinstance(section, dict):
        return []
    raw_commands = section.get("commands", [])
    if not isinstance(raw_commands, list):
        raise ValueError("commands must be a list")
    normalized: list[dict[str, str]] = []
    for index, item in enumerate(raw_commands, start=1):
        if isinstance(item, str):
            normalized.append({"name": f"command-{index}", "command": item})
            continue
        if not isinstance(item, dict) or "command" not in item:
            raise ValueError("each command must be a string or a mapping with command")
        normalized.append(
            {
                "name": str(item.get("name", f"command-{index}")),
                "command": str(item["command"]),
            }
        )
    return normalized


def _run_command(
    name: str,
    command: str,
    root: Path,
    timeout: int,
    kind: str,
) -> CommandResult:
    command = _expand_command(command)
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        duration = time.perf_counter() - started
        return CommandResult(
            name=name,
            command=command,
            exit_code=completed.returncode,
            duration_seconds=round(duration, 6),
            passed=completed.returncode == 0,
            stdout_tail=_tail(completed.stdout),
            stderr_tail=_tail(completed.stderr),
            kind=kind,
        )
    except subprocess.TimeoutExpired as exc:
        duration = time.perf_counter() - started
        return CommandResult(
            name=name,
            command=command,
            exit_code=124,
            duration_seconds=round(duration, 6),
            passed=False,
            stdout_tail=_tail(exc.stdout or ""),
            stderr_tail=_tail(exc.stderr or "command timed out"),
            kind=kind,
        )


def _tail(text: str | bytes, limit: int = 2000) -> str:
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    return text[-limit:]


def _expand_command(command: str) -> str:
    python = subprocess.list2cmdline([sys.executable])
    return command.replace("{python}", python)
