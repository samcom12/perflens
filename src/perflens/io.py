from __future__ import annotations

import json
import tomllib
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import to_plain_data


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def read_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, value: Any) -> Path:
    target = Path(path)
    ensure_parent(target)
    target.write_text(
        json.dumps(to_plain_data(value), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    return target


def load_structured_file(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    suffix = target.suffix.lower()
    text = target.read_text(encoding="utf-8")
    if suffix == ".json":
        return json.loads(text)
    if suffix == ".toml":
        return tomllib.loads(text)
    if suffix in {".yml", ".yaml"}:
        try:
            import yaml  # type: ignore
        except ImportError:
            return _parse_simple_yaml(text)
        loaded = yaml.safe_load(text) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{target} must contain a mapping at the top level")
        return loaded
    raise ValueError(f"Unsupported config format: {target.suffix}")


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    lines: list[tuple[int, str]] = []
    for raw_line in text.splitlines():
        stripped = raw_line.split("#", 1)[0].rstrip()
        if not stripped:
            continue
        indent = len(stripped) - len(stripped.lstrip(" "))
        lines.append((indent, stripped.lstrip(" ")))
    if not lines:
        return {}
    parsed, index = _parse_yaml_block(lines, 0, lines[0][0])
    if index != len(lines):
        raise ValueError("Could not parse complete YAML document")
    if not isinstance(parsed, dict):
        raise ValueError("YAML document must be a mapping")
    return parsed


def _parse_yaml_block(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[Any, int]:
    if index >= len(lines):
        return {}, index
    current_indent, content = lines[index]
    if current_indent < indent:
        return {}, index
    if content.startswith("- "):
        return _parse_yaml_list(lines, index, current_indent)
    return _parse_yaml_map(lines, index, current_indent)


def _parse_yaml_map(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[dict[str, Any], int]:
    result: dict[str, Any] = {}
    while index < len(lines):
        line_indent, content = lines[index]
        if line_indent < indent:
            break
        if line_indent > indent:
            raise ValueError(f"Unexpected indentation near: {content}")
        if ":" not in content:
            raise ValueError(f"Expected key/value pair near: {content}")
        key, raw_value = content.split(":", 1)
        key = key.strip()
        raw_value = raw_value.strip()
        index += 1
        if raw_value:
            result[key] = _parse_scalar(raw_value)
        elif index < len(lines) and lines[index][0] > line_indent:
            result[key], index = _parse_yaml_block(lines, index, lines[index][0])
        else:
            result[key] = {}
    return result, index


def _parse_yaml_list(
    lines: list[tuple[int, str]], index: int, indent: int
) -> tuple[list[Any], int]:
    result: list[Any] = []
    while index < len(lines):
        line_indent, content = lines[index]
        if line_indent < indent:
            break
        if line_indent != indent or not content.startswith("- "):
            break
        item = content[2:].strip()
        index += 1
        if not item:
            value, index = _parse_yaml_block(lines, index, indent + 2)
            result.append(value)
            continue
        if ":" in item:
            key, raw_value = item.split(":", 1)
            mapping: dict[str, Any] = {}
            mapping[key.strip()] = (
                _parse_scalar(raw_value.strip()) if raw_value.strip() else {}
            )
            if index < len(lines) and lines[index][0] > indent:
                nested, index = _parse_yaml_map(lines, index, lines[index][0])
                mapping.update(nested)
            result.append(mapping)
        else:
            result.append(_parse_scalar(item))
    return result, index


def _parse_scalar(value: str) -> Any:
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False
    if value in {"null", "None", "~"}:
        return None
    if (
        len(value) >= 2
        and value[0] == value[-1]
        and value[0] in {"'", '"'}
    ):
        return value[1:-1]
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        return value

