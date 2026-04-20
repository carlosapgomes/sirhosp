#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v npx >/dev/null 2>&1; then
  echo "Erro: npx nao encontrado. Instale Node.js/npm para validar markdown." >&2
  exit 1
fi

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

if [ ${#files[@]} -eq 0 ]; then
  echo "Nenhum arquivo .md encontrado."
  exit 0
fi

MARKDOWNLINT_CONFIG="${MARKDOWNLINT_CONFIG:-$HOME/.markdownlint.json}"

if [ -f "$MARKDOWNLINT_CONFIG" ]; then
  npx --yes markdownlint-cli2 --config "$MARKDOWNLINT_CONFIG" "${files[@]}"
else
  npx --yes markdownlint-cli2 "${files[@]}"
fi

echo "Markdown lint OK."
