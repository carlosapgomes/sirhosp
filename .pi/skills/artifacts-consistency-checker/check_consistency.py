#!/usr/bin/env python3
"""
Artifacts Consistency Checker

Checks consistency between:
1) specs and code
2) ADRs and implementation
3) AGENTS.md and project reality
4) PROJECT_CONTEXT.md and repository structure
5) markdown links
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


CODE_EXTENSIONS = {
    ".py",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".java",
    ".rb",
    ".php",
    ".rs",
    ".kt",
    ".swift",
    ".c",
    ".cpp",
    ".h",
    ".hpp",
}

IGNORE_DIRS = {
    ".git",
    "__pycache__",
    ".venv",
    "venv",
    "node_modules",
    "dist",
    "build",
    ".mypy_cache",
    ".pytest_cache",
}

STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "como",
    "para",
    "com",
    "uma",
    "de",
    "do",
    "da",
    "dos",
    "das",
    "em",
    "por",
    "sobre",
    "versao",
    "version",
    "change",
    "spec",
}


@dataclass
class Finding:
    level: str  # error | warning | info
    category: str
    message: str
    details: str = ""
    files: Optional[List[str]] = None
    suggestion: str = ""


@dataclass
class CheckResult:
    checks: Dict[str, Dict[str, int]]
    findings: List[Finding]


class Reporter:
    def __init__(self) -> None:
        self.findings: List[Finding] = []
        self.counts: Dict[str, Dict[str, int]] = {}

    def add(
        self,
        level: str,
        category: str,
        message: str,
        details: str = "",
        files: Optional[List[str]] = None,
        suggestion: str = "",
    ) -> None:
        self.findings.append(
            Finding(
                level=level,
                category=category,
                message=message,
                details=details,
                files=files or [],
                suggestion=suggestion,
            )
        )

    def bump(self, category: str, key: str) -> None:
        self.counts.setdefault(category, {})
        self.counts[category][key] = self.counts[category].get(key, 0) + 1


# -----------------------------------------------------------------------------
# Helpers
# -----------------------------------------------------------------------------


def iter_files(root: Path, suffixes: Optional[Sequence[str]] = None) -> Iterable[Path]:
    suffix_set = set(suffixes or [])
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if suffix_set and path.suffix not in suffix_set:
            continue
        yield path


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def normalize_words(text: str, min_len: int = 4, max_words: int = 15) -> List[str]:
    words = re.findall(r"[A-Za-z0-9_\-]{4,}", text.lower())
    filtered: List[str] = []
    for word in words:
        key = word.strip("-_")
        if len(key) < min_len or key in STOPWORDS:
            continue
        if key not in filtered:
            filtered.append(key)
        if len(filtered) >= max_words:
            break
    return filtered


def markdown_links(text: str) -> List[str]:
    return re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)


def _looks_like_command(line: str) -> bool:
    if not line or line.startswith("#"):
        return False
    if line.startswith(("-", "*")):
        return False
    return bool(re.match(r"^[A-Za-z0-9_./-]+", line))


def extract_commands_from_agents(text: str) -> List[Tuple[str, str]]:
    """Parse both 'Comandos de Validacao' and 'Comandos essenciais' styles."""
    headers = [
        r"^##\s*2[\.)]?\s*Comandos de Validacao",
        r"^##\s*2[\.)]?\s*Comandos essenciais",
        r"^##\s*Comandos de Validacao",
        r"^##\s*Comandos essenciais",
    ]

    lines = text.splitlines()
    in_section = False
    in_codeblock = False
    subsection = "command"
    commands: List[Tuple[str, str]] = []

    for raw in lines:
        line = raw.rstrip()
        if any(re.match(pattern, line, re.IGNORECASE) for pattern in headers):
            in_section = True
            in_codeblock = False
            continue

        if in_section and re.match(r"^##\s+", line):
            break

        if not in_section:
            continue

        if line.strip().startswith("###"):
            subsection = re.sub(r"^#+\s*", "", line).strip().lower() or "command"
            continue

        if line.strip().startswith("```"):
            in_codeblock = not in_codeblock
            continue

        inline = re.search(r"`([^`]+)`", line)
        if inline:
            label_match = re.match(r"^\s*[-*]\s*([^:]+):", line)
            label = (label_match.group(1).strip().lower() if label_match else subsection)
            commands.append((label, inline.group(1).strip()))
            continue

        if in_codeblock and _looks_like_command(line.strip()):
            commands.append((subsection, line.strip()))

    dedup: List[Tuple[str, str]] = []
    seen = set()
    for label, command in commands:
        key = (label, command)
        if key in seen:
            continue
        seen.add(key)
        dedup.append((label, command))
    return dedup


def command_available(command: str) -> bool:
    parts = shlex.split(command)
    if not parts:
        return False
    token = parts[0]
    if token in {
        "python",
        "python3",
        "bash",
        "sh",
        "npm",
        "pnpm",
        "yarn",
        "git",
        "make",
        "ruff",
        "mypy",
        "pytest",
        "uv",
        "poetry",
    }:
        return True
    return Path(token).exists()


# -----------------------------------------------------------------------------
# Checks
# -----------------------------------------------------------------------------


def check_required_files(root: Path, rep: Reporter) -> None:
    category = "required_files"
    required = ["AGENTS.md"]
    recommended = ["PROJECT_CONTEXT.md", "docs/adr", "docs/releases"]

    for rel in required:
        path = root / rel
        if path.exists():
            rep.bump(category, "required_present")
        else:
            rep.add(
                "error",
                category,
                f"Arquivo obrigatorio ausente: {rel}",
                suggestion=f"Criar {rel}.",
            )
            rep.bump(category, "required_missing")

    for rel in recommended:
        path = root / rel
        if path.exists():
            rep.bump(category, "recommended_present")
        else:
            rep.add("warning", category, f"Artefato recomendado ausente: {rel}")
            rep.bump(category, "recommended_missing")


def check_specs_vs_code(root: Path, rep: Reporter, max_specs: int = 25) -> None:
    category = "specs_vs_code"
    specs_root = root / "openspec" / "specs"

    if not specs_root.exists():
        rep.add("warning", category, "Diretorio openspec/specs nao encontrado")
        return

    spec_files = sorted(specs_root.rglob("*.md"))
    if not spec_files:
        rep.add("warning", category, "Nenhuma spec markdown encontrada")
        return

    code_files = list(iter_files(root, CODE_EXTENSIONS))
    if not code_files:
        rep.add("warning", category, "Nenhum arquivo de codigo encontrado para comparar")
        return

    code_contents = [(p, read_text(p).lower()) for p in code_files[:400]]
    missing_impl: List[str] = []

    for spec_path in spec_files[:max_specs]:
        text = read_text(spec_path)
        headings = " ".join([line for line in text.splitlines() if line.startswith("#")])
        terms = normalize_words(headings + " " + text, max_words=10)
        if not terms:
            rep.bump(category, "specs_without_terms")
            continue

        found = False
        for _, content in code_contents:
            if any(term in content for term in terms[:5]):
                found = True
                break
        if found:
            rep.bump(category, "specs_with_impl")
        else:
            missing_impl.append(str(spec_path.relative_to(root)))
            rep.bump(category, "specs_without_impl")

    if missing_impl:
        rep.add(
            "warning",
            category,
            f"Specs sem evidencia de implementacao: {len(missing_impl)}",
            details=", ".join(missing_impl[:5]),
            files=missing_impl[:10],
            suggestion="Revisar se a spec esta implementada, renomear termos ou marcar como futura.",
        )


def _extract_adr_decision(adr_text: str) -> str:
    match = re.search(
        r"##\s*(Decision|Decisao|Decisão)\b(.*?)(\n##\s|\Z)",
        adr_text,
        re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return ""
    return match.group(2).strip()


def check_adrs_vs_implementation(root: Path, rep: Reporter, max_adrs: int = 25) -> None:
    category = "adrs_vs_implementation"
    adr_root = root / "docs" / "adr"
    if not adr_root.exists():
        rep.add("warning", category, "Diretorio docs/adr nao encontrado")
        return

    adr_files = sorted(adr_root.glob("ADR-*.md"))
    if not adr_files:
        rep.add("warning", category, "Nenhuma ADR encontrada")
        return

    impl_files = list(
        iter_files(
            root,
            CODE_EXTENSIONS | {".md", ".yml", ".yaml", ".toml", ".json", ".ini", ".cfg"},
        )
    )
    impl_contents = [(p, read_text(p).lower()) for p in impl_files[:500]]

    unmatched: List[str] = []
    for adr_path in adr_files[:max_adrs]:
        text = read_text(adr_path)
        decision = _extract_adr_decision(text)
        if not decision:
            rep.bump(category, "adr_without_decision")
            continue

        terms = normalize_words(decision, max_words=10)
        if not terms:
            rep.bump(category, "adr_without_terms")
            continue

        found = False
        for _, content in impl_contents:
            if any(term in content for term in terms[:4]):
                found = True
                break

        if found:
            rep.bump(category, "adr_with_impl")
        else:
            unmatched.append(str(adr_path.relative_to(root)))
            rep.bump(category, "adr_without_impl")

    if unmatched:
        rep.add(
            "warning",
            category,
            f"ADRs sem evidencia clara na implementacao: {len(unmatched)}",
            details=", ".join(unmatched[:5]),
            files=unmatched[:10],
            suggestion="Validar se a decisao foi aplicada ou atualizar status da ADR.",
        )


def check_agents(root: Path, rep: Reporter, run_commands: bool, timeout: int) -> None:
    category = "agents_vs_reality"
    path = root / "AGENTS.md"
    if not path.exists():
        rep.add("error", category, "AGENTS.md nao encontrado")
        return

    text = read_text(path)
    commands = extract_commands_from_agents(text)
    if not commands:
        rep.add(
            "warning",
            category,
            "Nao foi possivel extrair comandos da secao de comandos do AGENTS.md",
            suggestion="Use formato com bullets + `comando` ou bloco de codigo na secao 2.",
        )
        return

    rep.bump(category, "commands_detected")
    for label, command in commands:
        if run_commands:
            try:
                proc = subprocess.run(
                    command,
                    shell=True,
                    capture_output=True,
                    text=True,
                    cwd=str(root),
                    timeout=timeout,
                )
                if proc.returncode == 0:
                    rep.bump(category, "commands_ok")
                else:
                    rep.add(
                        "warning",
                        category,
                        f"Comando falhou ({label}): {command}",
                        details=f"exit={proc.returncode}",
                    )
                    rep.bump(category, "commands_failed")
            except subprocess.TimeoutExpired:
                rep.add("warning", category, f"Timeout no comando ({label}): {command}")
                rep.bump(category, "commands_timeout")
        else:
            if command_available(command):
                rep.bump(category, "commands_declared")
            else:
                rep.add("warning", category, f"Comando pode estar indisponivel ({label}): {command}")
                rep.bump(category, "commands_unavailable")

    py_match = re.search(r"Python:\s*([^\n]+)", text, re.IGNORECASE)
    if py_match:
        declared = py_match.group(1).strip()
        try:
            current = subprocess.run(
                ["python3", "--version"],
                check=False,
                capture_output=True,
                text=True,
                cwd=str(root),
            )
            current_version = (current.stdout or current.stderr).strip()
            if declared and declared not in current_version:
                rep.add(
                    "info",
                    category,
                    "Versao Python declarada difere do ambiente atual",
                    details=f"declarado={declared} | ambiente={current_version}",
                )
        except OSError:
            rep.add("info", category, "python3 nao encontrado para comparar versao")


def check_project_context(root: Path, rep: Reporter) -> None:
    category = "project_context"
    path = root / "PROJECT_CONTEXT.md"
    if not path.exists():
        rep.add("warning", category, "PROJECT_CONTEXT.md nao encontrado")
        return

    text = read_text(path).lower()
    if len(text) < 250:
        rep.add("warning", category, "PROJECT_CONTEXT.md muito curto para retomada eficaz")

    top_level_code_dirs = []
    for child in root.iterdir():
        if not child.is_dir() or child.name.startswith("."):
            continue
        if any(
            file_path.suffix in CODE_EXTENSIONS
            for file_path in child.rglob("*")
            if file_path.is_file()
        ):
            top_level_code_dirs.append(child.name.lower())

    missing_mentions = [name for name in top_level_code_dirs[:8] if name not in text]
    if missing_mentions:
        rep.add(
            "info",
            category,
            "PROJECT_CONTEXT.md nao menciona alguns componentes de codigo",
            details=", ".join(missing_mentions[:5]),
            suggestion="Atualizar secao de arquitetura de alto nivel.",
        )
    else:
        rep.bump(category, "component_mentions_ok")


def check_markdown_links(root: Path, rep: Reporter) -> None:
    category = "markdown_links"
    broken: List[str] = []
    for md_file in iter_files(root, [".md"]):
        text = read_text(md_file)
        for link in markdown_links(text):
            if link.startswith(("http://", "https://", "mailto:", "#")):
                continue
            clean = link.split("#", 1)[0].strip()
            if not clean:
                continue
            target = (md_file.parent / clean).resolve()
            if not target.exists():
                broken.append(f"{md_file.relative_to(root)} -> {link}")

    if broken:
        rep.add(
            "warning",
            category,
            f"Links markdown quebrados: {len(broken)}",
            details="; ".join(broken[:5]),
            files=broken[:10],
            suggestion="Corrigir paths relativos ou remover links antigos.",
        )
    else:
        rep.bump(category, "links_ok")


# -----------------------------------------------------------------------------
# Report formatting
# -----------------------------------------------------------------------------


def render_text(result: CheckResult, root: Path) -> str:
    errors = [f for f in result.findings if f.level == "error"]
    warnings = [f for f in result.findings if f.level == "warning"]
    infos = [f for f in result.findings if f.level == "info"]

    lines: List[str] = []
    lines.append("=" * 68)
    lines.append("ARTIFACTS CONSISTENCY REPORT")
    lines.append("=" * 68)
    lines.append(f"Projeto: {root.name}")
    lines.append("")
    lines.append("Resumo:")
    lines.append(f"- Errors: {len(errors)}")
    lines.append(f"- Warnings: {len(warnings)}")
    lines.append(f"- Info: {len(infos)}")
    lines.append("")

    for finding in result.findings:
        prefix = {"error": "[ERROR]", "warning": "[WARN]", "info": "[INFO]"}[finding.level]
        lines.append(f"{prefix} {finding.category}: {finding.message}")
        if finding.details:
            lines.append(f"  details: {finding.details}")
        if finding.suggestion:
            lines.append(f"  suggestion: {finding.suggestion}")
        lines.append("")

    lines.append("Counts by check:")
    for category, stats in sorted(result.checks.items()):
        lines.append(f"- {category}: {stats}")
    lines.append("=" * 68)
    return "\n".join(lines)


def render_markdown(result: CheckResult, root: Path) -> str:
    out: List[str] = [
        "# Artifacts Consistency Report",
        "",
        f"**Projeto:** `{root.name}`",
        "",
        "## Findings",
    ]
    if not result.findings:
        out.append("- Nenhum finding.")
    for finding in result.findings:
        out.append(f"- **{finding.level.upper()}** `{finding.category}`: {finding.message}")
        if finding.details:
            out.append(f"  detalhes: {finding.details}")
        if finding.suggestion:
            out.append(f"  sugestao: {finding.suggestion}")

    out.append("")
    out.append("## Check Stats")
    for category, stats in sorted(result.checks.items()):
        out.append(f"- `{category}`: `{stats}`")
    return "\n".join(out) + "\n"


def run_checks(root: Path, run_commands: bool, timeout: int, max_specs: int, max_adrs: int) -> CheckResult:
    rep = Reporter()
    check_required_files(root, rep)
    check_specs_vs_code(root, rep, max_specs=max_specs)
    check_adrs_vs_implementation(root, rep, max_adrs=max_adrs)
    check_agents(root, rep, run_commands=run_commands, timeout=timeout)
    check_project_context(root, rep)
    check_markdown_links(root, rep)
    return CheckResult(checks=rep.counts, findings=rep.findings)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check consistency among project artifacts")
    parser.add_argument("--root", default=".", help="Project root")
    parser.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    parser.add_argument(
        "--run-commands",
        action="store_true",
        help="Execute AGENTS commands (safe mode disabled)",
    )
    parser.add_argument("--timeout", type=int, default=60, help="Timeout (seconds) for each AGENTS command")
    parser.add_argument("--max-specs", type=int, default=25, help="Max spec files to inspect")
    parser.add_argument("--max-adrs", type=int, default=25, help="Max ADR files to inspect")
    args = parser.parse_args()

    root = Path(args.root).resolve()
    result = run_checks(root, args.run_commands, args.timeout, args.max_specs, args.max_adrs)

    if args.format == "json":
        payload = {
            "project": root.name,
            "checks": result.checks,
            "findings": [asdict(item) for item in result.findings],
            "summary": {
                "errors": sum(1 for item in result.findings if item.level == "error"),
                "warnings": sum(1 for item in result.findings if item.level == "warning"),
                "info": sum(1 for item in result.findings if item.level == "info"),
            },
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    elif args.format == "markdown":
        print(render_markdown(result, root), end="")
    else:
        print(render_text(result, root))

    has_error = any(item.level == "error" for item in result.findings)
    return 1 if has_error else 0


if __name__ == "__main__":
    raise SystemExit(main())
