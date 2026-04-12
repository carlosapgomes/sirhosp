#!/usr/bin/env python3
"""Suggest refactor sprint priorities from lightweight code heuristics."""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple


EXIT_OK = 0
EXIT_ERROR = 1
EXIT_POLICY = 2

SUPPORTED = {".py", ".js", ".ts", ".tsx", ".jsx"}
IGNORE_PARTS = {".git", "node_modules", ".venv", "venv", ".pi", ".codex"}


@dataclass
class Finding:
    kind: str
    severity: str
    score: int
    file: str
    line: int
    title: str
    detail: str
    suggestion: str
    effort_hours: str


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def iter_source_files(root: Path, include_tests: bool = False) -> Iterable[Path]:
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in SUPPORTED:
            continue
        parts = set(p.parts)
        if parts & IGNORE_PARTS:
            continue
        if not include_tests and "tests" in parts:
            continue
        yield p


def severity_for_score(score: int) -> str:
    if score >= 9:
        return "critical"
    if score >= 6:
        return "high"
    if score >= 3:
        return "medium"
    return "low"


def todo_findings(path: Path, root: Path) -> List[Finding]:
    findings: List[Finding] = []
    text = read_text(path)
    rel = path.relative_to(root).as_posix()
    for i, line in enumerate(text.splitlines(), start=1):
        if re.search(r"\b(TODO|FIXME|HACK|XXX)\b", line, re.IGNORECASE):
            findings.append(
                Finding(
                    kind="tech-debt-note",
                    severity="low",
                    score=2,
                    file=rel,
                    line=i,
                    title="Nota de dívida técnica pendente",
                    detail=line.strip()[:160],
                    suggestion="Criar issue vinculada e planejar remoção na sprint.",
                    effort_hours="0.5-1",
                )
            )
    return findings


def file_size_findings(path: Path, root: Path) -> List[Finding]:
    text = read_text(path)
    lines = text.splitlines()
    count = len(lines)
    rel = path.relative_to(root).as_posix()

    if count > 1200:
        score = 10
    elif count > 700:
        score = 8
    elif count > 400:
        score = 6
    elif count > 250:
        score = 4
    else:
        return []

    sev = severity_for_score(score)
    return [
        Finding(
            kind="long-file",
            severity=sev,
            score=score,
            file=rel,
            line=1,
            title=f"Arquivo muito grande ({count} linhas)",
            detail="Risco de baixa coesão e manutenção difícil.",
            suggestion="Dividir por responsabilidades/módulos menores.",
            effort_hours="2-8",
        )
    ]


def _control_node_count(node: ast.AST) -> int:
    controls = (ast.If, ast.For, ast.While, ast.Try, ast.With, ast.BoolOp, ast.Match)
    return sum(1 for n in ast.walk(node) if isinstance(n, controls))


def python_function_findings(path: Path, root: Path) -> List[Finding]:
    text = read_text(path)
    rel = path.relative_to(root).as_posix()
    findings: List[Finding] = []

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return findings

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        end = getattr(node, "end_lineno", node.lineno)
        length = end - node.lineno + 1
        params = len(node.args.args) + len(node.args.kwonlyargs)
        complexity_proxy = _control_node_count(node)

        score = 0
        if length > 120:
            score += 6
        elif length > 80:
            score += 5
        elif length > 50:
            score += 3

        if params > 8:
            score += 3
        elif params > 5:
            score += 2

        if complexity_proxy > 20:
            score += 4
        elif complexity_proxy > 12:
            score += 3
        elif complexity_proxy > 8:
            score += 2

        if score == 0:
            continue

        sev = severity_for_score(score)
        findings.append(
            Finding(
                kind="long-or-complex-function",
                severity=sev,
                score=score,
                file=rel,
                line=node.lineno,
                title=f"Função '{node.name}' potencial hotspot",
                detail=(
                    f"linhas={length}, params={params}, complexidade_proxy={complexity_proxy}"
                ),
                suggestion="Quebrar em funções menores e extrair regras de negócio.",
                effort_hours="2-6",
            )
        )

    return findings


def duplicate_block_findings(root: Path, min_lines: int = 4, include_tests: bool = False) -> List[Finding]:
    blocks: Dict[str, List[Tuple[str, int]]] = {}

    for p in iter_source_files(root, include_tests=include_tests):
        text = read_text(p)
        lines = [ln.rstrip() for ln in text.splitlines()]
        rel = p.relative_to(root).as_posix()

        if len(lines) < min_lines:
            continue

        for i in range(0, len(lines) - min_lines + 1):
            window = lines[i : i + min_lines]
            if any(len(w.strip()) < 6 for w in window):
                continue
            signature = "\n".join(window)
            blocks.setdefault(signature, []).append((rel, i + 1))

    findings: List[Finding] = []
    for signature, refs in blocks.items():
        unique_files = sorted({r[0] for r in refs})
        if len(unique_files) < 2:
            continue

        score = min(10, 3 + len(unique_files))
        sev = severity_for_score(score)
        file, line = refs[0]
        detail = f"Bloco repetido em {len(unique_files)} arquivos: {', '.join(unique_files[:4])}"
        findings.append(
            Finding(
                kind="duplicated-block",
                severity=sev,
                score=score,
                file=file,
                line=line,
                title="Duplicação de código detectada",
                detail=detail,
                suggestion="Extrair helper/serviço reutilizável para remover copy-paste.",
                effort_hours="2-5",
            )
        )

    return findings


def churn_hotspots(root: Path, include_tests: bool = False) -> List[Finding]:
    if not (root / ".git").exists():
        return []

    proc = subprocess.run(
        ["git", "-C", str(root), "log", "--name-only", "--since=60 days ago", "--pretty=format:"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []

    counts: Dict[str, int] = {}
    for line in proc.stdout.splitlines():
        path = line.strip()
        if not path:
            continue
        p = Path(path)
        if p.suffix.lower() not in SUPPORTED:
            continue
        parts = set(p.parts)
        if parts & IGNORE_PARTS:
            continue
        if not include_tests and "tests" in parts:
            continue
        counts[path] = counts.get(path, 0) + 1

    findings: List[Finding] = []
    for path, n in sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[:10]:
        if n < 5:
            continue
        score = min(10, 2 + n // 3)
        sev = severity_for_score(score)
        findings.append(
            Finding(
                kind="high-churn",
                severity=sev,
                score=score,
                file=path,
                line=1,
                title=f"Arquivo com alto churn ({n} alterações em ~60 dias)",
                detail="Hotspot recorrente de mudanças/bugs.",
                suggestion="Planejar refactor incremental + testes de caracterização.",
                effort_hours="2-4",
            )
        )

    return findings


def summarize(findings: Sequence[Finding]) -> Dict[str, int]:
    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for f in findings:
        counts[f.severity] += 1
    return counts


def render_text(findings: Sequence[Finding], files_scanned: int, max_items: int) -> str:
    counts = summarize(findings)
    lines: List[str] = []
    lines.append("refactor-sprint-suggester report")
    lines.append("=" * 30)
    lines.append(f"Files scanned: {files_scanned}")
    lines.append(f"Findings total: {len(findings)}")
    lines.append(
        f"Severity: critical={counts['critical']} high={counts['high']} medium={counts['medium']} low={counts['low']}"
    )
    lines.append("")

    if not findings:
        lines.append("✅ Sem hotspots relevantes detectados.")
        return "\n".join(lines) + "\n"

    lines.append("Top prioridades:")
    for i, f in enumerate(findings[:max_items], start=1):
        lines.append(
            f"{i}. [{f.severity.upper()}|score={f.score}] {f.file}:{f.line} — {f.title}"
        )
        lines.append(f"   detalhe: {f.detail}")
        lines.append(f"   sugestão: {f.suggestion}")
        lines.append(f"   esforço: {f.effort_hours}h")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Suggest prioritized refactor sprint items")
    parser.add_argument("--project-root", default=".")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument("--max-items", type=int, default=10)
    parser.add_argument("--output", help="Optional markdown output report path")
    parser.add_argument("--include-tests", action="store_true", help="Include test files in analysis")
    parser.add_argument(
        "--fail-on",
        choices=["none", "critical", "high", "medium", "low"],
        default="none",
        help="Exit non-zero when findings at/above severity exist",
    )
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    files = list(iter_source_files(root, include_tests=args.include_tests))

    findings: List[Finding] = []

    for p in files:
        findings.extend(todo_findings(p, root))
        findings.extend(file_size_findings(p, root))
        if p.suffix.lower() == ".py":
            findings.extend(python_function_findings(p, root))

    findings.extend(duplicate_block_findings(root, include_tests=args.include_tests))
    findings.extend(churn_hotspots(root, include_tests=args.include_tests))

    findings.sort(key=lambda f: (f.score, f.severity), reverse=True)

    if args.output:
        report = render_text(findings, files_scanned=len(files), max_items=args.max_items)
        out_path = (root / args.output).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report, encoding="utf-8")

    fail = False
    if args.fail_on != "none":
        threshold = {"low": 1, "medium": 2, "high": 3, "critical": 4}[args.fail_on]
        for f in findings:
            sev = {"low": 1, "medium": 2, "high": 3, "critical": 4}[f.severity]
            if sev >= threshold:
                fail = True
                break

    if args.format == "json":
        payload = {
            "ok": not fail,
            "policy_failed": fail,
            "files_scanned": len(files),
            "findings": [asdict(f) for f in findings],
            "counts": summarize(findings),
            "max_items": args.max_items,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(render_text(findings, files_scanned=len(files), max_items=args.max_items), end="")

    return EXIT_POLICY if fail else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
