#!/usr/bin/env python3
"""
ADR Generator

Creates Architecture Decision Records with:
- automatic sequential numbering
- slugged filename
- markdown template
- index maintenance in docs/adr/README.md
"""

from __future__ import annotations

import argparse
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


ADR_NAME_PATTERN = re.compile(r"^ADR-(\d{4})(?:-.+)?\.md$", re.IGNORECASE)
VALID_STATUSES = {"Proposed", "Accepted", "Deprecated", "Superseded"}
INACTIVE_STATUSES = {"Deprecated", "Superseded"}


@dataclass
class AdrEntry:
    number: int
    file_name: str
    title: str
    status: str
    date: str


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_only.lower()
    lowered = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    return lowered or "sem-titulo"


def list_adr_files(adr_dir: Path) -> List[Path]:
    files: List[Path] = []
    for path in sorted(adr_dir.glob("ADR-*.md")):
        if ADR_NAME_PATTERN.match(path.name):
            files.append(path)
    return files


def next_number(adr_dir: Path) -> int:
    numbers: List[int] = []
    for path in list_adr_files(adr_dir):
        match = ADR_NAME_PATTERN.match(path.name)
        if match:
            numbers.append(int(match.group(1)))
    return (max(numbers) + 1) if numbers else 1


def parse_adr_metadata(path: Path) -> AdrEntry:
    text = _read_text(path)
    match_num = ADR_NAME_PATTERN.match(path.name)
    if not match_num:
        raise ValueError(f"invalid ADR name: {path.name}")
    number = int(match_num.group(1))

    title_match = re.search(rf"^#\s*ADR-{number:04d}:\s*(.+)$", text, flags=re.MULTILINE | re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else path.stem

    status_match = re.search(r"^##\s*Status\s*$\n([^\n]+)", text, flags=re.MULTILINE)
    if status_match:
        status = status_match.group(1).strip().strip("[]")
    else:
        status = "Unknown"

    timestamp = path.stat().st_mtime
    date = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
    return AdrEntry(number=number, file_name=path.name, title=title, status=status, date=date)


def build_adr_content(
    number: int,
    title: str,
    status: str,
    context: str,
    decision: str,
    alternatives: Sequence[str],
    positives: Sequence[str],
    negatives: Sequence[str],
    risks: Sequence[str],
) -> str:
    alt_lines: List[str] = []
    if alternatives:
        for idx, alt in enumerate(alternatives, start=1):
            alt_lines.append(f"{idx}. {alt}")
    else:
        alt_lines.extend(
            [
                "1. [Alternativa 1]: [Descricao breve e motivo de nao adocao]",
                "2. [Alternativa 2]: [Descricao breve e motivo de nao adocao]",
            ]
        )

    positive_lines = [f"- {item}" for item in positives] or ["- [Beneficio principal]"]
    negative_lines = [f"- {item}" for item in negatives] or ["- [Trade-off principal]"]
    risk_lines = [f"- {item}" for item in risks] or ["- [Risco]: [Mitigacao]"]

    lines: List[str] = []
    lines.append(f"# ADR-{number:04d}: {title}")
    lines.append("")
    lines.append("## Status")
    lines.append(status)
    lines.append("")
    lines.append("## Contexto")
    lines.append(context)
    lines.append("")
    lines.append("## Decisao")
    lines.append(decision)
    lines.append("")
    lines.append("## Alternativas Consideradas")
    lines.extend(alt_lines)
    lines.append("")
    lines.append("## Consequencias")
    lines.append("### Positivas")
    lines.extend(positive_lines)
    lines.append("")
    lines.append("### Negativas/Trade-offs")
    lines.extend(negative_lines)
    lines.append("")
    lines.append("### Riscos e Mitigacoes")
    lines.extend(risk_lines)
    lines.append("")
    return "\n".join(lines)


def build_index_content(entries: Sequence[AdrEntry]) -> str:
    active = [entry for entry in entries if entry.status not in INACTIVE_STATUSES]
    inactive = [entry for entry in entries if entry.status in INACTIVE_STATUSES]

    active.sort(key=lambda item: item.number)
    inactive.sort(key=lambda item: item.number)

    lines: List[str] = []
    lines.append("# Architecture Decision Records")
    lines.append("")
    lines.append("Registros de decisoes arquiteturais importantes do projeto.")
    lines.append("")
    lines.append("## ADRs Ativas")
    lines.append("| Numero | Titulo | Status | Data |")
    lines.append("|--------|--------|--------|------|")
    if active:
        for item in active:
            lines.append(
                f"| [ADR-{item.number:04d}]({item.file_name}) | {item.title} | {item.status} | {item.date} |"
            )
    else:
        lines.append("| - | - | - | - |")

    lines.append("")
    lines.append("## ADRs Deprecated/Superseded")
    lines.append("| Numero | Titulo | Status | Data |")
    lines.append("|--------|--------|--------|------|")
    if inactive:
        for item in inactive:
            lines.append(
                f"| [ADR-{item.number:04d}]({item.file_name}) | {item.title} | {item.status} | {item.date} |"
            )
    else:
        lines.append("| - | - | - | - |")

    lines.append("")
    lines.append("## Como criar uma nova ADR")
    lines.append("1. Execute `python3 adr_generator.py --title \"Sua decisao\"`")
    lines.append("2. Revise contexto, decisao, alternativas e consequencias")
    lines.append("3. Commit da ADR junto do change relacionado")
    lines.append("")
    return "\n".join(lines)


def write_index(adr_dir: Path) -> Path:
    entries = [parse_adr_metadata(path) for path in list_adr_files(adr_dir)]
    readme = adr_dir / "README.md"
    readme.write_text(build_index_content(entries), encoding="utf-8")
    return readme


def create_adr(
    adr_dir: Path,
    title: str,
    status: str,
    context: str,
    decision: str,
    alternatives: Sequence[str],
    positives: Sequence[str],
    negatives: Sequence[str],
    risks: Sequence[str],
    dry_run: bool,
    force: bool,
) -> Tuple[Path, bool]:
    number = next_number(adr_dir)
    slug = slugify(title)
    file_name = f"ADR-{number:04d}-{slug}.md"
    path = adr_dir / file_name

    if path.exists() and not force:
        raise FileExistsError(f"ADR file already exists: {path}")

    content = build_adr_content(
        number=number,
        title=title,
        status=status,
        context=context,
        decision=decision,
        alternatives=alternatives,
        positives=positives,
        negatives=negatives,
        risks=risks,
    )
    if not dry_run:
        path.write_text(content, encoding="utf-8")
    return path, dry_run


def main() -> int:
    parser = argparse.ArgumentParser(description="Create and maintain ADRs")
    parser.add_argument("--project-root", default=".", help="Project root")
    parser.add_argument("--adr-dir", default="docs/adr", help="ADR directory (relative to project root)")
    parser.add_argument("--title", help="ADR title")
    parser.add_argument("--status", default="Proposed", help="ADR status")
    parser.add_argument(
        "--context",
        default="[Descreva o problema, constraints e objetivo da decisao]",
        help="Context section text",
    )
    parser.add_argument(
        "--decision",
        default="[Descreva claramente a decisao tomada e escopo]",
        help="Decision section text",
    )
    parser.add_argument("--alternative", action="append", default=[], help="Alternative option (repeatable)")
    parser.add_argument("--positive", action="append", default=[], help="Positive consequence (repeatable)")
    parser.add_argument("--negative", action="append", default=[], help="Negative consequence (repeatable)")
    parser.add_argument("--risk", action="append", default=[], help="Risk/mitigation entry (repeatable)")
    parser.add_argument("--list-next", action="store_true", help="Only print next ADR number")
    parser.add_argument("--reindex", action="store_true", help="Rebuild docs/adr/README.md from ADR files")
    parser.add_argument("--no-index", action="store_true", help="Do not update index after creation")
    parser.add_argument("--dry-run", action="store_true", help="Plan only, do not write")
    parser.add_argument("--force", action="store_true", help="Overwrite if target ADR path exists")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    adr_dir = (root / args.adr_dir).resolve()
    adr_dir.mkdir(parents=True, exist_ok=True)

    # Normalize status.
    status = args.status.strip()
    if status:
        normalized = status[0].upper() + status[1:].lower()
    else:
        normalized = "Proposed"
    if normalized not in VALID_STATUSES:
        print(
            f"Invalid status '{args.status}'. Allowed: {sorted(VALID_STATUSES)}",
            file=sys.stderr,
        )
        return 1

    if args.list_next:
        number = next_number(adr_dir)
        payload = {"next_number": number, "suggested_file": f"ADR-{number:04d}-<slug>.md"}
        if args.format == "json":
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"Next ADR: ADR-{number:04d}")
        return 0

    if args.reindex:
        readme = adr_dir / "README.md"
        if args.dry_run:
            payload = {"action": "reindex", "path": str(readme), "dry_run": True}
        else:
            write_index(adr_dir)
            payload = {"action": "reindex", "path": str(readme), "dry_run": False}
        if args.format == "json":
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"[adr-generator] index {'planned' if args.dry_run else 'updated'}: {readme}")
        return 0

    if not args.title:
        parser.error("--title is required unless using --list-next or --reindex")

    try:
        adr_path, dry = create_adr(
            adr_dir=adr_dir,
            title=args.title,
            status=normalized,
            context=args.context,
            decision=args.decision,
            alternatives=args.alternative,
            positives=args.positive,
            negatives=args.negative,
            risks=args.risk,
            dry_run=args.dry_run,
            force=args.force,
        )
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    readme_path = adr_dir / "README.md"
    index_updated = False
    if not args.no_index:
        if not args.dry_run:
            write_index(adr_dir)
            index_updated = True
        else:
            index_updated = False

    payload: Dict[str, object] = {
        "created_adr": str(adr_path),
        "status": normalized,
        "dry_run": dry,
        "index_updated": index_updated,
        "index_path": str(readme_path),
    }

    if args.format == "json":
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        action = "planned" if args.dry_run else "created"
        print(f"[adr-generator] ADR {action}: {adr_path}")
        if args.no_index:
            print("[adr-generator] index update skipped (--no-index)")
        else:
            if args.dry_run:
                print(f"[adr-generator] index update planned: {readme_path}")
            else:
                print(f"[adr-generator] index updated: {readme_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
