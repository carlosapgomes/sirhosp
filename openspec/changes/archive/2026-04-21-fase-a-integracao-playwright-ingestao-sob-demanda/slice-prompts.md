
# Índice de prompts por slice

Este arquivo é apenas um índice.

Cada slice possui **seu próprio arquivo de prompt** com handoff explícito para executor LLM iniciando com contexto zero.

## Arquivos de prompt

- `slice-prompts/SLICE-S1.md`
- `slice-prompts/SLICE-S1-5.md`
- `slice-prompts/SLICE-S1-6.md`
- `slice-prompts/SLICE-S2.md`
- `slice-prompts/SLICE-S2-1.md`
- `slice-prompts/SLICE-S3.md`
- `slice-prompts/SLICE-S4.md`
- `slice-prompts/SLICE-S4-1.md`
- `slice-prompts/SLICE-S5.md`

## Convenções

- Um arquivo por slice.
- Cada arquivo define:
  - handoff de entrada (contexto zero);
  - objetivo, escopo e limites do slice;
  - TDD obrigatório;
  - critérios de aceite;
  - validações mínimas;
  - handoff de saída com relatório em `/tmp/sirhosp-slice-<ID>-report.md`.
