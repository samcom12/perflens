"""
Python static analysis scanner using the built-in `ast` module.

Detects HPC anti-patterns common in scientific Python:
- Explicit loops over NumPy arrays (should use vectorized ops)
- GIL-bound threading patterns
- Repeated array allocations inside loops
- Missing numba/cython annotations on hot functions
- Inefficient pandas operations
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Optional

from perflens.scanner.models import Finding, FindingKind, Severity


# Names that indicate NumPy array types in annotations / comments
_NUMPY_ARRAY_HINTS = {"ndarray", "np.ndarray", "numpy.ndarray", "array"}

# Calls that are expensive when done per-element
_EXPENSIVE_SCALAR_CALLS = {
    "math.sin", "math.cos", "math.exp", "math.log", "math.sqrt",
    "math.pow", "math.tan", "math.atan2",
}

# NumPy equivalents that should replace scalar math
_NP_REPLACEMENTS = {
    "math.sin": "np.sin", "math.cos": "np.cos", "math.exp": "np.exp",
    "math.log": "np.log", "math.sqrt": "np.sqrt",
}

_IO_NAMES = {"print", "open", "write", "read", "readline", "readlines"}


class _LoopVisitor(ast.NodeVisitor):
    """Walk the AST and collect findings inside for/while loops."""

    def __init__(self, path: Path, source_lines: list[str]):
        self.path = path
        self.source_lines = source_lines
        self.findings: list[Finding] = []
        self._loop_depth = 0
        self._func_stack: list[str] = []

    # ── Helpers ─────────────────────────────────────────────────────────────

    def _ctx(self, lineno: int) -> list[str]:
        return self.source_lines[max(0, lineno - 2) : lineno + 2]

    def _add(self, node: ast.AST, kind: FindingKind, severity: Severity,
             message: str, suggestion: str, metadata: Optional[dict] = None) -> None:
        lineno = getattr(node, "lineno", 0)
        col    = getattr(node, "col_offset", 0)
        self.findings.append(Finding(
            file=self.path, line=lineno, col=col,
            kind=kind, severity=severity,
            message=message, suggestion=suggestion,
            context_lines=self._ctx(lineno),
            metadata=metadata or {},
        ))

    def _call_name(self, node: ast.Call) -> str:
        """Return dotted name of a Call node, e.g. 'np.zeros'."""
        func = node.func
        if isinstance(func, ast.Attribute):
            return f"{ast.unparse(func.value)}.{func.attr}"
        if isinstance(func, ast.Name):
            return func.id
        return ""

    # ── Visitors ────────────────────────────────────────────────────────────

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._func_stack.append(node.name)
        # Check for large functions without numba/cython hint
        if len(node.body) > 30:
            decorators = [ast.unparse(d) for d in node.decorator_list]
            if not any("numba" in d or "jit" in d or "cython" in d for d in decorators):
                self._add(
                    node,
                    FindingKind.GENERAL,
                    Severity.LOW,
                    f"Large function `{node.name}` ({len(node.body)} stmts) has no @numba.jit / @njit decorator",
                    "Annotate hot functions with `@numba.njit(parallel=True)` or compile with Cython",
                    {"func": node.name, "stmts": len(node.body)},
                )
        self.generic_visit(node)
        self._func_stack.pop()

    visit_AsyncFunctionDef = visit_FunctionDef  # type: ignore[assignment]

    def visit_For(self, node: ast.For) -> None:
        self._loop_depth += 1
        self._check_loop(node)
        self.generic_visit(node)
        self._loop_depth -= 1

    def visit_While(self, node: ast.While) -> None:
        self._loop_depth += 1
        self.generic_visit(node)
        self._loop_depth -= 1

    def _check_loop(self, node: ast.For) -> None:
        iter_node = node.iter

        # for i in range(...): arr[i] = ...  — classic numpy-loop pattern
        if isinstance(iter_node, ast.Call):
            iter_name = self._call_name(iter_node)

            if iter_name == "range":
                # Check if body does array subscript writes
                for stmt in ast.walk(node):
                    if isinstance(stmt, ast.Subscript):
                        self._add(
                            node,
                            FindingKind.NUMPY_LOOP,
                            Severity.HIGH,
                            f"Explicit `for i in range(...)` loop with array subscripting (depth={self._loop_depth}) — "
                            "bypasses NumPy vectorization",
                            "Replace with NumPy vectorized operations or use `np.vectorize` / `numba.prange`",
                            {"loop_depth": self._loop_depth},
                        )
                        break

            # for x in np.nditer(...) — usually OK but flag deep nesting
            elif "nditer" in iter_name and self._loop_depth >= 2:
                self._add(
                    node,
                    FindingKind.NUMPY_LOOP,
                    Severity.MEDIUM,
                    "np.nditer inside nested loop — consider fully-vectorized expression",
                    "Use broadcasting or `np.einsum` for multi-dimensional operations",
                )

        # Check body for expensive calls and allocations
        for stmt in ast.walk(node):
            if isinstance(stmt, ast.Call):
                name = self._call_name(stmt)

                # scalar math in loop
                if name in _EXPENSIVE_SCALAR_CALLS:
                    np_alt = _NP_REPLACEMENTS.get(name, f"np.{name.split('.')[-1]}")
                    self._add(
                        stmt,
                        FindingKind.TRANSCENDENTAL_IN_LOOP,
                        Severity.HIGH,
                        f"Scalar `{name}()` call inside loop (depth={self._loop_depth}) — not vectorized",
                        f"Use `{np_alt}(array)` on the full array outside the loop",
                        {"callee": name, "loop_depth": self._loop_depth},
                    )

                # array allocation inside loop
                elif name in ("np.zeros", "np.ones", "np.empty", "np.array",
                              "numpy.zeros", "numpy.ones", "numpy.empty"):
                    self._add(
                        stmt,
                        FindingKind.EXCESSIVE_ALLOCATION,
                        Severity.HIGH,
                        f"`{name}()` allocation inside loop (depth={self._loop_depth}) — triggers GC pressure",
                        "Pre-allocate arrays before the loop and reuse them with in-place operations",
                        {"callee": name},
                    )

                # I/O in loop
                elif name in _IO_NAMES or "write" in name or "print" in name:
                    self._add(
                        stmt,
                        FindingKind.IO_IN_LOOP,
                        Severity.MEDIUM,
                        f"I/O call `{name}()` inside loop — serialises execution",
                        "Accumulate results in a list and write outside the loop",
                    )

        # Nested loops ≥ 3 → tiling opportunity
        if self._loop_depth >= 3:
            self._add(
                node,
                FindingKind.LOOP_TILING_OPPORTUNITY,
                Severity.HIGH,
                f"Triple-nested Python loop (depth={self._loop_depth}) — extremely slow for large arrays",
                "Rewrite entirely with NumPy broadcasting / `np.einsum`, or compile with Numba `@njit(parallel=True)`",
                {"loop_depth": self._loop_depth},
            )

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            if alias.name == "threading":
                self._add(
                    node,
                    FindingKind.GIL_BOTTLENECK,
                    Severity.HIGH,
                    "Python `threading` module in HPC context — GIL prevents true parallelism",
                    "Use `multiprocessing`, `concurrent.futures.ProcessPoolExecutor`, or `mpi4py` for CPU-bound work",
                )
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.module == "threading":
            self._add(
                node,
                FindingKind.GIL_BOTTLENECK,
                Severity.MEDIUM,
                "Import from `threading` — GIL-bound in CPython",
                "Consider `multiprocessing` or `numba.prange` for parallelism",
            )
        self.generic_visit(node)


class PythonScanner:
    def __init__(self, verbose: bool = False):
        self.verbose = verbose

    def scan(self, path: Path) -> list[Finding]:
        source = path.read_text(errors="replace")
        lines  = source.splitlines()

        try:
            tree = ast.parse(source, filename=str(path))
        except SyntaxError as exc:
            if self.verbose:
                print(f"[perflens] Python parse error in {path}: {exc}")
            return []

        visitor = _LoopVisitor(path=path, source_lines=lines)
        visitor.visit(tree)

        # Additional regex-based checks on raw text
        findings = list(visitor.findings)
        findings.extend(self._regex_scan(path, source, lines))

        seen: set[tuple[int, str]] = set()
        result = []
        for f in findings:
            key = (f.line, f.kind.value)
            if key not in seen:
                seen.add(key)
                result.append(f)
        return sorted(result, key=lambda f: f.line)

    def _regex_scan(self, path: Path, source: str, lines: list[str]) -> list[Finding]:
        findings: list[Finding] = []

        # pandas .iterrows() — known performance trap
        for m in re.finditer(r"\.iterrows\(\)", source):
            lineno = source[: m.start()].count("\n") + 1
            findings.append(Finding(
                file=path, line=lineno, col=0,
                kind=FindingKind.NUMPY_LOOP,
                severity=Severity.HIGH,
                message="`DataFrame.iterrows()` is extremely slow — avoids vectorized Pandas/NumPy ops",
                suggestion="Use `df.apply()`, `df.itertuples()`, or fully vectorized column operations",
                context_lines=lines[max(0, lineno - 2) : lineno + 2],
            ))

        # pandas .apply(lambda) on axis=1
        for m in re.finditer(r"\.apply\(lambda", source):
            lineno = source[: m.start()].count("\n") + 1
            findings.append(Finding(
                file=path, line=lineno, col=0,
                kind=FindingKind.NUMPY_LOOP,
                severity=Severity.MEDIUM,
                message="`df.apply(lambda, axis=1)` applies a Python function row-by-row — slow",
                suggestion="Rewrite using vectorized Pandas / NumPy column expressions",
                context_lines=lines[max(0, lineno - 2) : lineno + 2],
            ))

        return findings
