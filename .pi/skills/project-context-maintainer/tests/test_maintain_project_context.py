#!/usr/bin/env python3
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "maintain_project_context.py"


class MaintainProjectContextTests(unittest.TestCase):
    def test_generates_project_context_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text(
                "# Meu Sistema\n\nSistema para gestao de processos publicos com foco em rastreabilidade.\n",
                encoding="utf-8",
            )
            (root / "AGENTS.md").write_text("# AGENTS\n", encoding="utf-8")
            (root / "app").mkdir()
            (root / "app" / "models.py").write_text("class X: pass\n", encoding="utf-8")
            (root / "docs").mkdir()
            (root / "docs" / "adr").mkdir()

            run = subprocess.run(
                ["python3", str(SCRIPT), "--project-root", str(root)],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)

            content = (root / "PROJECT_CONTEXT.md").read_text(encoding="utf-8")
            self.assertIn("## Fontes Autoritativas", content)
            self.assertIn("## Arquitetura de Alto Nivel", content)
            self.assertIn("Sistema para gestao de processos publicos", content)

    def test_check_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# X\n\ndesc suficiente para contexto.\n", encoding="utf-8")
            (root / "PROJECT_CONTEXT.md").write_text("old\n", encoding="utf-8")
            run = subprocess.run(
                ["python3", str(SCRIPT), "--project-root", str(root), "--check"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 2, msg=run.stderr)


if __name__ == "__main__":
    unittest.main()
