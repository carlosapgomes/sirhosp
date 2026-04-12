#!/usr/bin/env python3
"""Suggest (and optionally create) ADRs from active OpenSpec changes."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple


@dataclass
class AnalysisResult:
    change_id: Optional[str]
    score: int
    recommendation: str
    should_create: bool
    reasons: List[str]
    detected_signals: Dict[str, bool]
    title: str
    adr_id: str
    adr_path: str


EXIT_OK = 0
EXIT_ERROR = 1
EXIT_POLICY = 2

SIGNALS = {
    "architectural_change": {
        "keywords": [
            "arquitetura",
            "architecture",
            "refatoração estrutural",
            "refactor estrutural",
            "camada",
            "domain layer",
            "event-driven",
            "cqrs",
            "worker",
            "queue",
            "mensageria",
        ],
        "reason": "Mudança arquitetural relevante",
    },
    "dependency_or_platform_change": {
        "keywords": [
            "upgrade major",
            "breaking change",
            "troca de framework",
            "migrar framework",
            "nova dependência core",
            "provider",
            "postgresql",
            "kafka",
            "redis",
        ],
        "reason": "Mudança de plataforma/dependência com impacto estrutural",
    },
    "data_model_change": {
        "keywords": [
            "migration",
            "migração",
            "schema",
            "model",
            "modelo",
            "table",
            "tabela",
            "column",
            "coluna",
            "index",
            "índice",
            "database",
            "banco",
            "rollback caro",
        ],
        "reason": "Mudança significativa de modelo de dados",
    },
    "external_contract": {
        "keywords": [
            "api",
            "contrato externo",
            "webhook",
            "integração",
            "integration",
            "endpoint",
            "sdk",
        ],
        "reason": "Mudança de contrato externo/integração",
    },
    "security_policy": {
        "keywords": [
            "auth",
            "autenticação",
            "autorização",
            "permission",
            "oauth",
            "jwt",
            "token",
            "security",
            "segurança",
            "criptografia",
            "lgpd",
        ],
        "reason": "Mudança de política de segurança",
    },
    "high_risk_flag": {
        "keywords": [
            "high/arch",
            "high",
            "arquitetural",
            "risco 4",
            "risco 5",
            "risco 6",
            "risco 7",
            "risco 8",
            "rollback caro",
        ],
        "reason": "Indicador explícito de risco alto/arquitetural",
    },
}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def slugify(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    return value or "decision"


def title_from_change(change_id: str, text: str) -> str:
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            candidate = stripped.lstrip("#").strip()
            if candidate:
                return candidate

    words = [w for w in re.split(r"[-_\s]+", change_id) if w]
    return " ".join(w.capitalize() for w in words) if words else "Decision"


def find_latest_active_change(root: Path) -> Optional[str]:
    active = root / "openspec" / "changes" / "active"
    if not active.exists():
        return None

    dirs = [p for p in active.iterdir() if p.is_dir()]
    if not dirs:
        return None

    dirs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return dirs[0].name


def collect_change_text(root: Path, change_id: str) -> str:
    base = root / "openspec" / "changes" / "active" / change_id
    if not base.exists():
        return ""

    chunks: List[str] = []
    for rel in ["proposal.md", "design.md", "tasks.md"]:
        content = read_text(base / rel)
        if content:
            chunks.append(content)

    # include all markdown in specs deltas if present
    specs_dir = base / "specs"
    if specs_dir.exists():
        for p in specs_dir.rglob("*.md"):
            chunks.append(read_text(p))

    return "\n\n".join(chunks)


def detect_signals(text: str) -> Dict[str, bool]:
    lower = text.lower()
    detected: Dict[str, bool] = {}
    for name, spec in SIGNALS.items():
        detected[name] = any(k in lower for k in spec["keywords"])
    return detected


def compute_recommendation(signals: Dict[str, bool], threshold: int) -> Tuple[int, str, bool, List[str]]:
    score = sum(1 for v in signals.values() if v)
    reasons = [SIGNALS[k]["reason"] for k, ok in signals.items() if ok]

    if signals.get("high_risk_flag"):
        return score, "strong", True, reasons

    if score >= threshold:
        return score, "recommended", True, reasons

    if score == threshold - 1 and score > 0:
        return score, "consider", False, reasons

    return score, "optional", False, reasons


def next_adr_number(root: Path) -> int:
    adr_dir = root / "docs" / "adr"
    if not adr_dir.exists():
        return 1

    max_n = 0
    for p in adr_dir.glob("ADR-*.md"):
        m = re.match(r"ADR-(\d+)", p.name)
        if not m:
            continue
        max_n = max(max_n, int(m.group(1)))
    return max_n + 1


def build_adr_template(*, adr_id: str, title: str, change_id: Optional[str], reasons: Sequence[str]) -> str:
    reason_lines = "\n".join(f"- {r}" for r in reasons) if reasons else "- [preencher]"
    cid = change_id or "[preencher]"
    return (
        f"# {adr_id}: {title}\n\n"
        "## Status\n"
        "Proposed\n\n"
        "## Context\n"
        f"- Change ID: `{cid}`\n"
        "- Sinais detectados:\n"
        f"{reason_lines}\n\n"
        "## Decision\n"
        "[Descrever a decisão arquitetural]\n\n"
        "## Alternatives Considered\n"
        "1. [Alternativa A]\n"
        "2. [Alternativa B]\n\n"
        "## Consequences\n"
        "### Positive\n"
        "- [benefício]\n\n"
        "### Trade-offs\n"
        "- [custo/risco]\n"
    )


def analyze(root: Path, change_id: Optional[str], threshold: int) -> AnalysisResult:
    selected = change_id or find_latest_active_change(root)
    text = collect_change_text(root, selected) if selected else ""

    signals = detect_signals(text)
    score, recommendation, should_create, reasons = compute_recommendation(signals, threshold=threshold)

    if selected:
        title = title_from_change(selected, text)
    else:
        title = "Architectural Decision"

    n = next_adr_number(root)
    adr_id = f"ADR-{n:04d}"
    adr_slug = slugify(title)
    adr_path = (root / "docs" / "adr" / f"{adr_id}-{adr_slug}.md").relative_to(root).as_posix()

    return AnalysisResult(
        change_id=selected,
        score=score,
        recommendation=recommendation,
        should_create=should_create,
        reasons=reasons,
        detected_signals=signals,
        title=title,
        adr_id=adr_id,
        adr_path=adr_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Suggest ADR creation from active OpenSpec changes")
    parser.add_argument("change_id", nargs="?", help="Active change ID (optional)")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--threshold", type=int, default=2, help="Signals required to recommend ADR")
    parser.add_argument("--auto-create", action="store_true", help="Create ADR file when recommendation is positive")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--fail-on",
        choices=["none", "recommendation"],
        default="none",
        help="Policy threshold. Exit 2 when recommendation is triggered",
    )
    parser.add_argument(
        "--exit-on-recommendation",
        action="store_true",
        help="DEPRECATED: same as --fail-on recommendation",
    )
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    if args.exit_on_recommendation:
        args.fail_on = "recommendation"

    result = analyze(root, args.change_id, threshold=args.threshold)

    created = False
    if args.auto_create and result.should_create and not args.dry_run:
        path = root / result.adr_path
        path.parent.mkdir(parents=True, exist_ok=True)
        content = build_adr_template(
            adr_id=result.adr_id,
            title=result.title,
            change_id=result.change_id,
            reasons=result.reasons,
        )
        path.write_text(content, encoding="utf-8")
        created = True

    policy_failed = args.fail_on == "recommendation" and result.should_create and not created

    if args.format == "json":
        payload = {
            **asdict(result),
            "created": created,
            "fail_on": args.fail_on,
            "policy_failed": policy_failed,
            "ok": not policy_failed,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print("suggest-adr report")
        print("=" * 18)
        print(f"change: {result.change_id or '[none]'}")
        print(f"score: {result.score}")
        print(f"recommendation: {result.recommendation}")
        if result.reasons:
            print("reasons:")
            for r in result.reasons:
                print(f"- {r}")
        else:
            print("reasons: none")
        print(f"adr proposal: {result.adr_path}")
        if created:
            print("status: ADR file created")
        if policy_failed:
            print("status: policy threshold reached (recommendation)")

    return EXIT_POLICY if policy_failed else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
