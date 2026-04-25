<!-- markdownlint-disable MD013 -->
# Índice de prompts por slice

Cada slice possui arquivo próprio com handoff de entrada para executor iniciando com contexto zero.

## Arquivos de prompt

- `slice-prompts/SLICE-S1.md`
- `slice-prompts/SLICE-S2.md`
- `slice-prompts/SLICE-S3.md`
- `slice-prompts/SLICE-S4.md`

## Convenções obrigatórias por slice

- Escopo e limite explícito de arquivos alterados.
- TDD quando aplicável (red -> green -> refactor).
- Gates de aceite com comandos e critérios objetivos.
- Relatório obrigatório em `/tmp/sirhosp-slice-<ID>-report.md` com snippets before/after por arquivo alterado.
- Parar ao final do slice (sem avançar automaticamente).
