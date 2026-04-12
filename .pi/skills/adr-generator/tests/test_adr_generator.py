#!/usr/bin/env python3
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "adr_generator.py"


class AdrGeneratorTests(unittest.TestCase):
    def test_create_first_adr_and_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            run = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    "--title",
                    "Escolha de PostgreSQL como banco principal",
                    "--status",
                    "Accepted",
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)
            payload = json.loads(run.stdout)
            adr_path = Path(payload["created_adr"])
            self.assertTrue(adr_path.exists())
            self.assertIn("ADR-0001-escolha-de-postgresql-como-banco-principal.md", adr_path.name)

            content = adr_path.read_text(encoding="utf-8")
            self.assertIn("# ADR-0001:", content)
            self.assertIn("## Status", content)
            self.assertIn("Accepted", content)

            index = root / "docs" / "adr" / "README.md"
            self.assertTrue(index.exists())
            index_text = index.read_text(encoding="utf-8")
            self.assertIn("ADRs Ativas", index_text)
            self.assertIn("ADR-0001", index_text)

    def test_increment_number_with_existing_adr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adr_dir = root / "docs" / "adr"
            adr_dir.mkdir(parents=True, exist_ok=True)
            (adr_dir / "ADR-0005-antiga.md").write_text(
                "# ADR-0005: Antiga\n\n## Status\nAccepted\n",
                encoding="utf-8",
            )
            run = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    "--title",
                    "Nova decisao",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)
            created = list(adr_dir.glob("ADR-0006-*.md"))
            self.assertEqual(len(created), 1)

    def test_reindex_only_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adr_dir = root / "docs" / "adr"
            adr_dir.mkdir(parents=True, exist_ok=True)
            (adr_dir / "ADR-0001-a.md").write_text(
                "# ADR-0001: A\n\n## Status\nAccepted\n",
                encoding="utf-8",
            )
            (adr_dir / "ADR-0002-b.md").write_text(
                "# ADR-0002: B\n\n## Status\nSuperseded\n",
                encoding="utf-8",
            )

            run = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    "--reindex",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)

            index = (adr_dir / "README.md").read_text(encoding="utf-8")
            self.assertIn("ADRs Ativas", index)
            self.assertIn("ADRs Deprecated/Superseded", index)
            self.assertIn("ADR-0001", index)
            self.assertIn("ADR-0002", index)

    def test_list_next(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            adr_dir = root / "docs" / "adr"
            adr_dir.mkdir(parents=True, exist_ok=True)
            (adr_dir / "ADR-0012-x.md").write_text("# ADR-0012: X\n", encoding="utf-8")
            run = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    "--list-next",
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)
            payload = json.loads(run.stdout)
            self.assertEqual(payload["next_number"], 13)


if __name__ == "__main__":
    unittest.main()
