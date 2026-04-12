#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if ! command -v npx >/dev/null 2>&1; then
  echo "Erro: npx nao encontrado. Instale Node.js/npm para formatar markdown." >&2
  exit 1
fi

mapfile -d '' files < <(find . -type f -name '*.md' \
  -not -path './node_modules/*' \
  -not -path './.pi/*' \
  -not -path './.codex/*' \
  -not -path './.git/*' \
  -print0)

if [ ${#files[@]} -eq 0 ]; then
  echo "Nenhum arquivo .md encontrado."
  exit 0
fi

npx --yes prettier --write "${files[@]}"
npx --yes markdownlint-cli --fix "${files[@]}"
npx --yes markdownlint-cli "${files[@]}"

echo "Markdown formatado e validado com sucesso."
