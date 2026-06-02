"""
Clang AST scanner for C and C++ source files.

Uses libclang (via the `libclang` Python package) to walk the translation-unit
AST and apply a set of pattern-matching visitors that detect HPC optimization
opportunities.

Falls back to regex-based heuristics when libclang is unavailable.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from perflens.scanner.models import Finding, FindingKind, Severity

# Try to import libclang; fail gracefully
try:
    import clang.cindex as cx

    _CLANG_AVAILABLE = True
except ImportError:
    _CLANG_AVAILABLE = False


# ──────────────────────────────────────────────────────────────────────────────
# Regex-based fallback patterns (always run even with libclang for cheap checks)
# ──────────────────────────────────────────────────────────────────────────────

_REGEX_PATTERNS: list[tuple[re.Pattern, FindingKind, Severity, str, str]] = [
    # Division inside loop body
    (
        re.compile(r"for\s*\(.*\)\s*\{[^}]*(?<![/*])/(?![/*=])[^}]*\}", re.DOTALL),
        FindingKind.DIVISION_IN_LOOP,
        Severity.MEDIUM,
        "Division operation found inside loop body — consider hoisting the reciprocal",
        "Precompute `inv = 1.0 / divisor` before the loop and multiply instead",
    ),
    # Math transcendentals in loop
    (
        re.compile(r"for\s*\([^;]+;[^;]+;[^)]+\)[^{]*\{[^}]*\b(sin|cos|tan|exp|log|sqrt|pow)\s*\(", re.DOTALL),
        FindingKind.TRANSCENDENTAL_IN_LOOP,
        Severity.HIGH,
        "Transcendental math call inside loop — expensive on scalar paths",
        "Use fast-math approximations (e.g. -ffast-math), SVML, or vectorized intrinsics",
    ),
    # printf/IO inside loop
    (
        re.compile(r"for\s*\([^;]+;[^;]+;[^)]+\)[^{]*\{[^}]*\b(printf|fprintf|fwrite|fread)\s*\(", re.DOTALL),
        FindingKind.IO_IN_LOOP,
        Severity.HIGH,
        "I/O call inside compute loop — serialises execution",
        "Accumulate output and write outside the loop, or use buffered I/O",
    ),
    # MPI_Send/Recv without non-blocking alternatives
    (
        re.compile(r"\bMPI_(Send|Recv)\s*\("),
        FindingKind.MPI_SYNCHRONOUS_HOTSPOT,
        Severity.MEDIUM,
        "Synchronous MPI_Send/Recv — may block and waste compute cycles",
        "Switch to MPI_Isend/Irecv with MPI_Waitall to overlap communication and computation",
    ),
    # Missing #pragma omp simd on inner loop
    (
        re.compile(r"(?<!\bpragma omp simd\b\n)for\s*\(\s*\w+\s+\w+\s*="),
        FindingKind.MISSING_SIMD_PRAGMA,
        Severity.LOW,
        "Inner loop without #pragma omp simd — vectorization not guaranteed",
        "Add `#pragma omp simd` (or `#pragma GCC ivdep`) before the loop",
    ),
    # Potential false sharing: array of small structs accessed by thread index
    (
        re.compile(r"\bthread_id\s*\]\s*\."),
        FindingKind.FALSE_SHARING,
        Severity.MEDIUM,
        "Struct array indexed by thread ID — risk of false sharing on cache line",
        "Pad struct to cache-line size (64 bytes) with `__attribute__((aligned(64)))`",
    ),
]


# ──────────────────────────────────────────────────────────────────────────────
# AST visitor helpers (libclang path)
# ──────────────────────────────────────────────────────────────────────────────

if _CLANG_AVAILABLE:
    _CK = cx.CursorKind

    # Loop cursor kinds
    _LOOP_KINDS = {_CK.FOR_STMT, _CK.WHILE_STMT, _CK.DO_STMT}

    # Call expression names considered expensive
    _EXPENSIVE_MATH = {"sin", "cos", "tan", "exp", "log", "sqrt", "pow", "atan2", "cbrt"}
    _IO_CALLS       = {"printf", "fprintf", "fwrite", "fread", "puts", "fputs"}
    _MPI_BLOCKING   = {"MPI_Send", "MPI_Recv", "MPI_Bcast", "MPI_Reduce", "MPI_Barrier"}


@dataclass
class _LoopContext:
    """Track nested loop depth and properties while walking the AST."""
    depth: int = 0
    nest_stack: list[int] = field(default_factory=list)  # line numbers of enclosing loops


# ──────────────────────────────────────────────────────────────────────────────
# Main scanner class
# ──────────────────────────────────────────────────────────────────────────────


class ClangScanner:
    """
    Walk a C/C++ translation unit via libclang, emitting Finding objects for
    every detected optimization opportunity.
    """

    def __init__(self, verbose: bool = False, extra_args: Optional[list[str]] = None):
        self.verbose = verbose
        self.extra_args: list[str] = extra_args or ["-std=c11", "-fopenmp"]

    # ── Public API ──────────────────────────────────────────────────────────

    def scan(self, path: Path, language: str = "c") -> list[Finding]:
        source = path.read_text(errors="replace")
        findings: list[Finding] = []

        # Always run cheap regex pass
        findings.extend(self._regex_scan(path, source))

        if _CLANG_AVAILABLE:
            findings.extend(self._ast_scan(path, language))
        else:
            if self.verbose:
                print("[perflens] libclang not available — using regex-only scanner")

        # Deduplicate by (line, kind)
        seen: set[tuple[int, str]] = set()
        unique: list[Finding] = []
        for f in findings:
            key = (f.line, f.kind.value)
            if key not in seen:
                seen.add(key)
                unique.append(f)

        return sorted(unique, key=lambda f: f.line)

    # ── Regex pass ──────────────────────────────────────────────────────────

    def _regex_scan(self, path: Path, source: str) -> list[Finding]:
        findings: list[Finding] = []
        lines = source.splitlines()

        for pattern, kind, severity, message, suggestion in _REGEX_PATTERNS:
            for m in pattern.finditer(source):
                line_no = source[: m.start()].count("\n") + 1
                col_no  = m.start() - source.rfind("\n", 0, m.start())
                ctx = lines[max(0, line_no - 2) : line_no + 2]
                findings.append(Finding(
                    file=path, line=line_no, col=col_no,
                    kind=kind, severity=severity,
                    message=message, suggestion=suggestion,
                    context_lines=ctx,
                ))
        return findings

    # ── AST pass (libclang) ─────────────────────────────────────────────────

    def _ast_scan(self, path: Path, language: str) -> list[Finding]:
        if not _CLANG_AVAILABLE:
            return []

        args = list(self.extra_args)
        if language == "cpp":
            args = ["-std=c++17", "-fopenmp"] + [a for a in args if "-std" not in a]

        index = cx.Index.create()
        tu = index.parse(str(path), args=args)

        findings: list[Finding] = []
        ctx = _LoopContext()
        self._visit(tu.cursor, path, findings, ctx)
        return findings

    def _visit(
        self,
        cursor: "cx.Cursor",  # type: ignore[name-defined]
        path: Path,
        findings: list[Finding],
        ctx: _LoopContext,
    ) -> None:
        if not _CLANG_AVAILABLE:
            return

        kind = cursor.kind
        loc  = cursor.location

        # Only process nodes from our target file
        if loc.file and Path(loc.file.name) != path:
            return

        line = loc.line or 0

        # ── Detect loop entry ─────────────────────────────────────────────
        if kind in _LOOP_KINDS:
            ctx.depth += 1
            ctx.nest_stack.append(line)

            children = list(cursor.get_children())

            # Nested-loop interchange opportunity (depth ≥ 2)
            if ctx.depth >= 2:
                findings.append(Finding(
                    file=path, line=line, col=loc.column or 0,
                    kind=FindingKind.LOOP_INTERCHANGE,
                    severity=Severity.MEDIUM,
                    message=f"Nested loop at depth {ctx.depth} — consider loop interchange for cache locality",
                    suggestion="Reorder loops so the innermost index matches the fastest-varying memory dimension",
                    metadata={"nest_depth": ctx.depth},
                ))

            # Tiling opportunity for deep nests
            if ctx.depth >= 3:
                findings.append(Finding(
                    file=path, line=line, col=loc.column or 0,
                    kind=FindingKind.LOOP_TILING_OPPORTUNITY,
                    severity=Severity.HIGH,
                    message=f"Triple-nested loop — loop tiling (blocking) can improve L1/L2 cache reuse",
                    suggestion="Tile with block sizes derived from L1/L2 cache size; typical starting point: 32–64",
                    metadata={"nest_depth": ctx.depth},
                ))

            # Walk children inside this loop
            for child in children:
                self._visit_in_loop(child, path, findings, ctx)

            ctx.depth -= 1
            ctx.nest_stack.pop()
            return  # children already visited above

        # Default: recurse
        for child in cursor.get_children():
            self._visit(child, path, findings, ctx)

    def _visit_in_loop(
        self,
        cursor: "cx.Cursor",  # type: ignore[name-defined]
        path: Path,
        findings: list[Finding],
        ctx: _LoopContext,
    ) -> None:
        if not _CLANG_AVAILABLE:
            return

        kind = cursor.kind
        loc  = cursor.location
        line = loc.line or 0

        if kind == _CK.CALL_EXPR:
            name = cursor.spelling or ""

            if name in _EXPENSIVE_MATH:
                findings.append(Finding(
                    file=path, line=line, col=loc.column or 0,
                    kind=FindingKind.TRANSCENDENTAL_IN_LOOP,
                    severity=Severity.HIGH,
                    message=f"Call to `{name}()` inside compute loop (depth={ctx.depth})",
                    suggestion=f"Vectorize with -ffast-math or use SVML/libmvec; hoist loop-invariant calls outside the loop",
                    metadata={"callee": name, "loop_depth": ctx.depth},
                ))

            elif name in _IO_CALLS:
                findings.append(Finding(
                    file=path, line=line, col=loc.column or 0,
                    kind=FindingKind.IO_IN_LOOP,
                    severity=Severity.HIGH,
                    message=f"I/O call `{name}()` inside loop (depth={ctx.depth}) — serialises execution",
                    suggestion="Batch output outside the loop or use a ring buffer",
                    metadata={"callee": name},
                ))

            elif name in _MPI_BLOCKING:
                findings.append(Finding(
                    file=path, line=line, col=loc.column or 0,
                    kind=FindingKind.MPI_SYNCHRONOUS_HOTSPOT,
                    severity=Severity.HIGH,
                    message=f"Blocking MPI call `{name}()` inside loop — stalls all ranks",
                    suggestion="Use non-blocking MPI_Isend/Irecv and overlap with local computation",
                    metadata={"callee": name},
                ))

            # Integer division in loop
            elif name in ("__divsi3", "__udivsi3", "__divdi3"):
                findings.append(Finding(
                    file=path, line=line, col=loc.column or 0,
                    kind=FindingKind.DIVISION_IN_LOOP,
                    severity=Severity.MEDIUM,
                    message="Integer division inside loop — expensive on most architectures",
                    suggestion="Replace with bitwise shift if divisor is a power of 2, or restructure",
                ))

        elif kind == _CK.BINARY_OPERATOR:
            tokens = [t.spelling for t in cursor.get_tokens()]
            if "/" in tokens or "%" in tokens:
                findings.append(Finding(
                    file=path, line=line, col=loc.column or 0,
                    kind=FindingKind.DIVISION_IN_LOOP,
                    severity=Severity.MEDIUM,
                    message="Division/modulo in loop body",
                    suggestion="Hoist the reciprocal computation (`inv = 1.0/d`) before the loop and multiply",
                    context_lines=tokens[:10],
                ))

        # Recurse into sub-expressions
        for child in cursor.get_children():
            self._visit_in_loop(child, path, findings, ctx)
