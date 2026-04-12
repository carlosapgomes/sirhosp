#!/usr/bin/env python3
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "check_consistency.py"


class CheckConsistencyTests(unittest.TestCase):
    def test_runs_with_minimal_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text(
                (
                    "# AGENTS\n"
                    "## 2. Comandos de Validacao\n"
                    "- Testes: `python3 -m pytest -q`\n"
                ),
                encoding="utf-8",
            )
            (root / "PROJECT_CONTEXT.md").write_text(
                "# PROJECT_CONTEXT.md\n\ntexto suficiente para consistencia.\n",
                encoding="utf-8",
            )
            (root / "docs" / "adr").mkdir(parents=True)
            (root / "docs" / "releases").mkdir(parents=True)

            run = subprocess.run(
                ["python3", str(SCRIPT), "--format", "json"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)
            payload = json.loads(run.stdout)
            self.assertEqual(payload["summary"]["errors"], 0)

    def test_missing_agents_is_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = subprocess.run(
                ["python3", str(SCRIPT), "--format", "json"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 1, msg=run.stderr)
            payload = json.loads(run.stdout)
            self.assertGreaterEqual(payload["summary"]["errors"], 1)


if __name__ == "__main__":
    unittest.main()
