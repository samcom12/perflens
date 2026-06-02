from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from perflens.scanner import scan_path


class ScannerTests(unittest.TestCase):
    def test_scans_c_and_python_findings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "kernel.c").write_text(
                """
#include <stdlib.h>
void kernel(double *a, int n) {
  for (int i = 0; i < n; ++i) {
    double *x = malloc(sizeof(double));
    a[i] = *x;
    free(x);
  }
}
""",
                encoding="utf-8",
            )
            (root / "loop.py").write_text(
                """
import math
def kernel(values):
    out = []
    for value in values:
        out.append(math.sqrt(value))
    return out
""",
                encoding="utf-8",
            )

            report = scan_path(root, use_clang="false")
            kinds = {finding.kind for finding in report.findings}

            self.assertEqual(report.language_counts["c"], 1)
            self.assertEqual(report.language_counts["python"], 1)
            self.assertIn("allocation-in-loop", kinds)
            self.assertIn("dynamic-list-growth", kinds)


if __name__ == "__main__":
    unittest.main()

