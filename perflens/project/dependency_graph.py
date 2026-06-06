"""
Dependency Graph Analysis.

Builds a directed graph of file dependencies (A includes B → edge A→B)
and uses it to:
  1. Determine a safe optimization order (leaves first)
  2. Identify files that are transitively affected by a hotspot
  3. Detect shared headers that need careful handling
"""

from __future__ import annotations

from collections import defaultdict, deque
from pathlib import Path
from typing import Optional

from perflens.project.models import ProjectGraph, SourceFile


class DependencyGraph:
    """
    Directed graph over SourceFile nodes.

    Edges: A → B  means A depends on B (A includes B).
    We work on the *reverse* graph (B → callers) for propagation.
    """

    def __init__(self, graph: ProjectGraph):
        self._graph     = graph
        self._out: dict[Path, set[Path]] = defaultdict(set)   # A → {B, C}
        self._in:  dict[Path, set[Path]] = defaultdict(set)   # B → {A, X}
        self._build()

    def _build(self) -> None:
        for sf in self._graph.files.values():
            for dep in sf.includes:
                self._out[sf.path].add(dep)
                self._in[dep].add(sf.path)

    # ── Public API ────────────────────────────────────────────────────────────

    def topological_order(self) -> list[Path]:
        """
        Return source files in topological order (leaves first).
        Files with no outgoing edges (pure implementations) come first.
        Cycles are broken arbitrarily.
        """
        in_degree: dict[Path, int] = {p: len(self._out[p])
                                       for p in self._graph.files}
        queue = deque(p for p, d in in_degree.items() if d == 0)
        order: list[Path] = []
        visited: set[Path] = set()

        while queue:
            node = queue.popleft()
            if node in visited:
                continue
            visited.add(node)
            order.append(node)
            for caller in self._in.get(node, set()):
                in_degree[caller] -= 1
                if in_degree[caller] <= 0:
                    queue.append(caller)

        # Append anything not reached (cycle nodes)
        for p in self._graph.files:
            if p not in visited:
                order.append(p)

        return order

    def transitive_dependents(self, path: Path, max_hops: int = 3) -> set[Path]:
        """
        Return the set of files that transitively include *path*
        (i.e., files that would be affected if *path* changes).
        """
        visited: set[Path] = set()
        queue   = deque([(path, 0)])
        while queue:
            current, hops = queue.popleft()
            if current in visited or hops > max_hops:
                continue
            visited.add(current)
            for caller in self._in.get(current, set()):
                queue.append((caller, hops + 1))
        visited.discard(path)
        return visited

    def is_shared_header(self, path: Path, threshold: int = 3) -> bool:
        """True if *path* is included by >= *threshold* other files."""
        return len(self._in.get(path, set())) >= threshold

    def shared_headers(self, threshold: int = 3) -> list[Path]:
        """Return all header files included by >= *threshold* files."""
        return [p for p in self._graph.files
                if self._graph.files[p].is_header
                and self.is_shared_header(p, threshold)]

    def build_optimization_order(
        self,
        top_hotspot_n: int = 10,
    ) -> list[list[Path]]:
        """
        Return batches of files to optimize in sequence.

        Batch 0: Top hotspot files (direct CPU cost)
        Batch 1: Files that transitively call hotspot files
        Batch 2: Remaining files with high scanner score
        """
        topo = self.topological_order()
        sf_map = self._graph.files

        hotspots = sorted(
            [p for p in topo if sf_map.get(p) and sf_map[p].hotspot_pct > 0],
            key=lambda p: sf_map[p].hotspot_pct,
            reverse=True,
        )[:top_hotspot_n]

        batch0 = hotspots
        batch1_set: set[Path] = set()
        for h in hotspots:
            batch1_set |= self.transitive_dependents(h)
        batch1 = [p for p in topo
                  if p in batch1_set and p not in batch0]

        remaining = [p for p in topo
                     if p not in batch0 and p not in batch1_set
                     and sf_map.get(p) and not sf_map[p].is_header
                     and sf_map[p].priority_score > 5.0]
        batch2 = sorted(remaining,
                        key=lambda p: sf_map[p].priority_score,
                        reverse=True)

        return [b for b in [batch0, batch1, batch2] if b]

    def dot_graph(self, max_nodes: int = 50) -> str:
        """Return a Graphviz DOT representation (for visualization)."""
        sf_map   = self._graph.files
        nodes    = list(self._graph.files.keys())[:max_nodes]
        node_set = set(nodes)
        lines    = ["digraph perflens {", '  rankdir=LR;']
        for p in nodes:
            sf    = sf_map.get(p)
            color = ("red"    if sf and sf.hotspot_pct > 20 else
                     "orange" if sf and sf.hotspot_pct > 5  else
                     "lightblue")
            label = p.name[:25]
            lines.append(f'  "{p.name}" [label="{label}" fillcolor="{color}" style=filled];')
        for src in nodes:
            for dst in self._out.get(src, set()):
                if dst in node_set:
                    lines.append(f'  "{src.name}" -> "{dst.name}";')
        lines.append("}")
        return "\n".join(lines)
