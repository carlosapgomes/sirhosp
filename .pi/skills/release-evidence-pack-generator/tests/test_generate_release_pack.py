#!/usr/bin/env python3
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "generate_release_pack.py"


class GenerateReleasePackTests(unittest.TestCase):
    def test_fail_on_missing_any_returns_policy_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    "--version",
                    "v0.1.0",
                    "--dry-run",
                    "--fail-on",
                    "missing-any",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 2)

    def test_generates_markdown_file_with_detected_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "openspec/changes/archive/change-a").mkdir(parents=True, exist_ok=True)
            (root / "openspec/changes/archive/change-b").mkdir(parents=True, exist_ok=True)
            (root / "docs/adr").mkdir(parents=True, exist_ok=True)
            (root / "docs/adr/ADR-0001-db.md").write_text("# ADR-0001: DB\n", encoding="utf-8")

            run = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    "--version",
                    "v1.0.0",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)

            out = root / "docs/releases"
            generated = list(out.glob("*_v1.0.0.md"))
            self.assertEqual(len(generated), 1)
            content = generated[0].read_text(encoding="utf-8")
            self.assertIn("change-a", content)
            self.assertIn("ADR-0001", content)

    def test_dry_run_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    "--version",
                    "1.2.0",
                    "--dry-run",
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)
            payload = json.loads(run.stdout)
            self.assertEqual(payload["version"], "v1.2.0")
            self.assertIn("markdown", payload)

    def test_accepts_explicit_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    "--version",
                    "v2.0.0",
                    "--changes",
                    "c1,c2",
                    "--dry-run",
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)
            payload = json.loads(run.stdout)
            self.assertEqual([c["change_id"] for c in payload["changes"]], ["c1", "c2"])


if __name__ == "__main__":
    unittest.main()
