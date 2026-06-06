"""
PerfLens project-level analysis — whole-codebase optimization workflow.
"""

from perflens.project.models import (
    ProjectGraph, SourceFile, BuildSystem,
    OptimizationPhase, ProjectOptimizationPlan, ProjectOptimizationResult,
)
from perflens.project.crawler import ProjectCrawler
from perflens.project.build_system import BuildDriver
from perflens.project.dependency_graph import DependencyGraph

__all__ = [
    "ProjectGraph", "SourceFile", "BuildSystem",
    "OptimizationPhase", "ProjectOptimizationPlan", "ProjectOptimizationResult",
    "ProjectCrawler", "BuildDriver", "DependencyGraph",
]
