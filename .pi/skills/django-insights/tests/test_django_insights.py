#!/usr/bin/env python3
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "django_insights.py"


class DjangoInsightsTests(unittest.TestCase):
    def test_detects_security_issues(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "settings.py").write_text(
                "DEBUG = True\nALLOWED_HOSTS = []\nSECRET_KEY = 'abc123'\n",
                encoding="utf-8",
            )

            run = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    "--format",
                    "json",
                    "--focus",
                    "security",
                    "--fail-on",
                    "high",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 2)
            payload = json.loads(run.stdout)
            self.assertGreaterEqual(payload["counts"]["critical"], 1)

    def test_detects_wildcard_and_print(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "views.py").write_text(
                "from django.db.models import *\n\nprint('x')\n",
                encoding="utf-8",
            )

            run = subprocess.run(
                ["python3", str(SCRIPT), "--project-root", str(root), "--format", "json", "--fail-on", "medium"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 2)
            payload = json.loads(run.stdout)
            self.assertGreaterEqual(payload["counts"]["medium"], 1)
            self.assertGreaterEqual(payload["counts"]["low"], 1)

    def test_app_scope(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "app1").mkdir(parents=True)
            (root / "app2").mkdir(parents=True)
            (root / "app1/views.py").write_text("print('a')\n", encoding="utf-8")
            (root / "app2/views.py").write_text("print('b')\n", encoding="utf-8")

            run = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    "--app",
                    "app1",
                    "--format",
                    "json",
                    "--fail-on",
                    "none",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0)
            payload = json.loads(run.stdout)
            files = {f["file"] for f in payload["findings"]}
            self.assertTrue(all(path.startswith("app1/") for path in files))


if __name__ == "__main__":
    unittest.main()
