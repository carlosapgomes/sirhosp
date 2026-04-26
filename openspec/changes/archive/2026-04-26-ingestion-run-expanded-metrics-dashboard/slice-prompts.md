# Índice de prompts por slice

Change: `ingestion-run-expanded-metrics-dashboard`

## Arquivos de prompt

- `slice-prompts/SLICE-S1.md`
- `slice-prompts/SLICE-S2.md`
- `slice-prompts/SLICE-S3.md`
- `slice-prompts/SLICE-S4.md`
- `slice-prompts/SLICE-S5.md`
- `slice-prompts/SLICE-S6.md`
- `slice-prompts/SLICE-S7.md`
- `slice-prompts/SLICE-S8.md`

## Convenções obrigatórias

- Executor inicia cada slice com contexto zero.
- Ler `AGENTS.md` e `PROJECT_CONTEXT.md` antes de codar.
- Ler os artefatos da change e o prompt do slice atual.
- Implementar somente o slice corrente.
- Aplicar TDD (`red -> green -> refactor`).
- Respeitar limite de arquivos por slice.
- Rodar comandos de validação informados no slice.
- Gerar relatório obrigatório em `/tmp/sirhosp-slice-IRMD-SX-report.md`.
- Cada relatório deve conter snippets before/after por arquivo alterado.
- Parar ao final de cada slice.
