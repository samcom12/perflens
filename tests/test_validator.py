from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from perflens.validator import run_validation


class ValidatorTests(unittest.TestCase):
    def test_runs_validation_and_benchmark_commands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            command = f'"{sys.executable}" -c "print(123)"'
            config = {
                "project": {"root": "."},
                "validation": {"commands": [{"name": "smoke", "command": command}]},
                "benchmark": {
                    "repeat": 2,
                    "commands": [{"name": "bench", "command": command}],
                },
            }
            config_path = root / "perflens.json"
            config_path.write_text(json.dumps(config), encoding="utf-8")

            report = run_validation(config_path)

            self.assertTrue(report.passed)
            self.assertEqual(len(report.commands), 1)
            self.assertEqual(len(report.benchmarks), 2)


if __name__ == "__main__":
    unittest.main()

