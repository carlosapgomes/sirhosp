#!/usr/bin/env python3
"""Generate/update CHANGELOG.md from git history.

Conventional Commit friendly and stdlib-only.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from datetime import date
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass
class Commit:
    hash: str
    subject: str
    body: str
    author: str
    date: str
    ctype: str
    scope: Optional[str]
    breaking: bool
    description: str


TYPE_TO_SECTION = {
    "feat": "Added",
    "fix": "Fixed",
    "perf": "Changed",
    "refactor": "Changed",
    "docs": "Documentation",
    "style": "Maintenance",
    "test": "Maintenance",
    "build": "Maintenance",
    "ci": "Maintenance",
    "chore": "Maintenance",
    "revert": "Changed",
    "remove": "Removed",
    "security": "Security",
}

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_POLICY = 2

ORDER = ["Added", "Changed", "Fixed", "Removed", "Security", "Documentation", "Maintenance"]


def run_git(root: Path, args: Sequence[str]) -> Tuple[int, str, str]:
    proc = subprocess.run(
        ["git", "-C", str(root), *args],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode, proc.stdout, proc.stderr


def latest_tag(root: Path) -> Optional[str]:
    code, out, _ = run_git(root, ["describe", "--tags", "--abbrev=0"])
    if code != 0:
        return None
    tag = out.strip()
    return tag if tag else None


def parse_subject(subject: str, body: str) -> Tuple[str, Optional[str], bool, str]:
    m = re.match(r"^(?P<type>[a-zA-Z0-9_-]+)(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?:\s+(?P<desc>.+)$", subject)
    breaking_by_body = "BREAKING CHANGE" in body.upper()
    if not m:
        return "other", None, breaking_by_body, subject.strip()

    ctype = m.group("type").lower()
    scope = m.group("scope")
    breaking = bool(m.group("bang")) or breaking_by_body
    desc = m.group("desc").strip()
    return ctype, scope, breaking, desc


def collect_commits(root: Path, from_ref: Optional[str], to_ref: str, include_merges: bool) -> Tuple[List[Commit], Optional[str]]:
    # Handle empty repositories gracefully.
    code, _, _ = run_git(root, ["rev-parse", "--verify", "HEAD"])
    if code != 0:
        return [], None

    tag_used: Optional[str] = None
    ref_range: Optional[str]

    if from_ref:
        ref_range = f"{from_ref}..{to_ref}"
    else:
        tag_used = latest_tag(root)
        ref_range = f"{tag_used}..{to_ref}" if tag_used else None

    pretty = "%h%x1f%s%x1f%b%x1f%an%x1f%ad"
    args = ["log", f"--pretty=format:{pretty}", "--date=short"]
    if not include_merges:
        args.append("--no-merges")
    if ref_range:
        args.append(ref_range)
    else:
        args.append(to_ref)

    code, out, err = run_git(root, args)
    if code != 0:
        raise RuntimeError((err or out or "failed to read git log").strip())

    commits: List[Commit] = []
    for line in out.splitlines():
        parts = line.split("\x1f")
        if len(parts) != 5:
            continue
        h, subject, body, author, cdate = [p.strip() for p in parts]
        ctype, scope, breaking, desc = parse_subject(subject, body)
        commits.append(
            Commit(
                hash=h,
                subject=subject,
                body=body,
                author=author,
                date=cdate,
                ctype=ctype,
                scope=scope,
                breaking=breaking,
                description=desc,
            )
        )

    return commits, tag_used


def section_for_commit(commit: Commit) -> str:
    if commit.breaking:
        return "Changed"

    if re.search(r"\bsecurity\b", commit.subject, re.IGNORECASE) or re.search(
        r"\bsecurity\b", commit.body, re.IGNORECASE
    ):
        return "Security"

    return TYPE_TO_SECTION.get(commit.ctype, "Changed")


def render_entries(commits: Sequence[Commit]) -> Tuple[Dict[str, List[str]], int]:
    grouped: Dict[str, List[str]] = {name: [] for name in ORDER}
    other: List[str] = []

    for c in commits:
        section = section_for_commit(c)
        scope_prefix = f"**{c.scope}:** " if c.scope else ""
        suffix = " ⚠️ BREAKING" if c.breaking else ""
        entry = f"- {scope_prefix}{c.description} (`{c.hash}`){suffix}"
        if section in grouped:
            grouped[section].append(entry)
        else:
            other.append(entry)

    if other:
        grouped.setdefault("Changed", []).extend(other)

    total = sum(len(v) for v in grouped.values())
    return grouped, total


def render_section(title: str, entries: Dict[str, List[str]]) -> str:
    lines = [title, ""]
    any_entry = False
    for sec in ORDER:
        items = entries.get(sec, [])
        if not items:
            continue
        any_entry = True
        lines.append(f"### {sec}")
        lines.extend(items)
        lines.append("")

    if not any_entry:
        lines.append("- No notable changes.")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def default_changelog() -> str:
    return (
        "# Changelog\n\n"
        "All notable changes to this project will be documented in this file.\n\n"
        "## [Unreleased]\n\n"
        "- No notable changes.\n"
    )


def upsert_section(content: str, heading: str, new_section: str) -> str:
    if not content.strip():
        content = default_changelog()

    pattern = re.compile(rf"^({re.escape(heading)}\n(?:.*?))(?:^##\s|\Z)", re.MULTILINE | re.DOTALL)
    m = pattern.search(content)
    if m:
        start, end = m.span(1)
        return content[:start] + new_section + content[end:]

    # Insert after first title paragraph.
    title_match = re.search(r"^#\s+.*\n(?:\n.*\n)*?\n", content)
    if title_match:
        idx = title_match.end()
        return content[:idx] + new_section + "\n" + content[idx:]

    return content.rstrip() + "\n\n" + new_section


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate/update CHANGELOG.md from git commits")
    parser.add_argument("--project-root", default=".", help="Repository root")
    parser.add_argument("--output", default="CHANGELOG.md", help="Output changelog path")
    parser.add_argument("--from-ref", help="Start ref (default: latest tag)")
    parser.add_argument("--to-ref", default="HEAD", help="End ref (default: HEAD)")
    parser.add_argument("--release", help="Release version (e.g. v1.2.0). Default updates [Unreleased]")
    parser.add_argument("--date", dest="release_date", help="Release date YYYY-MM-DD")
    parser.add_argument("--include-merges", action="store_true", help="Include merge commits")
    parser.add_argument("--dry-run", action="store_true", help="Print section only")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--fail-on",
        choices=["none", "empty"],
        default="none",
        help="Policy threshold. Exit 2 when no commits are found",
    )
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    output_path = (root / args.output).resolve()

    commits, tag_used = collect_commits(
        root,
        from_ref=args.from_ref,
        to_ref=args.to_ref,
        include_merges=args.include_merges,
    )

    grouped, total_entries = render_entries(commits)
    policy_failed = args.fail_on == "empty" and len(commits) == 0

    if args.release:
        rel_date = args.release_date or str(date.today())
        heading = f"## [{args.release}] - {rel_date}"
    else:
        heading = "## [Unreleased]"

    section_md = render_section(heading, grouped)

    if args.dry_run:
        if args.format == "json":
            payload = {
                "ok": not policy_failed,
                "policy_failed": policy_failed,
                "fail_on": args.fail_on,
                "heading": heading,
                "entries": grouped,
                "commit_count": len(commits),
                "tag_used": tag_used,
                "from_ref": args.from_ref or tag_used,
                "to_ref": args.to_ref,
            }
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(section_md, end="")
            if policy_failed:
                print("\n[changelog-updater] policy threshold reached: empty commit range")
        return EXIT_POLICY if policy_failed else EXIT_OK

    current = output_path.read_text(encoding="utf-8") if output_path.exists() else default_changelog()
    updated = upsert_section(current, heading, section_md)
    output_path.write_text(updated, encoding="utf-8")

    if args.format == "json":
        payload = {
            "ok": not policy_failed,
            "policy_failed": policy_failed,
            "fail_on": args.fail_on,
            "output": str(output_path),
            "heading": heading,
            "commit_count": len(commits),
            "entry_count": total_entries,
            "tag_used": tag_used,
            "from_ref": args.from_ref or tag_used,
            "to_ref": args.to_ref,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"[changelog-updater] wrote {output_path}")
        print(f"  heading: {heading}")
        print(f"  commits: {len(commits)}")
        print(f"  entries: {total_entries}")
        if policy_failed:
            print("  policy: empty commit range")

    return EXIT_POLICY if policy_failed else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
