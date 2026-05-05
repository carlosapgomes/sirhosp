# Índice de prompts por slice

Change: `summary-two-phase-pipeline-traceability`

## Arquivos

- `SLICE-STP-S1.md`
- `SLICE-STP-S2.md`
- `SLICE-STP-S3.md`
- `SLICE-STP-S4.md`
- `SLICE-STP-S5.md`
- `SLICE-STP-S6.md`
- `SLICE-STP-S7.md`
- `SLICE-STP-S8.md`
- `SLICE-STP-S9.md`
- `REPORT-TEMPLATE.md`

## Convenções obrigatórias

- Executor inicia cada slice com contexto zero.
- Ler AGENTS/PROJECT_CONTEXT e artefatos da change antes de codar.
- Implementar apenas o slice corrente.
- Slice vertical e enxuto: tocar o mínimo de arquivos necessários.
- TDD obrigatório (`red -> green -> refactor`) sempre que viável.
- Aplicar princípios de clean code:
  - funções pequenas e coesas;
  - nomes claros;
  - evitar duplicação;
  - erros explícitos;
  - refactor seguro sem ampliar escopo.
- Rodar gates descritos no prompt do slice.
- Gerar relatório em `/tmp/sirhosp-slice-STP-SX-report.md`.
- Parar ao final do slice e não avançar automaticamente.
