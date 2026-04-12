#!/usr/bin/env python3
"""Generate release evidence pack markdown from repository artifacts."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, asdict
from datetime import date
from pathlib import Path
from typing import List, Sequence


EXIT_OK = 0
EXIT_ERROR = 1
EXIT_POLICY = 2


@dataclass
class ChangeEntry:
    change_id: str
    path: str


@dataclass
class AdrEntry:
    title: str
    path: str


def normalize_version(version: str) -> str:
    v = version.strip()
    return v if v.startswith("v") else f"v{v}"


def collect_changes(root: Path, explicit: Sequence[str], max_changes: int) -> List[ChangeEntry]:
    if explicit:
        result: List[ChangeEntry] = []
        for cid in explicit:
            path = root / "openspec" / "changes" / "archive" / cid
            result.append(ChangeEntry(change_id=cid, path=path.relative_to(root).as_posix()))
        return result

    archive = root / "openspec" / "changes" / "archive"
    if not archive.exists():
        return []

    dirs = [p for p in archive.iterdir() if p.is_dir()]
    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)

    entries: List[ChangeEntry] = []
    for d in dirs[:max_changes]:
        entries.append(ChangeEntry(change_id=d.name, path=d.relative_to(root).as_posix()))
    return entries


def collect_adrs(root: Path, max_adrs: int) -> List[AdrEntry]:
    adr_dir = root / "docs" / "adr"
    if not adr_dir.exists():
        return []

    files = [p for p in adr_dir.glob("ADR-*.md") if p.is_file()]
    files.sort(key=lambda p: p.name)
    files = files[-max_adrs:]

    adrs: List[AdrEntry] = []
    for f in files:
        first = f.read_text(encoding="utf-8", errors="ignore").splitlines()
        title = first[0].lstrip("# ").strip() if first else f.stem
        adrs.append(AdrEntry(title=title, path=f.relative_to(root).as_posix()))
    return adrs


def render_markdown(
    *,
    version: str,
    release_date: str,
    previous_version: str,
    changes: Sequence[ChangeEntry],
    adrs: Sequence[AdrEntry],
) -> str:
    lines: List[str] = []
    lines.append(f"# Release Evidence Pack - {version}")
    lines.append("")
    lines.append(f"**Data da release:** {release_date}")
    lines.append(f"**Versão anterior:** {previous_version}")
    lines.append("**Responsável:** [preencher]")
    lines.append("")
    lines.append("## Resumo Executivo")
    lines.append("[Descrever o valor entregue e principais mudanças]")
    lines.append("")

    lines.append("## Changes Incluídos")
    if changes:
        lines.append("| Change ID | Link |")
        lines.append("|---|---|")
        for c in changes:
            lines.append(f"| {c.change_id} | [{c.path}]({c.path}) |")
    else:
        lines.append("- Nenhum change arquivado detectado automaticamente.")
    lines.append("")

    lines.append("## Specs Atualizadas")
    lines.append("[Listar specs relevantes alteradas nesta release]")
    lines.append("")

    lines.append("## ADRs Criadas/Afetadas")
    if adrs:
        for adr in adrs:
            lines.append(f"- [{adr.title}]({adr.path})")
    else:
        lines.append("- Nenhuma ADR detectada automaticamente.")
    lines.append("")

    lines.append("## Validação")
    lines.append("### Testes")
    lines.append("```text")
    lines.append("[colar output resumido]")
    lines.append("```")
    lines.append("")
    lines.append("### Lint/Type Check")
    lines.append("```text")
    lines.append("[colar output resumido]")
    lines.append("```")
    lines.append("")

    lines.append("## Rollout")
    lines.append("- [ ] plano de deploy validado")
    lines.append("- [ ] janelas de manutenção confirmadas")
    lines.append("")

    lines.append("## Rollback")
    lines.append("- [ ] procedimento de rollback documentado")
    lines.append("- [ ] gatilhos de rollback definidos")
    lines.append("")

    lines.append("## Checklist Final")
    lines.append("- [ ] changes listados")
    lines.append("- [ ] specs/ADRs revisadas")
    lines.append("- [ ] evidências de validação anexadas")
    lines.append("- [ ] aprovado para release")
    lines.append("")

    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate release evidence pack markdown")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--version", required=True, help="Release version (e.g. v1.2.0)")
    parser.add_argument("--date", dest="release_date", default=str(date.today()))
    parser.add_argument("--previous-version", default="[preencher]")
    parser.add_argument("--output", help="Output markdown file path")
    parser.add_argument("--changes", help="Comma-separated change ids")
    parser.add_argument("--max-changes", type=int, default=20)
    parser.add_argument("--max-adrs", type=int, default=10)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--fail-on",
        choices=["none", "missing-changes", "missing-adrs", "missing-any"],
        default="none",
        help="Policy threshold for missing artifacts",
    )
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    version = normalize_version(args.version)
    explicit = [c.strip() for c in (args.changes or "").split(",") if c.strip()]
    changes = collect_changes(root, explicit=explicit, max_changes=args.max_changes)
    adrs = collect_adrs(root, max_adrs=args.max_adrs)

    policy_failed = False
    if args.fail_on == "missing-changes":
        policy_failed = len(changes) == 0
    elif args.fail_on == "missing-adrs":
        policy_failed = len(adrs) == 0
    elif args.fail_on == "missing-any":
        policy_failed = len(changes) == 0 or len(adrs) == 0

    if args.output:
        out_path = (root / args.output).resolve()
    else:
        out_path = root / "docs" / "releases" / f"{args.release_date}_{version}.md"

    markdown = render_markdown(
        version=version,
        release_date=args.release_date,
        previous_version=args.previous_version,
        changes=changes,
        adrs=adrs,
    )

    if args.dry_run:
        if args.format == "json":
            payload = {
                "ok": not policy_failed,
                "policy_failed": policy_failed,
                "fail_on": args.fail_on,
                "version": version,
                "release_date": args.release_date,
                "output": str(out_path),
                "changes": [asdict(c) for c in changes],
                "adrs": [asdict(a) for a in adrs],
                "markdown": markdown,
            }
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(markdown)
            if policy_failed:
                print("\n[release-evidence-pack] policy threshold reached")
        return EXIT_POLICY if policy_failed else EXIT_OK

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(markdown + "\n", encoding="utf-8")

    if args.format == "json":
        payload = {
            "ok": not policy_failed,
            "policy_failed": policy_failed,
            "fail_on": args.fail_on,
            "output": str(out_path),
            "version": version,
            "release_date": args.release_date,
            "change_count": len(changes),
            "adr_count": len(adrs),
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"[release-evidence-pack] wrote {out_path}")
        print(f"  changes: {len(changes)}")
        print(f"  adrs: {len(adrs)}")
        if policy_failed:
            print("  policy: missing required artifacts")

    return EXIT_POLICY if policy_failed else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
