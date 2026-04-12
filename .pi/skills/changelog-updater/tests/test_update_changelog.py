#!/usr/bin/env python3
import json
import subprocess
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "update_changelog.py"


def run(cmd, cwd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=False)


def init_repo(root: Path) -> None:
    run(["git", "init"], cwd=root)
    run(["git", "config", "user.email", "test@example.com"], cwd=root)
    run(["git", "config", "user.name", "Test User"], cwd=root)


def commit_file(root: Path, path: str, content: str, msg: str) -> None:
    f = root / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(content, encoding="utf-8")
    run(["git", "add", path], cwd=root)
    result = run(["git", "commit", "-m", msg], cwd=root)
    if result.returncode != 0:
        raise RuntimeError(result.stderr)


class UpdateChangelogTests(unittest.TestCase):
    def test_fail_on_empty_returns_policy_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)

            run_result = run(
                [
                    "python3",
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    "--dry-run",
                    "--fail-on",
                    "empty",
                ],
                cwd=root,
            )
            self.assertEqual(run_result.returncode, 2, msg=run_result.stderr)

    def test_empty_repo_dry_run(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)

            run_result = run(
                ["python3", str(SCRIPT), "--project-root", str(root), "--dry-run"],
                cwd=root,
            )
            self.assertEqual(run_result.returncode, 0, msg=run_result.stderr)
            self.assertIn("No notable changes", run_result.stdout)

    def test_dry_run_groups_conventional_commits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            commit_file(root, "a.txt", "a\n", "feat: add login")
            commit_file(root, "b.txt", "b\n", "fix(api): handle timeout")

            run_result = run(
                [
                    "python3",
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    "--dry-run",
                ],
                cwd=root,
            )
            self.assertEqual(run_result.returncode, 0, msg=run_result.stderr)
            self.assertIn("## [Unreleased]", run_result.stdout)
            self.assertIn("### Added", run_result.stdout)
            self.assertIn("### Fixed", run_result.stdout)

    def test_write_changelog_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            commit_file(root, "a.txt", "a\n", "feat(core): add parser")

            run_result = run(
                ["python3", str(SCRIPT), "--project-root", str(root)],
                cwd=root,
            )
            self.assertEqual(run_result.returncode, 0, msg=run_result.stderr)

            changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
            self.assertIn("## [Unreleased]", changelog)
            self.assertIn("add parser", changelog)

    def test_uses_latest_tag_range_for_release(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            init_repo(root)
            commit_file(root, "base.txt", "base\n", "feat: base")
            run(["git", "tag", "v0.1.0"], cwd=root)
            commit_file(root, "new.txt", "new\n", "fix: post-tag bug")

            run_result = run(
                [
                    "python3",
                    str(SCRIPT),
                    "--project-root",
                    str(root),
                    "--release",
                    "v0.2.0",
                    "--format",
                    "json",
                ],
                cwd=root,
            )
            self.assertEqual(run_result.returncode, 0, msg=run_result.stderr)
            payload = json.loads(run_result.stdout)
            self.assertEqual(payload["commit_count"], 1)
            self.assertEqual(payload["tag_used"], "v0.1.0")

            changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
            self.assertIn("## [v0.2.0]", changelog)
            self.assertIn("post-tag bug", changelog)
            self.assertNotIn("feat: base", changelog)


if __name__ == "__main__":
    unittest.main()
