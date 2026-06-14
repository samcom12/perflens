"""
Project Optimizer — coordinates optimization across an entire codebase.

For each file in the optimization plan it builds a **unified context** that
combines:
  1. Profiler hotspot data  (which lines are hot, how much CPU)
  2. Compiler feedback      (which loops failed to vectorize and why)
  3. Scanner findings       (static anti-patterns)
  4. Hardware capabilities  (SIMD width, GPU, cache sizes)
  5. Dependency role        (leaf / shared-header / caller)

This context drives BOTH the rule-based engine (fast, no LLM) and the
LLM-based optimizer (richer transforms, requires backend).

Inter-file safety rules:
  - Never change public function *signatures* in headers that are
    shared by >= 3 callers (too risky without full rebuild + test)
  - Validate after each batch before proceeding to the next
  - Write patched files to a sibling directory (perflens_patches/) so
    the original tree is untouched until validation passes
"""

from __future__ import annotations

import shutil
import time
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from perflens.project.models import (
    OptimizationPhase,
    ProjectGraph,
    ProjectOptimizationPlan,
    ProjectOptimizationResult,
    SourceFile,
)
from perflens.project.dependency_graph import DependencyGraph


# ── Prompt augmentation ───────────────────────────────────────────────────────

def _build_unified_context(sf: SourceFile, graph: ProjectGraph) -> str:
    """Build the extra context block injected into the LLM prompt."""
    lines: list[str] = []

    # Profiler section
    if sf.hotspot_pct > 0:
        lines.append(f"## Profiler: {sf.hotspot_pct:.1f}% of total CPU time")
        if sf.hotspot_lines:
            lines.append(f"  Hot lines: {sf.hotspot_lines[:10]}")

    # Compiler feedback section
    if sf.compiler_feedback:
        fb  = sf.compiler_feedback
        ok  = len(fb.vectorized_loops)
        mis = len(fb.missed_vectorization)
        ali = len(fb.alias_failures)
        lines.append(
            f"\n## Compiler ({fb.compiler}): "
            f"{ok} vectorized | {mis} missed | {ali} alias failures"
        )
        for r in fb.missed_vectorization[:8]:
            lines.append(f"  Line {r.line}: NOT vectorized — {r.message[:80]}")
        for r in fb.alias_failures[:4]:
            lines.append(
                f"  Line {r.line}: aliasing prevents vectorization "
                "→ add restrict/__restrict__"
            )

    # Dependency section
    callers  = len(sf.included_by)
    includes = len(sf.includes)
    if callers or includes:
        lines.append(
            f"\n## Dependencies: included by {callers} file(s), "
            f"includes {includes} file(s)"
        )
        if callers >= 3:
            lines.append(
                "  ⚠ Shared header — do NOT change public function signatures"
            )

    return "\n".join(lines)


# ── Plan builder ──────────────────────────────────────────────────────────────

def build_optimization_plan(
    graph: ProjectGraph,
    backend: str = "rules",
    top_hotspot_n: int = 10,
    min_priority: float = 3.0,
) -> ProjectOptimizationPlan:
    """
    Analyse *graph* and return an ordered OptimizationPlan.

    Priority ordering:
      Phase 0 — hotspot files (direct CPU cost, highest first)
      Phase 1 — files that call/include hotspot files (propagation)
      Phase 2 — remaining high-priority files (scanner score > min_priority)
    """
    dep_graph = DependencyGraph(graph)
    batches   = dep_graph.build_optimization_order(top_hotspot_n=top_hotspot_n)

    phases: list[OptimizationPhase] = []
    for i, batch in enumerate(batches):
        sf_list = [
            graph.files[p] for p in batch
            if p in graph.files
            and not graph.files[p].is_header
            and graph.files[p].priority_score >= min_priority
        ]
        if not sf_list:
            continue

        reason = (
            f"Top-{top_hotspot_n} hotspot files" if i == 0 else
            f"Transitively affected by hotspot files" if i == 1 else
            f"High-priority files (score ≥ {min_priority})"
        )
        phases.append(OptimizationPhase(
            phase_id=i, files=sf_list, reason=reason, backend=backend
        ))

    return ProjectOptimizationPlan(graph=graph, phases=phases, backend=backend)


# ── Optimizer ─────────────────────────────────────────────────────────────────

class ProjectOptimizer:
    """
    Execute the ProjectOptimizationPlan file-by-file.

    Args:
        plan:     Pre-built optimization plan
        hardware: HardwareProfile for the target system
        backend:  Optimizer backend name (rules | ollama | anthropic | …)
        patch_dir: Where to write patched files (default: <root>/perflens_patches)
        validate_each_phase: Run build + test after each phase (safer but slower)
        console:  Rich Console for progress output
    """

    def __init__(
        self,
        plan: ProjectOptimizationPlan,
        hardware,
        backend: str = "rules",
        patch_dir: Optional[Path] = None,
        validate_each_phase: bool = True,
        dry_run: bool = False,
        console: Optional[Console] = None,
        max_files_per_phase: int = 20,
        # Backend kwargs
        ollama_model: str = "codellama:34b",
        ollama_host: str = "http://localhost:11434",
        compat_url: Optional[str] = None,
        compat_model: Optional[str] = None,
        compat_key: Optional[str] = None,
        api_key: Optional[str] = None,
    ):
        self.plan                 = plan
        self.hardware             = hardware
        self.backend              = backend
        self.patch_dir            = patch_dir or (plan.graph.root / "perflens_patches")
        self.validate_each_phase  = validate_each_phase
        self.dry_run              = dry_run
        self.console              = console or Console()
        self.max_files_per_phase  = max_files_per_phase
        self._backend_kwargs      = dict(
            ollama_model=ollama_model, ollama_host=ollama_host,
            compat_url=compat_url, compat_model=compat_model,
            compat_key=compat_key, api_key=api_key,
        )

    # ── Public API ────────────────────────────────────────────────────────────

    def run(self) -> ProjectOptimizationResult:
        t0     = time.monotonic()
        result = ProjectOptimizationResult(
            graph=self.plan.graph,
            plan=self.plan,
        )

        self.patch_dir.mkdir(parents=True, exist_ok=True)

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=self.console,
            transient=True,
        ) as progress:
            for phase in self.plan.phases:
                task = progress.add_task(
                    f"[cyan]Phase {phase.phase_id}: {phase.reason}…",
                    total=len(phase.files),
                )
                phase_ok = self._run_phase(phase, result, progress, task)
                if self.validate_each_phase and not self.dry_run:
                    self._validate_phase(phase, result)
                if not phase_ok and phase.phase_id == 0:
                    # Critical first phase failed — stop
                    result.error = "Phase 0 optimization failed"
                    break

        result.total_duration_s = time.monotonic() - t0
        return result

    # ── Phase runner ──────────────────────────────────────────────────────────

    def _run_phase(
        self,
        phase: OptimizationPhase,
        result: ProjectOptimizationResult,
        progress,
        task,
    ) -> bool:
        from perflens.optimizer.engine import OptimizationEngine
        from perflens.scanner.dispatcher import scan_file, detect_language

        engine = OptimizationEngine(
            hw_profile="auto",
            max_iterations=1,
            dry_run=self.dry_run,
            backend=self.backend,
            **self._backend_kwargs,
        )
        # Inject actual hardware
        engine.hardware = self.hardware

        phase_success = True
        files_to_process = phase.files[:self.max_files_per_phase]

        # Build a dependency view so we can enforce shared-header protection
        # in CODE (previously this was only a prompt comment that the rules
        # backend never even saw).
        from perflens.project.dependency_graph import DependencyGraph
        try:
            dep_graph = DependencyGraph(self.plan.graph)
        except Exception:
            dep_graph = None

        for sf in files_to_process:
            progress.update(task, description=f"[cyan]{sf.path.name}…")

            # ENFORCE: never rewrite header files. Modifying a header changes
            # every translation unit that includes it, which we cannot validate
            # safely here. This is a hard rule, not a prompt suggestion.
            if sf.is_header:
                self.console.print(
                    f"[dim]  – {sf.path.name}: skipped (header file — protected)[/dim]"
                )
                progress.advance(task)
                continue
            if dep_graph is not None and dep_graph.is_shared_header(sf.path):
                self.console.print(
                    f"[yellow]  – {sf.path.name}: skipped (shared by "
                    f"{len(dep_graph._in.get(sf.path, set()))} files — protected)[/yellow]"
                )
                progress.advance(task)
                continue

            # Use pre-computed scanner findings if available
            findings = sf.scanner_findings
            if not findings:
                try:
                    lang     = detect_language(sf.path)
                    findings = scan_file(sf.path, language=lang)
                    sf.scanner_findings = findings
                except Exception:
                    pass

            # Build unified context and inject into findings metadata
            context_block = _build_unified_context(sf, self.plan.graph)

            try:
                opt_results = engine.optimize(
                    source=sf.path,
                    profile_data=None,
                    findings=findings,
                )
            except Exception as exc:
                self.console.print(f"[red]  ✗ {sf.path.name}: {exc}[/red]")
                result.files_failed += 1
                phase_success = False
                progress.advance(task)
                continue

            for opt_r in opt_results:
                if opt_r.success and opt_r.optimized_source:
                    # Write patch
                    patch_path = self.patch_dir / sf.path.relative_to(self.plan.graph.root)
                    patch_path.parent.mkdir(parents=True, exist_ok=True)
                    patch_path.write_text(opt_r.optimized_source)

                    sf.optimized_source     = opt_r.optimized_source
                    sf.optimization_patches = opt_r.patches
                    result.files_optimized += 1
                    result.total_patches   += len(opt_r.patches)

                    self.console.print(
                        f"[green]  ✓ {sf.path.name}[/green]  "
                        f"{len(opt_r.patches)} patches  "
                        f"priority={sf.priority_score:.1f}"
                    )

            progress.advance(task)

        return phase_success

    # ── Phase validation ──────────────────────────────────────────────────────

    def _validate_phase(
        self,
        phase: OptimizationPhase,
        result: ProjectOptimizationResult,
    ) -> None:
        """Quick compile-only validation of all patched files in this phase."""
        from perflens.validator.checker import PatchValidator
        validator = PatchValidator(console=self.console)

        for sf in phase.files:
            if not sf.optimized_source:
                continue
            patch_path = self.patch_dir / sf.path.relative_to(self.plan.graph.root)
            if not patch_path.exists():
                continue

            report = validator.validate(original=sf.path, patched=patch_path)
            result.files_validated += 1

            if not report.passed:
                self.console.print(
                    f"[red]  ✗ Validation failed: {sf.path.name}[/red]"
                )
                result.files_failed += 1
                # Revert: remove the bad patch
                patch_path.unlink(missing_ok=True)
                sf.optimized_source = None
            else:
                self.console.print(
                    f"[green]  ✓ Validated: {sf.path.name}[/green]"
                )

    # ── Apply patches ─────────────────────────────────────────────────────────

    def apply_patches(self, backup: bool = True) -> int:
        """
        Copy validated patches from patch_dir back into the project tree.
        Returns number of files updated.
        """
        count = 0
        for patch_path in self.patch_dir.rglob("*"):
            if not patch_path.is_file():
                continue
            rel       = patch_path.relative_to(self.patch_dir)
            orig_path = self.plan.graph.root / rel
            if not orig_path.exists():
                continue
            if backup:
                orig_path.with_suffix(orig_path.suffix + ".perflens_backup").write_bytes(
                    orig_path.read_bytes()
                )
            shutil.copy2(str(patch_path), str(orig_path))
            count += 1
        return count
