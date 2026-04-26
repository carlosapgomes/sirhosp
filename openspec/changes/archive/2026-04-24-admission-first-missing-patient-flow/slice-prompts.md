
# Índice de prompts por slice

Cada slice possui arquivo próprio com handoff para executor iniciando com contexto zero.

## Arquivos de prompt

- `slice-prompts/SLICE-S1.md`
- `slice-prompts/SLICE-S2.md`
- `slice-prompts/SLICE-S3.md`
- `slice-prompts/SLICE-S4.md`
- `slice-prompts/SLICE-S5.md`

## Convenções obrigatórias por slice

- Escopo e limite explícito de arquivos alterados.
- TDD quando aplicável (`red -> green -> refactor`).
- Gates com comandos oficiais containerizados.
- Relatório obrigatório em `/tmp/sirhosp-slice-AFMF-SX-report.md` com snippets before/after.
- Parar ao final de cada slice (sem avançar automaticamente).
