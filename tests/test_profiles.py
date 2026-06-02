from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from perflens.profiles import parse_profile


class ProfileParserTests(unittest.TestCase):
    def test_parses_vtune_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "vtune.csv"
            path.write_text(
                "Function,Source File,Line,CPU Time\n"
                "kernel,kernel.c,12,3.5\n",
                encoding="utf-8",
            )

            report = parse_profile(path, kind="auto")

            self.assertEqual(report.profiler, "vtune")
            self.assertEqual(report.hotspots[0].function, "kernel")
            self.assertEqual(report.hotspots[0].value, 3.5)

    def test_parses_hpctoolkit_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "profile.txt"
            path.write_text("91.0% 12.5s stencil_step stencil.c:8\n", encoding="utf-8")

            report = parse_profile(path, kind="hpctoolkit")

            self.assertEqual(report.profiler, "hpctoolkit")
            self.assertEqual(report.hotspots[0].file, "stencil.c")
            self.assertEqual(report.hotspots[0].line, 8)


if __name__ == "__main__":
    unittest.main()

