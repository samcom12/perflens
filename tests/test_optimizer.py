from __future__ import annotations

import unittest

from perflens.hardware import HardwareDB
from perflens.models import Hotspot, ProfileReport, ScanReport, SourceFile, SourceFinding
from perflens.optimizer import recommend_optimizations


class OptimizerTests(unittest.TestCase):
    def test_prioritizes_findings_with_profile_evidence(self) -> None:
        scan = ScanReport(
            root=".",
            files=[SourceFile(path="stencil.c", language="c", lines=20)],
            findings=[
                SourceFinding(
                    path="stencil.c",
                    line=8,
                    language="c",
                    kind="allocation-in-loop",
                    severity="warning",
                    message="allocation in loop",
                )
            ],
        )
        profile = ProfileReport(
            source="profile.csv",
            profiler="vtune",
            hotspots=[
                Hotspot(
                    function="stencil_step",
                    file="stencil.c",
                    line=8,
                    metric="cpu-time",
                    value=42.0,
                    unit="s",
                )
            ],
        )
        hardware = HardwareDB().get("amd-zen4")

        plan = recommend_optimizations(scan, profile=profile, hardware=hardware)

        self.assertEqual(plan.hardware_id, "amd-zen4")
        self.assertGreaterEqual(plan.actions[0].priority, 90)
        self.assertIn("top_findings", plan.prompt_bundle)


if __name__ == "__main__":
    unittest.main()

