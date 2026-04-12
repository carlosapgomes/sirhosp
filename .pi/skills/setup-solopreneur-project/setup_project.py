#!/usr/bin/env python3
"""
Bootstrap a project to DevLoop SOP structure.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple


REQUIRED_DIRS = [
    "docs/adr",
    "docs/releases",
    "tests/unit",
    "tests/integration",
    "tests/e2e",
    "scripts",
    "prompts",
    ".codex/skills",
    ".githooks",
]

OPTIONAL_OPENSPEC_DIRS = [
    "openspec/specs",
    "openspec/changes/archive",
]

REQUIRED_FILES = [
    "AGENTS.md",
    "PROJECT_CONTEXT.md",
    "README.md",
    "docs/adr/README.md",
    "docs/adr/template.md",
    "scripts/markdown-format.sh",
    "scripts/markdown-lint.sh",
    ".githooks/pre-commit",
    ".markdownlintignore",
]

GITIGNORE_LINES = [
    "prompts/",
    ".env",
    "*.secret",
    "openspec/changes/*/",
    "!openspec/changes/archive/",
]


@dataclass
class Operation:
    kind: str
    path: str
    status: str
    message: str


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def _agents_fallback() -> str:
    return (
        "# AGENTS.md\n\n"
        "## 1. Stack e Versoes\n"
        "- Python: 3.12.x\n"
        "- Framework: Django/Flask/FastAPI/Outro\n"
        "- Banco: PostgreSQL/MySQL/SQLite\n\n"
        "## 2. Comandos de Validacao (Quality Gate)\n"
        "- Markdown (autofix): `./scripts/markdown-format.sh`\n"
        "- Markdown (lint): `./scripts/markdown-lint.sh`\n"
        "- Testes: `python3 -m pytest -q`\n"
        "- Lint: `ruff check .`\n"
        "- Type check: `mypy .` (se aplicavel)\n"
        "- Build/Check: `python3 manage.py check` (ou equivalente)\n"
        "- Migracoes (check): `python3 manage.py makemigrations --check --dry-run` (se aplicavel)\n\n"
        "## 3. Comandos Essenciais (Operacao Local)\n"
        "### Setup\n"
        "```bash\n"
        "python3 -m venv .venv\n"
        "source .venv/bin/activate\n"
        "pip install -r requirements/dev.txt\n"
        "```\n\n"
        "### Rodar local\n"
        "```bash\n"
        "python3 manage.py runserver\n"
        "```\n\n"
        "### Testes rapidos\n"
        "```bash\n"
        "python3 -m pytest -q tests/unit\n"
        "```\n\n"
        "### Migracoes\n"
        "```bash\n"
        "python3 manage.py migrate --plan\n"
        "```\n\n"
        "### Hooks\n"
        "```bash\n"
        "git config core.hooksPath .githooks\n"
        "```\n\n"
        "## 4. Arquitetura e Constraints\n"
        "- Definir boundaries por modulo.\n"
        "- Nao colocar logica de negocio em camada de apresentacao.\n\n"
        "## 5. Politica de Testes\n"
        "- TDD para novas funcionalidades quando viavel.\n"
        "- Cobrir cenarios criticos e edge cases.\n\n"
        "## 6. Stop Rule (CRUCIAL)\n"
        "- Implementar um slice por vez.\n"
        "- Rodar comandos da secao 2.\n"
        "- Atualizar tasks/specs e parar para confirmacao.\n\n"
        "## 7. Definition of Done (DoD)\n"
        "- [ ] Build/check sem erro\n"
        "- [ ] Testes relevantes passando\n"
        "- [ ] Markdown lint sem erros (`./scripts/markdown-lint.sh`)\n"
        "- [ ] Lint/type-check OK\n"
        "- [ ] Tasks/specs/docs atualizadas\n"
        "- [ ] Commit com mensagem clara\n\n"
        "## 8. Anti-patterns Proibidos\n"
        "- Nao criar God classes/services.\n"
        "- Nao ignorar logs/telemetria em operacoes criticas.\n\n"
        "## 9. Prompt de Reentrada\n"
        "```text\n"
        "Read AGENTS.md and PROJECT_CONTEXT.md first.\n"
        "Implement ONLY the next incomplete slice from tasks/spec.\n"
        "Run section 2 validation commands, update artifacts, then STOP and ask confirmation.\n"
        "```\n"
    )


def _context_fallback() -> str:
    return (
        "# PROJECT_CONTEXT.md\n\n"
        "## Proposito\n"
        "Resumo executivo para retomada rapida apos pausas e onboarding.\n\n"
        "## Fontes Autoritativas\n"
        "- `AGENTS.md`\n"
        "- `openspec/specs/` (quando existir)\n"
        "- `docs/adr/`\n"
        "- Em conflito: artefato mais recente versionado no Git\n\n"
        "## Objetivo do Sistema\n"
        "Descrever em 1-2 paragrafos o problema resolvido e o valor entregue.\n\n"
        "## Arquitetura de Alto Nivel\n"
        "- Componente principal de backend\n"
        "- Componente de frontend/UI\n"
        "- Integrações externas e fluxos principais\n\n"
        "## Regras Nao Negociaveis\n"
        "- Nao quebrar contratos publicos de API sem versionamento.\n"
        "- Toda mudanca relevante deve deixar evidencia no Git.\n\n"
        "## Quality Bar\n"
        "- Testes relevantes executam localmente antes de merge.\n"
        "- Lint e checks estaticos sem erros criticos.\n"
        "- Mudancas de risco medio/alto devem ter plano de rollback.\n"
    )


def _readme_fallback(project_name: str) -> str:
    return (
        f"# {project_name}\n\n"
        "Breve descricao do projeto.\n\n"
        "## Workflow Kit SOP\n"
        "Este repositorio usa AGENTS.md + PROJECT_CONTEXT.md + artefatos de especificacao.\n\n"
        "## Artefatos principais\n"
        "- `AGENTS.md`\n"
        "- `PROJECT_CONTEXT.md`\n"
        "- `docs/adr/`\n"
        "- `docs/releases/`\n"
        "- `tests/`\n"
    )


def _adr_readme_fallback() -> str:
    return (
        "# Architecture Decision Records\n\n"
        "Registros de decisoes arquiteturais importantes.\n\n"
        "## Como criar nova ADR\n"
        "1. Copiar `template.md`\n"
        "2. Nomear com prefixo `ADR-XXXX-...`\n"
        "3. Atualizar este indice\n"
    )


def _adr_template_fallback() -> str:
    return (
        "# ADR-XXXX: <Titulo>\n\n"
        "## Status\n"
        "[Proposed | Accepted | Deprecated | Superseded]\n\n"
        "## Contexto\n"
        "[Situacao e motivacao]\n\n"
        "## Decisao\n"
        "[O que foi decidido]\n\n"
        "## Alternativas Consideradas\n"
        "1. [Alternativa 1]\n"
        "2. [Alternativa 2]\n\n"
        "## Consequencias\n"
        "- Positivas:\n"
        "- Negativas/Trade-offs:\n"
    )


def _markdown_format_script_fallback() -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        "REPO_ROOT=\"$(cd \"$(dirname \"$0\")/..\" && pwd)\"\n"
        "cd \"$REPO_ROOT\"\n\n"
        "if ! command -v npx >/dev/null 2>&1; then\n"
        "  echo \"Erro: npx nao encontrado. Instale Node.js/npm para formatar markdown.\" >&2\n"
        "  exit 1\n"
        "fi\n\n"
        "mapfile -d '' files < <(find . -type f -name '*.md' \\\n"
        "  -not -path './node_modules/*' \\\n"
        "  -not -path './.pi/*' \\\n"
        "  -not -path './.codex/*' \\\n"
        "  -not -path './.git/*' \\\n"
        "  -print0)\n\n"
        "if [ ${#files[@]} -eq 0 ]; then\n"
        "  echo \"Nenhum arquivo .md encontrado.\"\n"
        "  exit 0\n"
        "fi\n\n"
        "npx --yes prettier --write \"${files[@]}\"\n"
        "npx --yes markdownlint-cli --fix \"${files[@]}\"\n"
        "npx --yes markdownlint-cli \"${files[@]}\"\n\n"
        "echo \"Markdown formatado e validado com sucesso.\"\n"
    )


def _markdown_lint_script_fallback() -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        "REPO_ROOT=\"$(cd \"$(dirname \"$0\")/..\" && pwd)\"\n"
        "cd \"$REPO_ROOT\"\n\n"
        "if ! command -v npx >/dev/null 2>&1; then\n"
        "  echo \"Erro: npx nao encontrado. Instale Node.js/npm para validar markdown.\" >&2\n"
        "  exit 1\n"
        "fi\n\n"
        "mapfile -d '' files < <(find . -type f -name '*.md' \\\n"
        "  -not -path './node_modules/*' \\\n"
        "  -not -path './.pi/*' \\\n"
        "  -not -path './.codex/*' \\\n"
        "  -not -path './.git/*' \\\n"
        "  -print0)\n\n"
        "if [ ${#files[@]} -eq 0 ]; then\n"
        "  echo \"Nenhum arquivo .md encontrado.\"\n"
        "  exit 0\n"
        "fi\n\n"
        "npx --yes markdownlint-cli \"${files[@]}\"\n\n"
        "echo \"Markdown lint OK.\"\n"
    )


def _pre_commit_hook_fallback() -> str:
    return (
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n\n"
        "REPO_ROOT=\"$(git rev-parse --show-toplevel)\"\n"
        "cd \"$REPO_ROOT\"\n\n"
        "if ! command -v npx >/dev/null 2>&1; then\n"
        "  echo \"Erro: npx nao encontrado. Instale Node.js/npm para rodar markdown lint no pre-commit.\" >&2\n"
        "  exit 1\n"
        "fi\n\n"
        "mapfile -t staged_md < <(\n"
        "  git diff --cached --name-only --diff-filter=ACMR \\\n"
        "    | grep -E '\\\\.md$' \\\n"
        "    | grep -vE '^(\\\\.pi/|\\\\.codex/)' \\\n"
        "    || true\n"
        ")\n\n"
        "if [ ${#staged_md[@]} -eq 0 ]; then\n"
        "  exit 0\n"
        "fi\n\n"
        "echo \"[pre-commit] Formatando e validando markdown staged...\"\n"
        "npx --yes prettier --write \"${staged_md[@]}\"\n"
        "npx --yes markdownlint-cli --fix \"${staged_md[@]}\"\n"
        "npx --yes markdownlint-cli \"${staged_md[@]}\"\n"
        "git add \"${staged_md[@]}\"\n\n"
        "echo \"[pre-commit] Markdown OK.\"\n"
    )


def _markdownlintignore_fallback() -> str:
    return (
        ".pi/**\n"
        ".codex/**\n"
        "node_modules/**\n"
        ".git/**\n"
    )


def _run_generator(script_path: Path, root: Path, output: str) -> bool:
    if not script_path.exists():
        return False
    proc = subprocess.run(
        [sys.executable, str(script_path), "--project-root", str(root), "--output", output],
        check=False,
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def ensure_dir(path: Path, dry_run: bool, ops: List[Operation]) -> None:
    if path.exists():
        ops.append(Operation("dir", str(path), "exists", "already present"))
        return
    if dry_run:
        ops.append(Operation("dir", str(path), "planned", "would create"))
        return
    path.mkdir(parents=True, exist_ok=True)
    ops.append(Operation("dir", str(path), "created", "created"))


def ensure_file(path: Path, content: str, force: bool, dry_run: bool, ops: List[Operation]) -> None:
    if path.exists() and not force:
        ops.append(Operation("file", str(path), "exists", "kept existing"))
        return
    if dry_run:
        ops.append(Operation("file", str(path), "planned", "would write"))
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    status = "updated" if path.exists() and force else "created"
    ops.append(Operation("file", str(path), status, "written"))


def ensure_executable(path: Path, dry_run: bool, ops: List[Operation]) -> None:
    if not path.exists():
        return
    current_mode = path.stat().st_mode
    desired_mode = current_mode | 0o111
    if current_mode == desired_mode:
        ops.append(Operation("chmod", str(path), "exists", "already executable"))
        return
    if dry_run:
        ops.append(Operation("chmod", str(path), "planned", "would add executable bit"))
        return
    path.chmod(desired_mode)
    ops.append(Operation("chmod", str(path), "updated", "executable bit added"))


def configure_git_hooks(root: Path, dry_run: bool, ops: List[Operation]) -> None:
    if not (root / ".git").exists():
        ops.append(Operation("git", str(root), "skipped", "not a git repository"))
        return
    if dry_run:
        ops.append(Operation("git", str(root), "planned", "would set core.hooksPath=.githooks"))
        return

    proc = subprocess.run(
        ["git", "-C", str(root), "config", "core.hooksPath", ".githooks"],
        check=False,
        capture_output=True,
        text=True,
    )
    if proc.returncode == 0:
        ops.append(Operation("git", str(root), "updated", "configured core.hooksPath=.githooks"))
        return

    error_msg = (proc.stderr or proc.stdout or "unknown error").strip()
    ops.append(Operation("git", str(root), "warning", f"failed to configure hooks: {error_msg}"))


def ensure_gitignore(root: Path, dry_run: bool, ops: List[Operation]) -> None:
    path = root / ".gitignore"
    current = _read_text(path).splitlines()
    missing = [line for line in GITIGNORE_LINES if line not in current]
    if not missing:
        ops.append(Operation("file", str(path), "exists", "gitignore already contains required rules"))
        return
    if dry_run:
        ops.append(Operation("file", str(path), "planned", f"would append {len(missing)} rule(s)"))
        return
    prefix = "\n" if path.exists() and _read_text(path) and not _read_text(path).endswith("\n") else ""
    addition = (
        prefix
        + "\n# dev-loop bootstrap rules\n"
        + "\n".join(missing)
        + "\n"
    )
    with path.open("a", encoding="utf-8") as f:
        f.write(addition)
    ops.append(Operation("file", str(path), "updated", f"appended {len(missing)} rule(s)"))


def check_setup(root: Path) -> Tuple[bool, List[str]]:
    missing: List[str] = []
    for rel in REQUIRED_DIRS:
        if not (root / rel).exists():
            missing.append(rel)
    for rel in REQUIRED_FILES:
        if not (root / rel).exists():
            missing.append(rel)

    gitignore = _read_text(root / ".gitignore")
    for line in GITIGNORE_LINES:
        if line not in gitignore:
            missing.append(f".gitignore::{line}")
    return (len(missing) == 0, missing)


def run_setup(root: Path, include_openspec: bool, force: bool, dry_run: bool) -> List[Operation]:
    ops: List[Operation] = []

    for rel in REQUIRED_DIRS:
        ensure_dir(root / rel, dry_run=dry_run, ops=ops)
    if include_openspec:
        for rel in OPTIONAL_OPENSPEC_DIRS:
            ensure_dir(root / rel, dry_run=dry_run, ops=ops)

    # Try generators first.
    skills_root = Path(__file__).resolve().parents[1]
    agents_gen = skills_root / "agents-md-generator" / "generate_agents_md.py"
    context_gen = skills_root / "project-context-maintainer" / "maintain_project_context.py"

    if not dry_run:
        generated_agents = _run_generator(agents_gen, root, "AGENTS.md")
        generated_context = _run_generator(context_gen, root, "PROJECT_CONTEXT.md")
    else:
        generated_agents = False
        generated_context = False

    if generated_agents:
        ops.append(Operation("file", str(root / "AGENTS.md"), "created", "generated via agents-md-generator"))
    else:
        ensure_file(root / "AGENTS.md", _agents_fallback(), force=force, dry_run=dry_run, ops=ops)

    if generated_context:
        ops.append(Operation("file", str(root / "PROJECT_CONTEXT.md"), "created", "generated via project-context-maintainer"))
    else:
        ensure_file(root / "PROJECT_CONTEXT.md", _context_fallback(), force=force, dry_run=dry_run, ops=ops)

    ensure_file(
        root / "README.md",
        _readme_fallback(root.name),
        force=False,
        dry_run=dry_run,
        ops=ops,
    )
    ensure_file(
        root / "docs/adr/README.md",
        _adr_readme_fallback(),
        force=False,
        dry_run=dry_run,
        ops=ops,
    )
    ensure_file(
        root / "docs/adr/template.md",
        _adr_template_fallback(),
        force=False,
        dry_run=dry_run,
        ops=ops,
    )
    ensure_file(
        root / "docs/releases/README.md",
        "# Releases\n\nArmazene evidencias de release em `YYYY-MM-DD_vX.Y.Z.md`.\n",
        force=False,
        dry_run=dry_run,
        ops=ops,
    )
    ensure_file(
        root / "scripts/markdown-format.sh",
        _markdown_format_script_fallback(),
        force=False,
        dry_run=dry_run,
        ops=ops,
    )
    ensure_file(
        root / "scripts/markdown-lint.sh",
        _markdown_lint_script_fallback(),
        force=False,
        dry_run=dry_run,
        ops=ops,
    )
    ensure_file(
        root / ".githooks/pre-commit",
        _pre_commit_hook_fallback(),
        force=False,
        dry_run=dry_run,
        ops=ops,
    )
    ensure_file(
        root / ".markdownlintignore",
        _markdownlintignore_fallback(),
        force=False,
        dry_run=dry_run,
        ops=ops,
    )

    ensure_executable(root / "scripts/markdown-format.sh", dry_run=dry_run, ops=ops)
    ensure_executable(root / "scripts/markdown-lint.sh", dry_run=dry_run, ops=ops)
    ensure_executable(root / ".githooks/pre-commit", dry_run=dry_run, ops=ops)

    configure_git_hooks(root, dry_run=dry_run, ops=ops)
    ensure_gitignore(root, dry_run=dry_run, ops=ops)
    return ops


def render_text(ops: Sequence[Operation], ok: bool, missing: Sequence[str]) -> str:
    lines: List[str] = []
    lines.append("=" * 68)
    lines.append("SETUP SOLOPRENEUR PROJECT")
    lines.append("=" * 68)
    for op in ops:
        lines.append(f"[{op.status.upper()}] {op.kind}: {op.path} - {op.message}")
    if missing:
        lines.append("")
        lines.append("Missing items:")
        for item in missing:
            lines.append(f"- {item}")
    lines.append("")
    lines.append(f"Status: {'OK' if ok else 'INCOMPLETE'}")
    lines.append("=" * 68)
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Bootstrap DevLoop SOP project structure")
    parser.add_argument("--project-root", default=".", help="Project root")
    parser.add_argument("--dry-run", action="store_true", help="Plan actions without writing")
    parser.add_argument("--check", action="store_true", help="Check if expected structure exists")
    parser.add_argument("--force", action="store_true", help="Overwrite generated files when possible")
    parser.add_argument("--include-openspec", action="store_true", help="Create openspec base directories")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    root = Path(args.project_root).resolve()
    root.mkdir(parents=True, exist_ok=True)

    if args.check:
        ok, missing = check_setup(root)
        payload = {"ok": ok, "missing": missing}
        if args.format == "json":
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(render_text([], ok, missing))
        return 0 if ok else 2

    ops = run_setup(
        root=root,
        include_openspec=args.include_openspec,
        force=args.force,
        dry_run=args.dry_run,
    )
    ok, missing = check_setup(root) if not args.dry_run else (True, [])

    if args.format == "json":
        payload = {
            "operations": [asdict(op) for op in ops],
            "ok": ok,
            "missing": missing,
            "dry_run": args.dry_run,
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(render_text(ops, ok, missing))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
