#!/usr/bin/env bash
# =============================================================================
# SIRHOSP - Markdown autofix
#
# Usage:
#   ./scripts/markdown-format.sh              # todos os .md do repo (CUIDADO:
#                                             # pode reformatar arquivos nao
#                                             # relacionados ao seu trabalho)
#   ./scripts/markdown-format.sh --changed    # apenas .md alterados vs HEAD
#                                             # (staged + unstaged + untracked)
#   ./scripts/markdown-format.sh arquivo.md [mais.md ...]
#                                             # apenas os .md listados
# =============================================================================
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v npx >/dev/null 2>&1; then
  echo "Erro: npx nao encontrado. Instale Node.js/npm para formatar markdown." >&2
  exit 1
fi

MODE=all
if [ "${1:-}" = "--changed" ]; then
  MODE=changed
  shift
fi
if [ $# -gt 0 ]; then
  MODE=files
fi

case "$MODE" in
  files)
    mapfile -d '' files < <(
      for f in "$@"; do
        case "$f" in
          *.md) [ -f "$f" ] && printf '%s\0' "$f" ;;
          *) echo "Aviso: ignorando nao-markdown: $f" >&2 ;;
        esac
      done
    )
    ;;
  changed)
    mapfile -d '' files < <(
      {
        git diff --name-only -z HEAD -- '*.md' || true
        git ls-files --others --exclude-standard -z -- '*.md' || true
      } | sort -zu
    )
    ;;
  all)
    mapfile -d '' files < <(find . -type f -name '*.md' \
      -not -path './node_modules/*' \
      -not -path './.pi/*' \
      -not -path './.codex/*' \
      -not -path './.git/*' \
      -not -path './.venv/*' \
      -not -path './.pytest_cache/*' \
      -not -path './.mypy_cache/*' \
      -not -path './.ruff_cache/*' \
      -print0)
    ;;
esac

if [ ${#files[@]} -eq 0 ]; then
  echo "Nenhum arquivo .md selecionado (modo: $MODE)."
  exit 0
fi

echo "Modo: $MODE — ${#files[@]} arquivo(s) .md."

MARKDOWNLINT_CONFIG="${MARKDOWNLINT_CONFIG:-.markdownlint.yaml}"
MARKDOWNLINT_CLI2_CONFIG="${MARKDOWNLINT_CLI2_CONFIG:-.markdownlint-cli2.yaml}"

npx --yes prettier --write "${files[@]}"

if [ -f "$MARKDOWNLINT_CONFIG" ]; then
  npx --yes markdownlint-cli --config "$MARKDOWNLINT_CONFIG" --fix "${files[@]}"
else
  npx --yes markdownlint-cli --fix "${files[@]}"
fi

if [ -f "$MARKDOWNLINT_CLI2_CONFIG" ]; then
  npx --yes markdownlint-cli2 --config "$MARKDOWNLINT_CLI2_CONFIG" "${files[@]}"
else
  npx --yes markdownlint-cli2 "${files[@]}"
fi

echo "Markdown formatado e validado com sucesso (modo: $MODE)."
