#!/usr/bin/env python3
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "quality_gate.py"


class QualityGateTests(unittest.TestCase):
    def test_parses_comandos_de_validacao_without_accent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text(
                (
                    "# AGENTS\n\n"
                    "## 2. Comandos de Validacao (Quality Gate)\n"
                    "- Testes: `python3 -m pytest -q`\n"
                    "- Lint: `ruff check .`\n"
                ),
                encoding="utf-8",
            )
            run = subprocess.run(
                ["python3", str(SCRIPT), "--list"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)
            self.assertIn("python3 -m pytest -q", run.stdout)
            self.assertIn("ruff check .", run.stdout)

    def test_parses_comandos_essenciais_with_code_blocks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "AGENTS.md").write_text(
                (
                    "# AGENTS\n\n"
                    "## 2) Comandos essenciais\n\n"
                    "### Testes completos\n"
                    "```bash\n"
                    "python3 -m pytest -q\n"
                    "```\n\n"
                    "### Lint\n"
                    "```bash\n"
                    "ruff check .\n"
                    "```\n"
                ),
                encoding="utf-8",
            )

            run = subprocess.run(
                ["python3", str(SCRIPT), "--list"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)
            self.assertIn("python3 -m pytest -q", run.stdout)
            self.assertIn("ruff check .", run.stdout)

    def test_detects_python_stack_from_manage_py(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "manage.py").write_text("print('ok')\n", encoding="utf-8")
            run = subprocess.run(
                ["python3", str(SCRIPT), "--list"],
                cwd=str(root),
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)
            self.assertIn("python3 manage.py check", run.stdout)


if __name__ == "__main__":
    unittest.main()
