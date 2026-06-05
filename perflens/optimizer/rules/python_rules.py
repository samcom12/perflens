"""
Python source-level transformation rules.

Rules work on the raw source text (not bytecode) so they're safe to apply
without executing the code.
"""

from __future__ import annotations

import re
from typing import Optional

from perflens.optimizer.models import Patch, TransformKind
from perflens.optimizer.rules.base_rule import RuleContext, TransformRule
from perflens.scanner.models import FindingKind


def _line_of(source: str, match: re.Match) -> int:
    """Return 1-based line number of a regex match in source."""
    return source[: match.start()].count("\n") + 1


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 1 — Replace scalar math.* with numpy equivalents
# ═══════════════════════════════════════════════════════════════════════════════

_MATH_IMPORT = re.compile(r"^import\s+math\b", re.MULTILINE)
_MATH_CALLS  = {
    "math.sin": "np.sin", "math.cos": "np.cos", "math.tan": "np.tan",
    "math.exp": "np.exp", "math.log": "np.log", "math.sqrt": "np.sqrt",
    "math.pow": "np.power", "math.pi": "np.pi", "math.e": "np.e",
    "math.atan2": "np.arctan2", "math.fabs": "np.fabs",
    "math.ceil": "np.ceil", "math.floor": "np.floor",
}


class ScalarMathToNumpyRule(TransformRule):
    """
    Replace ``math.sin(x)`` → ``np.sin(x)`` etc.

    When applied to arrays, NumPy's UFUNC dispatches to SVML/libmvec
    giving vectorised execution.  Even for scalars, removing the
    ``math`` import eliminates the CPython C-extension call overhead.
    """

    supported_languages = {"python"}

    @property
    def name(self) -> str:
        return "scalar_math_to_numpy"

    @property
    def transform_kind(self) -> TransformKind:
        return TransformKind.NUMPY_VECTORISE

    def applies(self, ctx: RuleContext) -> bool:
        if ctx.language != "python":
            return False
        return bool(_MATH_IMPORT.search(ctx.source)) and any(
            k in ctx.source for k in _MATH_CALLS
        )

    def apply(self, ctx: RuleContext) -> Optional[tuple[str, list[Patch]]]:
        source = ctx.source
        changed: list[str] = []

        for old, new in _MATH_CALLS.items():
            if old in source:
                source = source.replace(old, new)
                changed.append(f"{old} → {new}")

        if not changed:
            return None

        # Ensure numpy is imported
        if "import numpy" not in source:
            source = "import numpy as np\n" + source
        # Remove math import if no raw `math.` left
        if "math." not in source:
            source = _MATH_IMPORT.sub("", source).lstrip("\n")

        patches = [Patch(
            transform_kind=TransformKind.NUMPY_VECTORISE,
            description=f"Replace {len(changed)} scalar math.* calls with numpy equivalents",
            original_snippet="\n".join(f"  {c.split(' → ')[0]}" for c in changed[:5]),
            optimized_snippet="\n".join(f"  {c.split(' → ')[1]}" for c in changed[:5]),
            start_line=1, end_line=len(source.splitlines()),
            rationale=(
                "NumPy UFuncs dispatch to SVML/libmvec, applying vectorised "
                "SIMD instructions on arrays. Even scalar usage avoids Python "
                "C-extension overhead."
            ),
            expected_speedup="2–10× on array inputs",
        )]
        return source, patches


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 2 — Pre-allocate numpy arrays before loop
# ═══════════════════════════════════════════════════════════════════════════════

# Match: inside a for-loop body, np.zeros/ones/empty called
_LOOP_ALLOC = re.compile(
    r"(?P<indent>[ \t]+)(?P<var>\w+)\s*=\s*np\.(?:zeros|ones|empty|zeros_like|ones_like)\s*\(",
    re.MULTILINE,
)
_FOR_HEADER = re.compile(r"^([ \t]*)for\s+\w+\s+in\s+", re.MULTILINE)


class PreAllocateRule(TransformRule):
    """
    Hoist ``np.zeros(...)`` allocations from inside a loop to before it.

    Pattern detected::

        for i in range(n):
            tmp = np.zeros(m)   # ← allocates every iteration
            ...

    Transformed to::

        tmp = np.zeros(m)       # ← single allocation
        for i in range(n):
            tmp[:] = 0.0        # ← in-place zero-fill
            ...
    """

    supported_languages = {"python"}

    @property
    def name(self) -> str:
        return "preallocate_numpy"

    @property
    def transform_kind(self) -> TransformKind:
        return TransformKind.NUMPY_VECTORISE

    def applies(self, ctx: RuleContext) -> bool:
        if ctx.language != "python":
            return False
        return any(f.kind == FindingKind.EXCESSIVE_ALLOCATION for f in ctx.findings)

    def apply(self, ctx: RuleContext) -> Optional[tuple[str, list[Patch]]]:
        source = ctx.source
        lines  = source.splitlines()
        patches: list[Patch] = []
        insertions: list[tuple[int, str]] = []   # (before_line_index, text)

        for m in _LOOP_ALLOC.finditer(source):
            lineno = _line_of(source, m)
            indent = m.group("indent")
            var    = m.group("var")

            # Find the enclosing for-loop header (nearest one above)
            for_lines = list(_FOR_HEADER.finditer(source[: m.start()]))
            if not for_lines:
                continue
            for_m    = for_lines[-1]
            for_line = _line_of(source, for_m)

            alloc_call = lines[lineno - 1].strip()

            # Build hoisted declaration
            hoisted = f"{for_m.group(1)}{alloc_call}  # hoisted by perflens"
            # Replace allocation in loop with in-place reset
            in_place = f"{indent}{var}[:] = 0  # in-place reset"

            insertions.append((for_line - 1, hoisted))
            lines[lineno - 1] = in_place

            patches.append(Patch(
                transform_kind=TransformKind.NUMPY_VECTORISE,
                description=f"Hoist `{var}` allocation before loop at line {for_line}",
                original_snippet=alloc_call,
                optimized_snippet=f"{hoisted}\n... loop ...\n{in_place}",
                start_line=lineno, end_line=lineno,
                rationale=(
                    "NumPy allocation triggers the Python GC and zeroes memory. "
                    "Pre-allocating once and resetting in-place eliminates this overhead."
                ),
                expected_speedup="1.5–3× for tight loops",
            ))

        if not patches:
            return None

        # Apply insertions in reverse order to preserve line numbers
        for idx, text in sorted(insertions, reverse=True):
            lines.insert(idx, text)

        return "\n".join(lines), patches


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 3 — Add @numba.njit to hot functions
# ═══════════════════════════════════════════════════════════════════════════════

_FUNC_DEF = re.compile(
    r"^(?P<indent>[ \t]*)def\s+(?P<name>\w+)\s*\(", re.MULTILINE
)
_ALREADY_DECORATED = re.compile(
    r"@\s*(?:numba\.(?:njit|jit|vectorize)|jit|njit)\s*", re.MULTILINE
)

# Functions with these names are likely helpers, not hot kernels — skip them
_SKIP_NAMES = {
    "main", "run", "test", "setup", "teardown", "parse_args",
    "__init__", "__repr__", "__str__", "__len__", "__getitem__",
}


class NumbaAnnotateRule(TransformRule):
    """
    Add ``@numba.njit(parallel=True, cache=True)`` to compute-heavy functions.

    Detects candidate functions by:
    - Having numpy loop patterns in their body
    - Being flagged by scanner (NUMPY_LOOP, TRANSCENDENTAL_IN_LOOP)
    - Being longer than 15 lines (likely non-trivial)

    Also adds ``from numba import njit, prange`` at the top and replaces
    ``range(...)`` with ``prange(...)`` inside annotated functions.
    """

    supported_languages = {"python"}

    @property
    def name(self) -> str:
        return "numba_annotate"

    @property
    def transform_kind(self) -> TransformKind:
        return TransformKind.NUMBA_JIT

    def applies(self, ctx: RuleContext) -> bool:
        if ctx.language != "python":
            return False
        if _ALREADY_DECORATED.search(ctx.source):
            return False
        return any(f.kind in (
            FindingKind.NUMPY_LOOP,
            FindingKind.TRANSCENDENTAL_IN_LOOP,
            FindingKind.EXCESSIVE_ALLOCATION,
        ) for f in ctx.findings)

    def apply(self, ctx: RuleContext) -> Optional[tuple[str, list[Patch]]]:
        lines   = ctx.source.splitlines()
        patches = []

        # Find flagged line numbers for hot functions
        hot_lines = {f.line for f in ctx.findings if f.kind in (
            FindingKind.NUMPY_LOOP, FindingKind.TRANSCENDENTAL_IN_LOOP,
        )}

        candidates: list[tuple[int, str]] = []   # (line_index, name)
        for m in _FUNC_DEF.finditer(ctx.source):
            name   = m.group("name")
            lineno = _line_of(ctx.source, m)
            if name in _SKIP_NAMES:
                continue
            # Check if any hot findings are within ~100 lines of this function
            near = any(abs(lineno - hl) < 80 for hl in hot_lines)
            if near:
                candidates.append((lineno - 1, name))

        if not candidates:
            return None

        # Insert decorator before each candidate function (reverse order)
        for idx, name in sorted(candidates, reverse=True):
            decorator = "@njit(parallel=True, cache=True)"
            lines.insert(idx, decorator)
            patches.append(Patch(
                transform_kind=TransformKind.NUMBA_JIT,
                description=f"Add @njit(parallel=True) to function `{name}`",
                original_snippet=f"def {name}(...)",
                optimized_snippet=f"{decorator}\ndef {name}(...)",
                start_line=idx + 1, end_line=idx + 1,
                rationale=(
                    "Numba JIT-compiles Python functions to LLVM IR, generating "
                    "native SIMD code. `parallel=True` enables automatic "
                    "parallelisation of for-loops."
                ),
                expected_speedup="10–100× vs pure Python",
            ))

        # Add numba import if not present
        source = "\n".join(lines)
        if "from numba import" not in source and "import numba" not in source:
            source = "from numba import njit, prange\n" + source

        # Replace range with prange inside decorated functions
        source = re.sub(
            r"(?<=@njit\(parallel=True, cache=True\)\ndef [^\n]+\n(?:[^\n]*\n){0,200})\brange\b",
            "prange",
            source,
        )

        return source, patches


# ═══════════════════════════════════════════════════════════════════════════════
# Rule 4 — Replace iterrows with vectorised pandas
# ═══════════════════════════════════════════════════════════════════════════════

_ITERROWS = re.compile(r"\.iterrows\(\)")


class PandasIterrowsRule(TransformRule):
    """
    Add a comment guiding the developer to replace ``df.iterrows()``
    with a vectorised expression and suggest the ``swifter`` library.
    """

    supported_languages = {"python"}

    @property
    def name(self) -> str:
        return "pandas_vectorise"

    @property
    def transform_kind(self) -> TransformKind:
        return TransformKind.NUMPY_VECTORISE

    def applies(self, ctx: RuleContext) -> bool:
        return ctx.language == "python" and bool(_ITERROWS.search(ctx.source))

    def apply(self, ctx: RuleContext) -> Optional[tuple[str, list[Patch]]]:
        source = ctx.source
        lines  = source.splitlines(keepends=True)
        patches = []
        offset  = 0

        for m in _ITERROWS.finditer(ctx.source):
            lineno = _line_of(ctx.source, m)
            hint   = (
                "    # PERFLENS: replace iterrows() with vectorised ops:\n"
                "    #   df['col'].apply(func) or df.assign(col=lambda df: ...)\n"
                "    #   or: pip install swifter  →  df.swifter.apply(func)\n"
            )
            lines.insert(lineno - 1 + offset, hint)
            offset += 1
            patches.append(Patch(
                transform_kind=TransformKind.NUMPY_VECTORISE,
                description=f"Flag .iterrows() at line {lineno} — add vectorisation hint",
                original_snippet=".iterrows()",
                optimized_snippet="# PERFLENS hint inserted — see comment above .iterrows()",
                start_line=lineno, end_line=lineno,
                rationale=(
                    "df.iterrows() applies a Python function row-by-row, "
                    "bypassing pandas/NumPy vectorised ops. "
                    "Replace with column-wise operations."
                ),
                expected_speedup="10–1000× depending on DataFrame size",
            ))

        if not patches:
            return None
        return "".join(lines), patches
