#!/usr/bin/env python3
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "suggest_refactor_sprint.py"


class RefactorSprintSuggesterTests(unittest.TestCase):
    def test_fail_on_returns_policy_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "x.py").write_text("# TODO: cleanup\n", encoding="utf-8")

            run = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    "--fail-on",
                    "low",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 2)

    def test_detects_long_function_and_todo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            long_body = "\n".join([f"    if x == {i}:\n        x += 1" for i in range(30)])
            code = (
                "def big(a, b, c, d, e, f, g):\n"
                "    # TODO refactor this\n"
                "    x = 0\n"
                f"{long_body}\n"
                "    return x\n"
            )
            (root / "mod.py").write_text(code, encoding="utf-8")

            run = subprocess.run(
                ["python3", str(SCRIPT), "--project-root", str(root), "--format", "json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)
            payload = json.loads(run.stdout)
            kinds = {f["kind"] for f in payload["findings"]}
            self.assertIn("long-or-complex-function", kinds)
            self.assertIn("tech-debt-note", kinds)

    def test_detects_duplicate_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            block = """def same():
    value = 10
    result = value * 2
    result = result + 3
    return result
"""
            (root / "a.py").write_text(block, encoding="utf-8")
            (root / "b.py").write_text(block, encoding="utf-8")

            run = subprocess.run(
                ["python3", str(SCRIPT), "--project-root", str(root), "--format", "json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)
            payload = json.loads(run.stdout)
            kinds = {f["kind"] for f in payload["findings"]}
            self.assertIn("duplicated-block", kinds)

    def test_write_output_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "x.py").write_text("# TODO: cleanup\nprint('x')\n", encoding="utf-8")

            run = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    "--output",
                    "docs/refactor-report.md",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)
            report = (root / "docs/refactor-report.md")
            self.assertTrue(report.exists())
            self.assertIn("Top prioridades", report.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
