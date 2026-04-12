#!/usr/bin/env python3
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "setup_project.py"


class SetupProjectTests(unittest.TestCase):
    def test_check_fails_before_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = subprocess.run(
                ["python3", str(SCRIPT), "--project-root", str(root), "--check", "--format", "json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 2, msg=run.stderr)
            payload = json.loads(run.stdout)
            self.assertFalse(payload["ok"])
            self.assertGreater(len(payload["missing"]), 0)

    def test_bootstrap_creates_expected_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = subprocess.run(
                ["python3", str(SCRIPT), "--project-root", str(root), "--include-openspec"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)

            for rel in [
                "AGENTS.md",
                "PROJECT_CONTEXT.md",
                "docs/adr/template.md",
                "docs/releases/README.md",
                "tests/unit",
                "openspec/specs",
                "scripts/markdown-format.sh",
                "scripts/markdown-lint.sh",
                ".githooks/pre-commit",
                ".markdownlintignore",
            ]:
                self.assertTrue((root / rel).exists(), msg=f"missing: {rel}")

            self.assertTrue(os.access(root / "scripts/markdown-format.sh", os.X_OK))
            self.assertTrue(os.access(root / "scripts/markdown-lint.sh", os.X_OK))
            self.assertTrue(os.access(root / ".githooks/pre-commit", os.X_OK))

            agents = (root / "AGENTS.md").read_text(encoding="utf-8")
            self.assertIn("## 2. Comandos de Validacao (Quality Gate)", agents)
            self.assertIn("## 3. Comandos Essenciais (Operacao Local)", agents)

            check = subprocess.run(
                ["python3", str(SCRIPT), "--project-root", str(root), "--check", "--format", "json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(check.returncode, 0, msg=check.stderr)
            payload = json.loads(check.stdout)
            self.assertTrue(payload["ok"])

    def test_dry_run_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = subprocess.run(
                ["python3", str(SCRIPT), "--project-root", str(root), "--dry-run", "--format", "json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)
            payload = json.loads(run.stdout)
            self.assertTrue(payload["dry_run"])
            self.assertFalse((root / "AGENTS.md").exists())
            self.assertFalse((root / "PROJECT_CONTEXT.md").exists())


if __name__ == "__main__":
    unittest.main()
