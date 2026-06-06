"""
Project Crawler — walks a directory tree, discovers source files, and
builds a coarse dependency graph by parsing:
  - C/C++  : #include directives
  - Fortran : USE / INCLUDE statements
  - Python  : import / from … import statements

The crawler does NOT need to compile the code.  It uses pure text
parsing (fast regex) rather than a full preprocessor, so it works
on incomplete or partially-broken codebases.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from perflens.project.models import ProjectGraph, SourceFile, BuildSystem


# ── Language detection ────────────────────────────────────────────────────────

_EXT_LANG: dict[str, str] = {
    ".c":   "c",   ".h":   "c",
    ".cpp": "cpp", ".cxx": "cpp", ".cc": "cpp",
    ".hpp": "cpp", ".hxx": "cpp",
    ".f":   "fortran", ".f90": "fortran", ".f95": "fortran",
    ".f03": "fortran", ".f08": "fortran", ".for": "fortran",
    ".f77": "fortran",
    ".py":  "python",
}

# Directories to always skip
_SKIP_DIRS = {
    ".git", ".svn", ".hg", ".github", ".vscode", ".idea",
    "__pycache__", "node_modules", "build", "Build", "BUILD",
    "_build", "cmake-build-debug", "cmake-build-release",
    ".cmake", "CMakeFiles", "dist", "*.egg-info",
    "venv", ".venv", "env", ".env",
}

# ── Include/import patterns ───────────────────────────────────────────────────

_C_INCLUDE    = re.compile(r'^\s*#\s*include\s+[<"]([^>"]+)[>"]', re.MULTILINE)
_F_USE        = re.compile(r'^\s*USE\s+(\w+)', re.IGNORECASE | re.MULTILINE)
_F_INCLUDE    = re.compile(r'^\s*INCLUDE\s+[\'"]([^\'"]+)[\'"]', re.IGNORECASE | re.MULTILINE)
_PY_IMPORT    = re.compile(r'^\s*(?:import|from)\s+([\w.]+)', re.MULTILINE)


class ProjectCrawler:
    """
    Walk *root* directory and build a ProjectGraph.

    Args:
        root:        Project root directory
        max_files:   Cap on files to process (safety for huge repos)
        skip_dirs:   Additional directory names to skip
        extensions:  Restrict to these extensions (None = all supported)
    """

    def __init__(
        self,
        root: Path,
        max_files: int = 5000,
        skip_dirs: Optional[set[str]] = None,
        extensions: Optional[set[str]] = None,
    ):
        self.root       = root
        self.max_files  = max_files
        self.skip_dirs  = _SKIP_DIRS | (skip_dirs or set())
        self.extensions = extensions   # None → all

    # ── Public API ────────────────────────────────────────────────────────────

    def crawl(self) -> ProjectGraph:
        """Return a fully-populated ProjectGraph for *self.root*."""
        build_sys = _detect_build_system(self.root)
        graph = ProjectGraph(
            root=self.root,
            build_system=build_sys,
            name=self.root.name,
        )

        # Discover files
        source_files = self._discover_files()
        for sf in source_files:
            graph.files[sf.path] = sf

        # Resolve dependencies
        self._resolve_dependencies(graph)

        return graph

    # ── File discovery ────────────────────────────────────────────────────────

    def _discover_files(self) -> list[SourceFile]:
        result: list[SourceFile] = []
        for path in self._walk():
            ext  = path.suffix.lower()
            lang = _EXT_LANG.get(ext)
            if not lang:
                continue
            if self.extensions and ext not in self.extensions:
                continue
            result.append(SourceFile(path=path, language=lang))
            if len(result) >= self.max_files:
                break
        return result

    def _walk(self):
        """Yield all files under root, skipping ignored directories."""
        stack = [self.root]
        while stack:
            current = stack.pop()
            try:
                entries = sorted(current.iterdir())
            except PermissionError:
                continue
            for entry in entries:
                if entry.is_symlink():
                    continue
                if entry.is_dir():
                    if entry.name not in self.skip_dirs and not entry.name.startswith("."):
                        stack.append(entry)
                elif entry.is_file():
                    yield entry

    # ── Dependency resolution ─────────────────────────────────────────────────

    def _resolve_dependencies(self, graph: ProjectGraph) -> None:
        """Parse each file for includes/imports and link SourceFile objects."""
        # Build a name→path index for fast lookup
        name_index: dict[str, list[Path]] = {}
        for path in graph.files:
            name_index.setdefault(path.name, []).append(path)
            name_index.setdefault(path.stem, []).append(path)

        for sf in graph.files.values():
            deps = self._parse_dependencies(sf)
            for dep_name in deps:
                resolved = self._resolve_name(dep_name, sf.path, name_index, graph)
                if resolved and resolved != sf.path:
                    sf.includes.append(resolved)
                    dep_sf = graph.files.get(resolved)
                    if dep_sf:
                        dep_sf.included_by.append(sf.path)

    def _parse_dependencies(self, sf: SourceFile) -> list[str]:
        try:
            text = sf.path.read_text(errors="replace")
        except OSError:
            return []

        deps: list[str] = []
        if sf.language in ("c", "cpp"):
            deps = [m.group(1) for m in _C_INCLUDE.finditer(text)]
        elif sf.language == "fortran":
            deps  = [m.group(1) for m in _F_USE.finditer(text)]
            deps += [m.group(1) for m in _F_INCLUDE.finditer(text)]
        elif sf.language == "python":
            deps = [m.group(1).split(".")[0] for m in _PY_IMPORT.finditer(text)]
        return deps

    def _resolve_name(
        self,
        dep_name: str,
        from_file: Path,
        name_index: dict[str, list[Path]],
        graph: ProjectGraph,
    ) -> Optional[Path]:
        """Try to resolve a dependency name to an absolute Path in the graph."""
        # Exact relative to including file's directory
        candidate = from_file.parent / dep_name
        if candidate in graph.files:
            return candidate

        # By filename only
        base = Path(dep_name).name
        matches = name_index.get(base) or name_index.get(Path(dep_name).stem, [])
        if len(matches) == 1:
            return matches[0]

        # Closest match by directory distance
        if matches:
            return min(matches,
                       key=lambda p: len(set(p.parts) ^ set(from_file.parts)))
        return None


# ── Build system detection ────────────────────────────────────────────────────

def _detect_build_system(root: Path) -> BuildSystem:
    """Heuristically detect which build system a project uses."""
    markers = {
        BuildSystem.CMAKE:    ["CMakeLists.txt"],
        BuildSystem.MESON:    ["meson.build"],
        BuildSystem.AUTOCONF: ["configure.ac", "configure.in", "Makefile.am"],
        BuildSystem.SCONS:    ["SConstruct", "SConscript"],
        BuildSystem.MAKE:     ["Makefile", "GNUmakefile", "makefile", "*.mk"],
        BuildSystem.PYTHON:   ["setup.py", "pyproject.toml", "setup.cfg"],
    }
    for bs, files in markers.items():
        for fname in files:
            if "*" in fname:
                if any(root.glob(fname)):
                    return bs
            elif (root / fname).exists():
                return bs
    return BuildSystem.BARE
