from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from typing import Any


JsonMap = dict[str, Any]


def to_plain_data(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [to_plain_data(item) for item in value]
    if isinstance(value, dict):
        return {key: to_plain_data(item) for key, item in value.items()}
    return value


@dataclass(slots=True)
class SourceFile:
    path: str
    language: str
    lines: int


@dataclass(slots=True)
class SourceFinding:
    path: str
    line: int
    language: str
    kind: str
    severity: str
    message: str
    snippet: str = ""
    recommendation: str = ""
    symbol: str | None = None
    confidence: float = 0.7


@dataclass(slots=True)
class ScanReport:
    root: str
    files: list[SourceFile] = field(default_factory=list)
    findings: list[SourceFinding] = field(default_factory=list)
    language_counts: dict[str, int] = field(default_factory=dict)
    clang_available: bool = False
    generated_at: str = ""

    @classmethod
    def from_dict(cls, data: JsonMap) -> "ScanReport":
        return cls(
            root=str(data.get("root", "")),
            files=[SourceFile(**item) for item in data.get("files", [])],
            findings=[SourceFinding(**item) for item in data.get("findings", [])],
            language_counts=dict(data.get("language_counts", {})),
            clang_available=bool(data.get("clang_available", False)),
            generated_at=str(data.get("generated_at", "")),
        )


@dataclass(slots=True)
class Hotspot:
    function: str
    file: str | None
    line: int | None
    metric: str
    value: float
    unit: str = ""
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ProfileReport:
    source: str
    profiler: str
    hotspots: list[Hotspot] = field(default_factory=list)
    generated_at: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: JsonMap) -> "ProfileReport":
        return cls(
            source=str(data.get("source", "")),
            profiler=str(data.get("profiler", "")),
            hotspots=[Hotspot(**item) for item in data.get("hotspots", [])],
            generated_at=str(data.get("generated_at", "")),
            metadata=dict(data.get("metadata", {})),
        )


@dataclass(slots=True)
class HardwareSpec:
    id: str
    vendor: str
    model: str
    kind: str
    cores: int | None = None
    threads: int | None = None
    simd: list[str] = field(default_factory=list)
    memory: dict[str, Any] = field(default_factory=dict)
    gpu: dict[str, Any] = field(default_factory=dict)
    compilers: list[str] = field(default_factory=list)
    tune_hints: list[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: JsonMap) -> "HardwareSpec":
        return cls(
            id=str(data["id"]),
            vendor=str(data.get("vendor", "")),
            model=str(data.get("model", "")),
            kind=str(data.get("kind", "cpu")),
            cores=data.get("cores"),
            threads=data.get("threads"),
            simd=list(data.get("simd", [])),
            memory=dict(data.get("memory", {})),
            gpu=dict(data.get("gpu", {})),
            compilers=list(data.get("compilers", [])),
            tune_hints=list(data.get("tune_hints", [])),
        )


@dataclass(slots=True)
class OptimizationAction:
    id: str
    title: str
    priority: int
    category: str
    rationale: str
    files: list[str] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    suggested_change: str = ""
    validation_notes: list[str] = field(default_factory=list)
    confidence: float = 0.7


@dataclass(slots=True)
class OptimizationPlan:
    hardware_id: str
    actions: list[OptimizationAction] = field(default_factory=list)
    prompt_bundle: dict[str, Any] = field(default_factory=dict)
    generated_at: str = ""

    @classmethod
    def from_dict(cls, data: JsonMap) -> "OptimizationPlan":
        return cls(
            hardware_id=str(data.get("hardware_id", "")),
            actions=[OptimizationAction(**item) for item in data.get("actions", [])],
            prompt_bundle=dict(data.get("prompt_bundle", {})),
            generated_at=str(data.get("generated_at", "")),
        )


@dataclass(slots=True)
class CommandResult:
    name: str
    command: str
    exit_code: int
    duration_seconds: float
    passed: bool
    stdout_tail: str = ""
    stderr_tail: str = ""
    kind: str = "validation"


@dataclass(slots=True)
class ValidationReport:
    config: str
    root: str
    passed: bool
    commands: list[CommandResult] = field(default_factory=list)
    benchmarks: list[CommandResult] = field(default_factory=list)
    generated_at: str = ""

    @classmethod
    def from_dict(cls, data: JsonMap) -> "ValidationReport":
        return cls(
            config=str(data.get("config", "")),
            root=str(data.get("root", "")),
            passed=bool(data.get("passed", False)),
            commands=[CommandResult(**item) for item in data.get("commands", [])],
            benchmarks=[CommandResult(**item) for item in data.get("benchmarks", [])],
            generated_at=str(data.get("generated_at", "")),
        )

