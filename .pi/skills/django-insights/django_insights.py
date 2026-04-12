#!/usr/bin/env python3
"""Django project diagnostics (performance, security, architecture)."""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Set


@dataclass
class Finding:
    category: str
    severity: str
    file: str
    line: int
    message: str
    suggestion: str


EXIT_OK = 0
EXIT_ERROR = 1
EXIT_POLICY = 2

SEVERITY_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def iter_python_files(root: Path, app: str | None = None) -> Iterable[Path]:
    base = root / app if app else root
    if not base.exists():
        return []

    files: List[Path] = []
    for p in base.rglob("*.py"):
        posix = p.as_posix()
        if "/.git/" in posix or "/node_modules/" in posix or "/.venv/" in posix or "/venv/" in posix or "/.pi/" in posix or "/.codex/" in posix:
            continue
        files.append(p)
    return files


def detect_settings_security(path: Path, root: Path) -> List[Finding]:
    findings: List[Finding] = []
    text = read_text(path)
    rel = path.relative_to(root).as_posix()

    for i, line in enumerate(text.splitlines(), start=1):
        if re.search(r"^\s*DEBUG\s*=\s*True\b", line):
            findings.append(
                Finding(
                    category="security",
                    severity="critical",
                    file=rel,
                    line=i,
                    message="DEBUG=True em settings",
                    suggestion="Desativar DEBUG em produção e usar variáveis de ambiente.",
                )
            )
        if re.search(r"^\s*ALLOWED_HOSTS\s*=\s*\[\s*\]\s*$", line):
            findings.append(
                Finding(
                    category="security",
                    severity="high",
                    file=rel,
                    line=i,
                    message="ALLOWED_HOSTS vazio",
                    suggestion="Definir hosts permitidos por ambiente.",
                )
            )
        if re.search(r"SECRET_KEY\s*=\s*['\"](?!.*(env|os\.getenv))", line):
            findings.append(
                Finding(
                    category="security",
                    severity="high",
                    file=rel,
                    line=i,
                    message="Possível SECRET_KEY hardcoded",
                    suggestion="Mover SECRET_KEY para variável de ambiente.",
                )
            )

    return findings


def detect_python_code_smells(path: Path, root: Path) -> List[Finding]:
    findings: List[Finding] = []
    text = read_text(path)
    rel = path.relative_to(root).as_posix()
    lines = text.splitlines()

    for i, line in enumerate(lines, start=1):
        if re.search(r"\bprint\s*\(", line):
            findings.append(
                Finding(
                    category="architecture",
                    severity="low",
                    file=rel,
                    line=i,
                    message="print() detectado",
                    suggestion="Preferir logging estruturado.",
                )
            )

        if re.search(r"^\s*from\s+.+\s+import\s+\*", line):
            findings.append(
                Finding(
                    category="architecture",
                    severity="medium",
                    file=rel,
                    line=i,
                    message="Wildcard import detectado",
                    suggestion="Importar símbolos explicitamente.",
                )
            )

        if re.search(r"\b(raw|execute|executemany)\s*\(\s*f['\"]", line):
            findings.append(
                Finding(
                    category="security",
                    severity="critical",
                    file=rel,
                    line=i,
                    message="SQL com f-string detectado",
                    suggestion="Usar queries parametrizadas.",
                )
            )

    if path.name == "views.py":
        findings.extend(detect_view_performance(lines, rel))

    return findings


def detect_view_performance(lines: Sequence[str], rel: str) -> List[Finding]:
    findings: List[Finding] = []
    for i, line in enumerate(lines, start=1):
        if not re.search(r"\bfor\s+\w+\s+in\s+.+:", line):
            continue

        window = lines[i : min(i + 4, len(lines))]
        for j, nxt in enumerate(window, start=i + 1):
            if re.search(r"\b\w+\.[a-zA-Z_]+\.[a-zA-Z_]+", nxt) and "select_related" not in "\n".join(window):
                findings.append(
                    Finding(
                        category="performance",
                        severity="medium",
                        file=rel,
                        line=j,
                        message="Padrão potencial de N+1 query em loop",
                        suggestion="Avaliar select_related/prefetch_related.",
                    )
                )
                break
    return findings


def should_include(category: str, focus: Set[str]) -> bool:
    return not focus or category in focus


def render_text(findings: Sequence[Finding], focus: Set[str], files_scanned: int) -> str:
    lines: List[str] = []
    lines.append("django-insights report")
    lines.append("=" * 21)
    lines.append(f"Files scanned: {files_scanned}")
    lines.append(f"Focus: {', '.join(sorted(focus)) if focus else 'all'}")
    lines.append("")

    if not findings:
        lines.append("✅ No findings.")
        return "\n".join(lines) + "\n"

    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        counts[f.severity] += 1

    lines.append(f"Findings: {len(findings)}")
    lines.append(f"  critical: {counts['critical']}")
    lines.append(f"  high:     {counts['high']}")
    lines.append(f"  medium:   {counts['medium']}")
    lines.append(f"  low:      {counts['low']}")
    lines.append("")

    for f in findings:
        lines.append(f"- [{f.severity.upper()}] ({f.category}) {f.file}:{f.line} {f.message}")
        lines.append(f"  suggestion: {f.suggestion}")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Django diagnostics for performance/security/architecture")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--app", help="Optional app directory to scope analysis")
    parser.add_argument(
        "--focus",
        help="Comma separated categories: performance,security,architecture",
    )
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--fail-on",
        choices=["critical", "high", "medium", "low", "none"],
        default="high",
        help="Exit non-zero when findings at or above this severity exist",
    )
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    focus = {x.strip() for x in (args.focus or "").split(",") if x.strip()}

    files = list(iter_python_files(root, app=args.app))

    findings: List[Finding] = []
    for f in files:
        if f.name in {"settings.py", "settings_local.py", "settings_prod.py"}:
            findings.extend(detect_settings_security(f, root))
        findings.extend(detect_python_code_smells(f, root))

    filtered = [f for f in findings if should_include(f.category, focus)]

    threshold = args.fail_on
    failing = False
    if threshold != "none":
        failing = any(SEVERITY_RANK[f.severity] >= SEVERITY_RANK[threshold] for f in filtered)

    if args.format == "json":
        payload = {
            "ok": not failing,
            "policy_failed": failing,
            "files_scanned": len(files),
            "focus": sorted(focus),
            "fail_on": threshold,
            "findings": [asdict(f) for f in filtered],
            "counts": {
                "critical": sum(1 for f in filtered if f.severity == "critical"),
                "high": sum(1 for f in filtered if f.severity == "high"),
                "medium": sum(1 for f in filtered if f.severity == "medium"),
                "low": sum(1 for f in filtered if f.severity == "low"),
            },
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(render_text(filtered, focus, len(files)), end="")

    return EXIT_POLICY if failing else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
