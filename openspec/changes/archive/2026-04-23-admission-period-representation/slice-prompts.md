# Índice de prompts por slice

Change: `admission-period-representation`

## Arquivos de prompt

- `slice-prompts/SLICE-S1.md`
- `slice-prompts/SLICE-S2.md`
- `slice-prompts/SLICE-S3.md`
- `slice-prompts/SLICE-S4.md`
- `slice-prompts/SLICE-S5.md`

## Convenções obrigatórias

- Executor inicia cada slice com contexto zero.
- Ler `AGENTS.md`, `PROJECT_CONTEXT.md` e artefatos da change antes de codar.
- Implementar somente o slice corrente.
- TDD quando aplicável (red -> green -> refactor).
- Respeitar limite de arquivos por slice.
- Gerar relatório em `/tmp/sirhosp-slice-APR-SX-report.md` com snippets before/after.
- Parar ao final de cada slice.
