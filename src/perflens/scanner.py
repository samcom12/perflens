from __future__ import annotations

import ast
import re
import shutil
import subprocess
from pathlib import Path

from .io import utc_now
from .models import ScanReport, SourceFile, SourceFinding


LANGUAGE_BY_SUFFIX = {
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".py": "python",
    ".f": "fortran",
    ".f77": "fortran",
    ".f90": "fortran",
    ".f95": "fortran",
    ".f03": "fortran",
    ".f08": "fortran",
}

SKIP_DIRS = {
    ".git",
    ".hg",
    ".svn",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "venv",
    "build",
    "dist",
    ".perflens",
}


def detect_language(path: Path) -> str | None:
    return LANGUAGE_BY_SUFFIX.get(path.suffix.lower())


def detect_clang() -> str | None:
    return shutil.which("clang") or shutil.which("clang++")


def iter_source_files(root: Path) -> list[Path]:
    paths: list[Path] = []
    for path in root.rglob("*"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.is_file() and detect_language(path):
            paths.append(path)
    return sorted(paths)


def scan_path(root: str | Path, use_clang: str = "auto") -> ScanReport:
    project_root = Path(root).resolve()
    clang_path = detect_clang()
    clang_enabled = bool(clang_path) and use_clang.lower() in {"auto", "true", "yes", "1"}
    files: list[SourceFile] = []
    findings: list[SourceFinding] = []
    language_counts: dict[str, int] = {}

    for source in iter_source_files(project_root):
        language = detect_language(source)
        if language is None:
            continue
        rel_path = _rel(source, project_root)
        text = source.read_text(encoding="utf-8", errors="ignore")
        line_count = text.count("\n") + (1 if text else 0)
        files.append(SourceFile(path=rel_path, language=language, lines=line_count))
        language_counts[language] = language_counts.get(language, 0) + 1
        if language == "python":
            findings.extend(_scan_python(source, rel_path, text))
        elif language in {"c", "cpp"}:
            findings.extend(_scan_c_family(source, rel_path, text, language))
            if clang_enabled:
                findings.extend(_clang_diagnostics(source, rel_path, language, clang_path))
        elif language == "fortran":
            findings.extend(_scan_fortran(source, rel_path, text))

    return ScanReport(
        root=str(project_root),
        files=files,
        findings=sorted(findings, key=lambda item: (item.path, item.line, item.kind)),
        language_counts=language_counts,
        clang_available=bool(clang_path),
        generated_at=utc_now(),
    )


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def _scan_python(path: Path, rel_path: str, text: str) -> list[SourceFinding]:
    findings: list[SourceFinding] = []
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        return [
            SourceFinding(
                path=rel_path,
                line=exc.lineno or 1,
                language="python",
                kind="syntax-error",
                severity="error",
                message=exc.msg,
                snippet=exc.text.strip() if exc.text else "",
                recommendation="Fix syntax before running performance analysis.",
                confidence=1.0,
            )
        ]

    lines = text.splitlines()

    class Visitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.loop_depth = 0

        def visit_For(self, node: ast.For) -> None:
            findings.append(
                SourceFinding(
                    path=rel_path,
                    line=node.lineno,
                    language="python",
                    kind="loop",
                    severity="info",
                    message="Python loop detected in a performance-sensitive candidate region.",
                    snippet=_line(lines, node.lineno),
                    recommendation=(
                        "If this loop is hot, consider NumPy vectorization, Numba, Cython, "
                        "or moving the kernel to C/C++/Fortran."
                    ),
                    confidence=0.65,
                )
            )
            self.loop_depth += 1
            self.generic_visit(node)
            self.loop_depth -= 1

        def visit_While(self, node: ast.While) -> None:
            findings.append(
                SourceFinding(
                    path=rel_path,
                    line=node.lineno,
                    language="python",
                    kind="loop",
                    severity="info",
                    message="Python while-loop detected.",
                    snippet=_line(lines, node.lineno),
                    recommendation="Check whether this loop dominates runtime and can be vectorized or compiled.",
                    confidence=0.6,
                )
            )
            self.loop_depth += 1
            self.generic_visit(node)
            self.loop_depth -= 1

        def visit_Call(self, node: ast.Call) -> None:
            name = _python_call_name(node.func)
            if self.loop_depth and name in {"append", "extend"}:
                findings.append(
                    SourceFinding(
                        path=rel_path,
                        line=node.lineno,
                        language="python",
                        kind="dynamic-list-growth",
                        severity="warning",
                        message="List growth inside a loop can dominate Python runtime.",
                        snippet=_line(lines, node.lineno),
                        recommendation="Preallocate arrays or use vectorized NumPy operations for hot paths.",
                        confidence=0.75,
                    )
                )
            if self.loop_depth and name in {"sqrt", "sin", "cos", "exp", "pow"}:
                findings.append(
                    SourceFinding(
                        path=rel_path,
                        line=node.lineno,
                        language="python",
                        kind="scalar-math-in-loop",
                        severity="info",
                        message="Scalar math call inside Python loop.",
                        snippet=_line(lines, node.lineno),
                        recommendation="Batch math operations with NumPy ufuncs or compile the loop.",
                        confidence=0.68,
                    )
                )
            self.generic_visit(node)

    Visitor().visit(tree)
    return findings


def _python_call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _scan_c_family(
    path: Path, rel_path: str, text: str, language: str
) -> list[SourceFinding]:
    del path
    findings: list[SourceFinding] = []
    lines = text.splitlines()
    loop_active_until = -1
    brace_depth = 0

    for index, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("//"):
            brace_depth += raw_line.count("{") - raw_line.count("}")
            continue
        if re.search(r"\b(for|while)\s*\(", stripped):
            loop_active_until = max(loop_active_until, brace_depth + max(1, raw_line.count("{")))
            findings.append(
                SourceFinding(
                    path=rel_path,
                    line=index,
                    language=language,
                    kind="loop",
                    severity="info",
                    message="Loop candidate detected.",
                    snippet=stripped,
                    recommendation=(
                        "Use profile data and compiler vectorization reports to decide whether this "
                        "loop should be transformed, tiled, parallelized, or vectorized."
                    ),
                    confidence=0.7,
                )
            )
        inside_loop = loop_active_until >= 0 and brace_depth <= loop_active_until
        if inside_loop and re.search(r"\b(malloc|calloc|realloc|free)\s*\(", stripped):
            findings.append(
                SourceFinding(
                    path=rel_path,
                    line=index,
                    language=language,
                    kind="allocation-in-loop",
                    severity="warning",
                    message="Heap allocation inside a loop can create serious overhead.",
                    snippet=stripped,
                    recommendation="Move allocation outside the hot loop or reuse a work buffer.",
                    confidence=0.82,
                )
            )
        if inside_loop and re.search(r"\bnew\s+", stripped):
            findings.append(
                SourceFinding(
                    path=rel_path,
                    line=index,
                    language=language,
                    kind="allocation-in-loop",
                    severity="warning",
                    message="Object allocation inside a loop can create serious overhead.",
                    snippet=stripped,
                    recommendation="Reserve storage or reuse objects outside the hot loop.",
                    confidence=0.8,
                )
            )
        if inside_loop and re.search(r"\bpow\s*\(", stripped):
            findings.append(
                SourceFinding(
                    path=rel_path,
                    line=index,
                    language=language,
                    kind="expensive-scalar-op",
                    severity="info",
                    message="pow() inside a loop is often slower than multiplication for small integer powers.",
                    snippet=stripped,
                    recommendation="Replace small fixed powers with multiplication or vectorized intrinsics.",
                    confidence=0.72,
                )
            )
        if inside_loop and re.search(r"\b(printf|std::cout|fprintf)\b", stripped):
            findings.append(
                SourceFinding(
                    path=rel_path,
                    line=index,
                    language=language,
                    kind="io-in-loop",
                    severity="warning",
                    message="I/O inside a loop can distort runtime and block optimization.",
                    snippet=stripped,
                    recommendation="Buffer output or move diagnostics outside performance runs.",
                    confidence=0.86,
                )
            )
        if re.search(r"#\s*pragma\s+omp\s+parallel\s+for", stripped):
            findings.append(
                SourceFinding(
                    path=rel_path,
                    line=index,
                    language=language,
                    kind="openmp-loop",
                    severity="info",
                    message="OpenMP parallel loop detected.",
                    snippet=stripped,
                    recommendation="Validate schedule, chunk size, data sharing, and NUMA behavior.",
                    confidence=0.8,
                )
            )
        if re.search(r"\bMPI_(Send|Recv|Allreduce|Barrier|Bcast|Reduce)\b", stripped):
            findings.append(
                SourceFinding(
                    path=rel_path,
                    line=index,
                    language=language,
                    kind="mpi-call",
                    severity="info",
                    message="MPI communication call detected.",
                    snippet=stripped,
                    recommendation="Correlate with rank-level profiles and communication imbalance.",
                    confidence=0.78,
                )
            )
        brace_depth += raw_line.count("{") - raw_line.count("}")
        if loop_active_until >= 0 and brace_depth < loop_active_until:
            loop_active_until = -1
    return findings


def _scan_fortran(path: Path, rel_path: str, text: str) -> list[SourceFinding]:
    del path
    findings: list[SourceFinding] = []
    lines = text.splitlines()
    loop_depth = 0
    for index, raw_line in enumerate(lines, start=1):
        stripped = raw_line.strip()
        lower = stripped.lower()
        if not stripped or lower.startswith("!"):
            continue
        if re.match(r"do\s+([a-z_][a-z0-9_]*)\s*=", lower):
            loop_depth += 1
            findings.append(
                SourceFinding(
                    path=rel_path,
                    line=index,
                    language="fortran",
                    kind="loop",
                    severity="info",
                    message="Fortran do-loop candidate detected.",
                    snippet=stripped,
                    recommendation="Check vectorization, loop order, and contiguous array access.",
                    confidence=0.72,
                )
            )
        if loop_depth and re.search(r"\ballocate\s*\(", lower):
            findings.append(
                SourceFinding(
                    path=rel_path,
                    line=index,
                    language="fortran",
                    kind="allocation-in-loop",
                    severity="warning",
                    message="Allocation inside a Fortran loop can dominate hot-path runtime.",
                    snippet=stripped,
                    recommendation="Allocate work arrays outside the loop or reuse scratch storage.",
                    confidence=0.82,
                )
            )
        if loop_depth and re.search(r"\b(print|write)\b", lower):
            findings.append(
                SourceFinding(
                    path=rel_path,
                    line=index,
                    language="fortran",
                    kind="io-in-loop",
                    severity="warning",
                    message="Fortran I/O inside a loop can dominate runtime.",
                    snippet=stripped,
                    recommendation="Gate diagnostics or aggregate output outside benchmarked kernels.",
                    confidence=0.85,
                )
            )
        if lower.startswith("end do") and loop_depth:
            loop_depth -= 1
    return findings


def _clang_diagnostics(
    source: Path, rel_path: str, language: str, clang_path: str | None
) -> list[SourceFinding]:
    if clang_path is None:
        return []
    command = [clang_path, "-fsyntax-only", "-Wall", str(source)]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=8,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [
            SourceFinding(
                path=rel_path,
                line=1,
                language=language,
                kind="clang-diagnostic",
                severity="info",
                message=f"Clang diagnostic pass could not run: {exc}",
                recommendation="Provide compile_commands.json for complete compiler-aware analysis.",
                confidence=0.6,
            )
        ]
    diagnostics: list[SourceFinding] = []
    for raw_line in completed.stderr.splitlines()[:20]:
        match = re.search(r":(\d+):\d+:\s+(warning|error):\s+(.*)", raw_line)
        if not match:
            continue
        diagnostics.append(
            SourceFinding(
                path=rel_path,
                line=int(match.group(1)),
                language=language,
                kind="clang-diagnostic",
                severity=match.group(2),
                message=match.group(3).strip(),
                snippet=raw_line.strip(),
                recommendation="Inspect compiler diagnostics before applying automated transforms.",
                confidence=0.9,
            )
        )
    return diagnostics


def _line(lines: list[str], line_number: int) -> str:
    if 1 <= line_number <= len(lines):
        return lines[line_number - 1].strip()
    return ""

