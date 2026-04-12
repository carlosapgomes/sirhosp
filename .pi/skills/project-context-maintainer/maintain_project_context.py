#!/usr/bin/env python3
"""
Generate or update PROJECT_CONTEXT.md from repository signals.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class Component:
    name: str
    description: str
    location: str


@dataclass
class ContextModel:
    purpose: str
    objective: str
    authoritative_sources: List[str]
    components: List[Component]
    non_negotiable_rules: List[str]
    quality_bar: List[str]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _extract_readme_summary(root: Path) -> Optional[str]:
    for name in ("README.md", "Readme.md", "readme.md"):
        candidate = root / name
        if candidate.exists():
            text = _read_text(candidate)
            if not text.strip():
                continue
            lines = [line.strip() for line in text.splitlines()]
            paragraphs = []
            current: List[str] = []
            for line in lines:
                if line.startswith("#"):
                    continue
                if not line:
                    if current:
                        paragraphs.append(" ".join(current).strip())
                        current = []
                    continue
                current.append(line)
            if current:
                paragraphs.append(" ".join(current).strip())
            for p in paragraphs:
                if len(p) >= 25:
                    return p
    return None


def _discover_authoritative_sources(root: Path) -> List[str]:
    candidates = [
        "AGENTS.md",
        "README.md",
        "openspec/specs/",
        "docs/adr/",
        "docs/releases/",
        "prompts/handoff.md",
    ]
    found = [path for path in candidates if (root / path).exists()]
    if not found:
        found = ["README.md", "codigo-fonte em ./"]
    return found


def _count_code_files(path: Path) -> int:
    exts = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".java"}
    count = 0
    for file_path in path.rglob("*"):
        if file_path.is_file() and file_path.suffix in exts:
            count += 1
    return count


def _component_description(name: str) -> str:
    key = name.lower()
    defaults = {
        "apps": "Modulos de dominio/aplicacao",
        "app": "Aplicacao principal",
        "backend": "Servicos de backend",
        "frontend": "Interface web",
        "api": "Contratos e endpoints de integracao",
        "services": "Orquestracao de regras de negocio",
        "domain": "Regra de negocio pura",
        "docs": "Documentacao e rastreabilidade",
        "tests": "Suite de testes automatizados",
        "scripts": "Automacoes e utilitarios",
    }
    return defaults.get(key, "Componente identificado no repositorio")


def _discover_components(root: Path, max_components: int = 8) -> List[Component]:
    components: List[Component] = []
    for child in sorted(root.iterdir()):
        if not child.is_dir():
            continue
        if child.name.startswith(".") or child.name in {"venv", ".venv", "__pycache__"}:
            continue
        count = _count_code_files(child)
        if count == 0 and child.name not in {"docs", "tests", "scripts"}:
            continue
        components.append(
            Component(
                name=child.name,
                description=_component_description(child.name),
                location=str(child.relative_to(root)),
            )
        )
        if len(components) >= max_components:
            break
    if not components:
        components.append(Component(name="root", description="Estrutura principal do projeto", location="."))
    return components


def _detect_rules(root: Path) -> List[str]:
    rules: List[str] = []
    joined = "\n".join(
        _read_text(path)
        for path in [root / "AGENTS.md", root / "README.md", root / "PROJECT_CONTEXT.md"]
        if path.exists()
    ).lower()
    if "lgpd" in joined or "gdpr" in joined:
        rules.append("Conformidade com LGPD/GDPR para dados pessoais.")
    if "sso" in joined:
        rules.append("Manter compatibilidade com fluxo de autenticacao SSO.")
    if "auditoria" in joined or "audit" in joined:
        rules.append("Garantir rastreabilidade para auditoria (artefatos e logs).")

    rules.extend(
        [
            "Nao quebrar contratos publicos de API sem mudanca versionada.",
            "Toda mudanca relevante deve deixar evidencia no Git (spec/task/commit).",
        ]
    )
    deduped: List[str] = []
    for rule in rules:
        if rule not in deduped:
            deduped.append(rule)
    return deduped


def _quality_bar(root: Path) -> List[str]:
    quality = [
        "Testes relevantes executam localmente antes de merge.",
        "Lint e checks estaticos sem erros criticos.",
        "Mudancas com risco medio/alto devem ter plano de rollback.",
    ]
    if (root / "manage.py").exists():
        quality.append("Verificacao Django (`python3 manage.py check`) sem erro.")
    if (root / "pyproject.toml").exists():
        quality.append("Build de pacote/app deve permanecer reprodutivel.")
    return quality


def build_context_model(root: Path) -> ContextModel:
    summary = _extract_readme_summary(root)
    objective = summary or "Definir objetivo de negocio e comportamento principal do sistema."
    purpose = (
        "Resumo executivo para retomada rapida apos pausas e para onboarding de novos contribuidores."
    )
    sources = _discover_authoritative_sources(root)
    components = _discover_components(root)
    rules = _detect_rules(root)
    quality = _quality_bar(root)
    return ContextModel(
        purpose=purpose,
        objective=objective,
        authoritative_sources=sources,
        components=components,
        non_negotiable_rules=rules,
        quality_bar=quality,
    )


def render_context_markdown(model: ContextModel) -> str:
    lines: List[str] = []
    lines.append("# PROJECT_CONTEXT.md")
    lines.append("")
    lines.append("## Proposito")
    lines.append(model.purpose)
    lines.append("")
    lines.append("## Fontes Autoritativas")
    for source in model.authoritative_sources:
        lines.append(f"- `{source}`")
    lines.append("- Em caso de conflito: specs/artefatos mais recentes no Git prevalecem.")
    lines.append("")
    lines.append("## Objetivo do Sistema")
    lines.append(model.objective)
    lines.append("")
    lines.append("## Arquitetura de Alto Nivel")
    for component in model.components:
        lines.append(f"- **{component.name}** ({component.location}): {component.description}.")
    lines.append("")
    lines.append("## Regras Nao Negociaveis")
    for rule in model.non_negotiable_rules:
        lines.append(f"- {rule}")
    lines.append("")
    lines.append("## Quality Bar")
    for item in model.quality_bar:
        lines.append(f"- {item}")
    lines.append("")
    lines.append("<!-- generated-by: project-context-maintainer -->")
    return "\n".join(lines).strip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or update PROJECT_CONTEXT.md")
    parser.add_argument("--project-root", default=".", help="Project root path")
    parser.add_argument("--output", default="PROJECT_CONTEXT.md", help="Output file path")
    parser.add_argument("--stdout", action="store_true", help="Print generated markdown")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; return 0 if up-to-date else 2",
    )
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    output = (root / args.output).resolve()
    model = build_context_model(root)

    if args.format == "json":
        payload: Dict[str, object] = {
            "purpose": model.purpose,
            "objective": model.objective,
            "authoritative_sources": model.authoritative_sources,
            "components": [component.__dict__ for component in model.components],
            "non_negotiable_rules": model.non_negotiable_rules,
            "quality_bar": model.quality_bar,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    rendered = render_context_markdown(model)
    current = _read_text(output) if output.exists() else ""
    if args.check:
        return 0 if rendered == current else 2
    if args.stdout:
        print(rendered, end="")
        return 0
    output.write_text(rendered, encoding="utf-8")
    print(f"[project-context-maintainer] wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
