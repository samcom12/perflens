from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from perflens.dashboard import generate_dashboard
from perflens.models import OptimizationAction, OptimizationPlan, ScanReport, SourceFile, SourceFinding


class DashboardTests(unittest.TestCase):
    def test_generates_static_html(self) -> None:
        scan = ScanReport(
            root=".",
            files=[SourceFile(path="kernel.c", language="c", lines=10)],
            findings=[
                SourceFinding(
                    path="kernel.c",
                    line=3,
                    language="c",
                    kind="loop",
                    severity="info",
                    message="loop",
                )
            ],
            language_counts={"c": 1},
        )
        plan = OptimizationPlan(
            hardware_id="generic-x86-64",
            actions=[
                OptimizationAction(
                    id="opt-001",
                    title="Inspect hot loop",
                    priority=70,
                    category="loop",
                    rationale="test",
                    files=["kernel.c"],
                    evidence=["kernel.c:3"],
                )
            ],
        )
        with tempfile.TemporaryDirectory() as tmp:
            path = generate_dashboard(Path(tmp), scan=scan, plan=plan)
            text = path.read_text(encoding="utf-8")

        self.assertIn("perflens dashboard", text)
        self.assertIn("Inspect hot loop", text)


if __name__ == "__main__":
    unittest.main()

