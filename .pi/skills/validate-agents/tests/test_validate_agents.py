#!/usr/bin/env python3
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "validate_agents.py"


AGENTS_SAMPLE = """# AGENTS.md

## 8. Anti-patterns Proibidos
- Nao usar wildcard imports.
- Nao usar except sem tipo.
- Nao hardcodar secrets.
"""


class ValidateAgentsTests(unittest.TestCase):
    def test_detects_critical_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text(AGENTS_SAMPLE, encoding="utf-8")
            target = root / "app.py"
            target.write_text('API_KEY = "super-secret"\n', encoding="utf-8")

            run = subprocess.run(
                ["python3", str(SCRIPT), "--project-root", str(root), str(target)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 2)
            self.assertIn("hardcoded-secret", run.stdout)

    def test_fix_rewrites_bare_except(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text(AGENTS_SAMPLE, encoding="utf-8")
            target = root / "worker.py"
            target.write_text(
                """def run():
    try:
        return 1
    except:
        return 0
""",
                encoding="utf-8",
            )

            run = subprocess.run(
                ["python3", str(SCRIPT), "--project-root", str(root), str(target), "--fix"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stdout + run.stderr)
            updated = target.read_text(encoding="utf-8")
            self.assertIn("except Exception:", updated)

    def test_json_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text(AGENTS_SAMPLE, encoding="utf-8")
            target = root / "mod.py"
            target.write_text("from math import *\n", encoding="utf-8")

            run = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    str(target),
                    "--format",
                    "json",
                    "--fail-on",
                    "medium",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 2)
            payload = json.loads(run.stdout)
            self.assertIn("violations", payload)
            self.assertGreaterEqual(len(payload["violations"]), 1)
            self.assertEqual(payload["counts"]["medium"], 1)


if __name__ == "__main__":
    unittest.main()
