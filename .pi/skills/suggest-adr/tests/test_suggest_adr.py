#!/usr/bin/env python3
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "suggest_adr.py"


def write_change(root: Path, change_id: str, proposal: str, design: str = "") -> None:
    base = root / "openspec" / "changes" / "active" / change_id
    base.mkdir(parents=True, exist_ok=True)
    (base / "proposal.md").write_text(proposal, encoding="utf-8")
    if design:
        (base / "design.md").write_text(design, encoding="utf-8")


class SuggestAdrTests(unittest.TestCase):
    def test_fail_on_recommendation_returns_policy_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_change(
                root,
                "risky-change",
                "# Risco\n\nMudança de arquitetura com migração database e auth HIGH/ARCH",
            )

            run = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    "risky-change",
                    "--fail-on",
                    "recommendation",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 2)

    def test_recommends_for_high_risk_signals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_change(
                root,
                "migrate-auth-db",
                "# Migração auth\n\nImplementar migração de database com OAuth e mudança de arquitetura. risco HIGH/ARCH",
            )

            run = subprocess.run(
                ["python3", str(SCRIPT), "--project-root", str(root), "migrate-auth-db", "--format", "json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)
            payload = json.loads(run.stdout)
            self.assertTrue(payload["should_create"])
            self.assertIn(payload["recommendation"], {"strong", "recommended"})

    def test_optional_for_low_signal_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_change(root, "fix-typo", "# Fix typo\n\nAjustar texto em mensagem de erro.")

            run = subprocess.run(
                ["python3", str(SCRIPT), "--project-root", str(root), "fix-typo", "--format", "json"],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)
            payload = json.loads(run.stdout)
            self.assertFalse(payload["should_create"])

    def test_auto_create_generates_adr_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_change(
                root,
                "introduce-event-bus",
                "# Introduce event bus\n\nAdicionar worker queue e integração API externa.",
            )

            run = subprocess.run(
                [
                    "python3",
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    "introduce-event-bus",
                    "--auto-create",
                    "--format",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(run.returncode, 0, msg=run.stderr)
            payload = json.loads(run.stdout)
            self.assertTrue(payload["created"])
            target = root / payload["adr_path"]
            self.assertTrue(target.exists())
            self.assertIn("ADR-", target.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
