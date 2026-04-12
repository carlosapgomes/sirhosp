#!/usr/bin/env python3
"""
Generate or update AGENTS.md from project signals.

This script is intentionally deterministic and stdlib-only so it runs in
minimal environments used by LLM tooling.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None  # type: ignore[assignment]


SECTION_STACK = "## 1. Stack e Versoes"
SECTION_VALIDATION = "## 2. Comandos de Validacao (Quality Gate)"
SECTION_ESSENTIAL = "## 3. Comandos Essenciais (Operacao Local)"
SECTION_ARCH = "## 4. Arquitetura e Constraints"
SECTION_TESTS = "## 5. Politica de Testes"
SECTION_STOP = "## 6. Stop Rule (CRUCIAL)"
SECTION_DOD = "## 7. Definition of Done (DoD)"
SECTION_ANTI = "## 8. Anti-patterns Proibidos"
SECTION_REENTRY = "## 9. Prompt de Reentrada"


@dataclass
class ProjectInfo:
    root: Path
    languages: List[str]
    framework: Optional[str]
    python_version: Optional[str]
    django_version: Optional[str]
    node_version: Optional[str]
    validation_commands: List[Tuple[str, str]]
    essential_commands: Dict[str, List[str]]
    architecture_constraints: List[str]
    anti_patterns: List[str]


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _load_pyproject(root: Path) -> Dict:
    path = root / "pyproject.toml"
    if not path.exists() or tomllib is None:
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _load_package_json(root: Path) -> Dict:
    path = root / "package.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _extract_from_requirements(root: Path, package_name: str) -> Optional[str]:
    req_files = [
        root / "requirements.txt",
        root / "requirements-dev.txt",
        root / "requirements" / "dev.txt",
    ]
    pattern = re.compile(
        rf"^\s*{re.escape(package_name)}\s*(==|~=|>=|<=|>|<)?\s*([A-Za-z0-9\.\-\+]+)?",
        re.IGNORECASE,
    )
    for req_file in req_files:
        if not req_file.exists():
            continue
        for line in _read_text(req_file).splitlines():
            match = pattern.match(line.strip())
            if match:
                return match.group(2) or "installed"
    return None


def detect_stack(root: Path) -> ProjectInfo:
    languages: List[str] = []
    framework: Optional[str] = None
    pyproject = _load_pyproject(root)
    package_json = _load_package_json(root)

    has_python = any((root / marker).exists() for marker in ["pyproject.toml", "requirements.txt", "manage.py"])
    has_node = (root / "package.json").exists()
    has_go = (root / "go.mod").exists()
    has_java = any((root / marker).exists() for marker in ["pom.xml", "build.gradle"])

    if has_python:
        languages.append("Python")
    if has_node:
        languages.append("JavaScript/TypeScript")
    if has_go:
        languages.append("Go")
    if has_java:
        languages.append("Java")

    django_version = None
    if (root / "manage.py").exists():
        framework = "Django"
        django_version = _extract_django_version(pyproject, root)
    elif has_node:
        deps = {**package_json.get("dependencies", {}), **package_json.get("devDependencies", {})}
        if "next" in deps:
            framework = "Next.js"
        elif "react" in deps:
            framework = "React"
        elif "vue" in deps:
            framework = "Vue"
        elif "express" in deps:
            framework = "Express"

    python_version = _extract_python_version(pyproject, root) if has_python else None
    node_version = _extract_node_version(package_json, root) if has_node else None

    validation_commands = infer_validation_commands(root, has_python, has_node)
    essential_commands = infer_essential_commands(root, has_python, has_node, framework)
    architecture_constraints = infer_architecture_constraints(root, framework, has_python, has_node)
    anti_patterns = infer_anti_patterns(framework, has_python, has_node)

    return ProjectInfo(
        root=root,
        languages=languages or ["Desconhecida"],
        framework=framework,
        python_version=python_version,
        django_version=django_version,
        node_version=node_version,
        validation_commands=validation_commands,
        essential_commands=essential_commands,
        architecture_constraints=architecture_constraints,
        anti_patterns=anti_patterns,
    )


def _extract_python_version(pyproject: Dict, root: Path) -> Optional[str]:
    requires_python = (
        pyproject.get("project", {}).get("requires-python")
        if pyproject
        else None
    )
    if isinstance(requires_python, str) and requires_python.strip():
        return requires_python.strip()

    pyver_file = root / ".python-version"
    if pyver_file.exists():
        version = _read_text(pyver_file).strip()
        if version:
            return version

    try:
        result = subprocess.run(
            ["python3", "--version"],
            check=False,
            capture_output=True,
            text=True,
            cwd=str(root),
        )
        out = (result.stdout or result.stderr).strip()
        match = re.search(r"Python\s+(\d+\.\d+(?:\.\d+)?)", out)
        if match:
            return match.group(1)
    except OSError:
        pass
    return None


def _extract_django_version(pyproject: Dict, root: Path) -> Optional[str]:
    if pyproject:
        project_deps = pyproject.get("project", {}).get("dependencies", [])
        if isinstance(project_deps, list):
            for dep in project_deps:
                if dep.lower().startswith("django"):
                    return dep.split("django", 1)[-1].strip(" =<>!~")
    req_version = _extract_from_requirements(root, "django")
    return req_version


def _extract_node_version(package_json: Dict, root: Path) -> Optional[str]:
    if package_json:
        engines = package_json.get("engines", {})
        if isinstance(engines, dict):
            node = engines.get("node")
            if isinstance(node, str) and node.strip():
                return node.strip()
    nvmrc = root / ".nvmrc"
    if nvmrc.exists():
        value = _read_text(nvmrc).strip()
        if value:
            return value
    return None


def _cmd_exists(name: str) -> bool:
    return any(
        (Path(path) / name).exists()
        for path in os.getenv("PATH", "").split(os.pathsep)
        if path
    )


def infer_validation_commands(root: Path, has_python: bool, has_node: bool) -> List[Tuple[str, str]]:
    commands: List[Tuple[str, str]] = []

    if (root / "scripts" / "markdown-format.sh").exists():
        commands.append(("Markdown (autofix)", "./scripts/markdown-format.sh"))
    if (root / "scripts" / "markdown-lint.sh").exists():
        commands.append(("Markdown (lint)", "./scripts/markdown-lint.sh"))

    if has_python:
        if any((root / file_name).exists() for file_name in ["pytest.ini", "pyproject.toml", "tox.ini"]):
            commands.append(("Testes", "python3 -m pytest -q"))
        elif (root / "manage.py").exists():
            commands.append(("Testes", "python3 manage.py test"))

        if _cmd_exists("ruff") or "ruff" in _read_text(root / "pyproject.toml").lower():
            commands.append(("Lint", "ruff check ."))
        if _cmd_exists("mypy") or "mypy" in _read_text(root / "pyproject.toml").lower():
            commands.append(("Type check", "mypy ."))
        if (root / "manage.py").exists():
            commands.append(("Build", "python3 manage.py check"))
            commands.append(("Migracoes", "python3 manage.py makemigrations --check --dry-run"))
        elif (root / "pyproject.toml").exists():
            commands.append(("Build", "python3 -m build"))

    if has_node:
        pkg = _load_package_json(root)
        scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
        if isinstance(scripts, dict):
            if "test" in scripts:
                commands.append(("Testes JS", "npm test"))
            if "lint" in scripts:
                commands.append(("Lint JS", "npm run lint"))
            if "type-check" in scripts:
                commands.append(("Type check JS", "npm run type-check"))
            if "build" in scripts:
                commands.append(("Build JS", "npm run build"))
    if not commands:
        commands.append(("Verificacao basica", "git status --short"))
    return commands


def infer_essential_commands(
    root: Path, has_python: bool, has_node: bool, framework: Optional[str]
) -> Dict[str, List[str]]:
    essentials: Dict[str, List[str]] = {}

    if has_python:
        setup = [
            "python3 -m venv .venv",
            "source .venv/bin/activate",
        ]
        if (root / "requirements.txt").exists():
            setup.append("pip install -r requirements.txt")
        elif (root / "requirements" / "dev.txt").exists():
            setup.append("pip install -r requirements/dev.txt")
        elif (root / "pyproject.toml").exists():
            setup.append("python3 -m pip install -e .")
        essentials["Setup"] = setup

        if framework == "Django" or (root / "manage.py").exists():
            essentials["Rodar local"] = ["python3 manage.py runserver"]
            essentials["Migracoes"] = [
                "python3 manage.py makemigrations --check",
                "python3 manage.py migrate --plan",
            ]
        else:
            essentials["Rodar local"] = ["python3 -m <seu_modulo_principal>"]

        if any((root / item).exists() for item in ["pytest.ini", "pyproject.toml", "tox.ini"]):
            essentials["Testes rapidos"] = ["python3 -m pytest -q tests/unit"]
            essentials["Testes completos"] = ["python3 -m pytest -q"]
        elif (root / "manage.py").exists():
            essentials["Testes completos"] = ["python3 manage.py test"]

    if has_node:
        essentials.setdefault("Setup", []).extend(["npm install"])
        pkg = _load_package_json(root)
        scripts = pkg.get("scripts", {}) if isinstance(pkg, dict) else {}
        if isinstance(scripts, dict):
            if "dev" in scripts:
                essentials["Rodar local JS"] = ["npm run dev"]
            if "test" in scripts:
                essentials["Testes JS"] = ["npm test"]

    if (root / "scripts" / "markdown-format.sh").exists() or (root / "scripts" / "markdown-lint.sh").exists():
        doc_cmds: List[str] = []
        if (root / "scripts" / "markdown-format.sh").exists():
            doc_cmds.append("./scripts/markdown-format.sh")
        if (root / "scripts" / "markdown-lint.sh").exists():
            doc_cmds.append("./scripts/markdown-lint.sh")
        essentials["Documentacao"] = doc_cmds

    if (root / ".githooks" / "pre-commit").exists():
        essentials["Hooks"] = ["git config core.hooksPath .githooks"]

    if not essentials:
        essentials["Operacao basica"] = ["git status --short", "git branch --show-current"]
    return essentials


def infer_architecture_constraints(
    root: Path, framework: Optional[str], has_python: bool, has_node: bool
) -> List[str]:
    constraints: List[str] = []
    if framework == "Django":
        constraints.extend(
            [
                "Direcao: templates -> views -> services -> models.",
                "Views devem ser finas; regras de negocio em services/domain.",
                "Models focados em dados e invariantes simples.",
            ]
        )
    elif framework in {"React", "Next.js", "Vue"}:
        constraints.extend(
            [
                "Componentes sem logica de dominio pesada.",
                "Fluxo: UI -> hooks/actions -> servicos -> API.",
                "Separar estado de apresentacao de estado de dominio.",
            ]
        )

    if has_python and not constraints:
        constraints.append("Organizar logica por modulo/cohesao; evitar funcoes gigantes.")
    if has_node and framework == "Express":
        constraints.append("Rotas finas, servicos testaveis, acesso a dados isolado.")

    if not constraints:
        constraints.append("Definir boundaries explicitos por modulo e manter dependencias unidirecionais.")
    return constraints


def infer_anti_patterns(framework: Optional[str], has_python: bool, has_node: bool) -> List[str]:
    anti = [
        "Nao criar classes/funcoes God object com responsabilidades demais.",
        "Nao deixar TODO/FIXME sem issue ou plano.",
        "Nao acoplar regras de negocio em camada de apresentacao.",
    ]
    if framework == "Django":
        anti.append("Nao colocar regra de negocio extensa em views.py ou serializers.")
    if has_node:
        anti.append("Nao misturar acesso HTTP, regra de negocio e SQL no mesmo arquivo.")
    if has_python:
        anti.append("Nao introduzir side effects globais invisiveis em import-time.")
    return anti


def render_agents_markdown(info: ProjectInfo) -> str:
    stack_lines: List[str] = []
    stack_lines.append(f"- Linguagens: {', '.join(info.languages)}")
    if info.framework:
        stack_lines.append(f"- Framework principal: {info.framework}")
    if info.python_version:
        stack_lines.append(f"- Python: {info.python_version}")
    if info.django_version:
        stack_lines.append(f"- Django: {info.django_version}")
    if info.node_version:
        stack_lines.append(f"- Node.js: {info.node_version}")

    validation_lines = [f"- {label}: `{cmd}`" for label, cmd in info.validation_commands]
    arch_lines = [f"- {item}" for item in info.architecture_constraints]
    anti_lines = [f"- {item}" for item in info.anti_patterns]
    has_markdown_lint = (info.root / "scripts" / "markdown-lint.sh").exists()
    dod_lines = [
        "- [ ] Build/check sem erros",
        "- [ ] Testes relevantes passando",
    ]
    if has_markdown_lint:
        dod_lines.append("- [ ] Markdown lint sem erros (`./scripts/markdown-lint.sh`)")
    dod_lines.extend(
        [
            "- [ ] Lint/type-check sem erros relevantes",
            "- [ ] Specs/docs atualizadas quando necessario",
            "- [ ] Commit com mensagem clara e rastreavel",
        ]
    )
    essential_sections: List[str] = []
    for block_title, commands in info.essential_commands.items():
        essential_sections.append(f"### {block_title}")
        essential_sections.append("```bash")
        essential_sections.extend(commands)
        essential_sections.append("```")
        essential_sections.append("")

    doc = [
        "# AGENTS.md",
        "",
        SECTION_STACK,
        *stack_lines,
        "",
        SECTION_VALIDATION,
        *validation_lines,
        "",
        SECTION_ESSENTIAL,
        *essential_sections,
        "",
        SECTION_ARCH,
        *arch_lines,
        "",
        SECTION_TESTS,
        "- TDD para novas funcionalidades e bugfixes criticos.",
        "- Priorizar testes unitarios; usar integracao para contratos e fluxos.",
        "- Ao tocar legado sem testes, adicionar ao menos um teste de caracterizacao.",
        "",
        SECTION_STOP,
        "- Implementar uma task slice por vez.",
        "- Rodar comandos de validacao da secao 2.",
        "- Atualizar tasks/specs e parar para confirmacao do proximo slice.",
        "",
        SECTION_DOD,
        *dod_lines,
        "",
        SECTION_ANTI,
        *anti_lines,
        "",
        SECTION_REENTRY,
        "```text",
        "Read AGENTS.md and PROJECT_CONTEXT.md first.",
        "Implement ONLY the next incomplete slice from tasks/spec.",
        "Run section 2 validation commands, update artifacts, then STOP and ask confirmation.",
        "```",
        "",
        "<!-- generated-by: agents-md-generator -->",
    ]
    return "\n".join(doc).strip() + "\n"


def build_agents(root: Path) -> str:
    info = detect_stack(root)
    return render_agents_markdown(info)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate or update AGENTS.md")
    parser.add_argument("--project-root", default=".", help="Project root path")
    parser.add_argument("--output", default="AGENTS.md", help="Output file path")
    parser.add_argument(
        "--check",
        action="store_true",
        help="Do not write; return 0 if up-to-date else 2",
    )
    parser.add_argument("--stdout", action="store_true", help="Print generated markdown")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    output = (root / args.output).resolve()
    info = detect_stack(root)

    if args.format == "json":
        payload = {
            "languages": info.languages,
            "framework": info.framework,
            "python_version": info.python_version,
            "django_version": info.django_version,
            "node_version": info.node_version,
            "validation_commands": info.validation_commands,
            "essential_commands": info.essential_commands,
            "architecture_constraints": info.architecture_constraints,
            "anti_patterns": info.anti_patterns,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    rendered = render_agents_markdown(info)
    current = _read_text(output) if output.exists() else ""

    if args.check:
        return 0 if current == rendered else 2

    if args.stdout:
        print(rendered, end="")
        return 0

    output.write_text(rendered, encoding="utf-8")
    print(f"[agents-md-generator] wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
