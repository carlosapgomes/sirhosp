# ADR-0008 — Decisão de correção da coorte fail-only de full-sync

## Status

Proposed

## Contexto

Template preenchível do change
`characterize-fullsync-chronic-failures` (slice CFC-S3). O preenchimento
ocorre no slice CFC-S4, a partir de:

- os agregados da caracterização read-only
  (`characterize_fullsync_failures`, janela 168h, `--min-attempts=3`) —
  coorte fail-only, reasons, timing por estágio, histograma horário e
  contraste fail-then-ok;
- os vereditos do laboratório sintético (`verdicts.json`), que reproduzem
  as hipóteses H1 (timeout por volume/deadline) e H2 (invalid_payload por
  conteúdo) contra o código real de extração e classificação.

Regra não negociável: este documento contém somente agregados. Nenhum
identificador de paciente, run, parâmetro, texto clínico, URL ou erro
bruto pode aparecer em qualquer seção.

## Hipóteses e vereditos

Preencher uma linha por hipótese. `Veredito` deve ser exatamente
`confirmed`, `refuted` ou `inconclusive`; `Evidência` deve citar a seção
do relatório de caracterização e/ou o artefato `verdicts.json`.

| Hipótese | Veredito | Evidência |
| --- | --- | --- |
| H1 — timeout por volume/deadline | `[PREENCHE]` | `[PREENCHE: seção do relatório + entry de verdicts.json]` |
| H2 — invalid_payload por conteúdo | `[PREENCHE]` | `[PREENCHE: seção do relatório + entry de verdicts.json]` |

## Causa comprovada

`[PREENCHE: causas comprovadas pelos vereditos ou "nenhuma hipótese confirmada"]`

## Correção recomendada

`[PREENCHE: change futuro a abrir com a correção de causa comprovada]` —
quando nenhuma hipótese for confirmada, remover esta seção e preencher a
seguinte.

## Próximo experimento

`[PREENCHE: experimento seguinte, somente quando nenhuma hipótese for confirmada]`

## Alternativas rejeitadas

1. `[PREENCHE: alternativa 1 e motivo da rejeição]`
2. `[PREENCHE: alternativa 2 e motivo da rejeição]`

## Consequências

### Positivas

- `[PREENCHE]`

### Negativas / Trade-offs

- `[PREENCHE]`

## Validação

Após preenchimento, este documento deve passar em:

```bash
uv run --no-sync python manage.py generate_fullsync_failure_report \
  --input /tmp/cfc-characterization.txt \
  --output /tmp/cfc-characterization-report.md \
  --check-adr docs/adr/ADR-0008-fullsync-failure-characterization-decision.md
```

Regras objetivas do validador: veredito com evidência, recomendação
presente (correção quando houver hipótese confirmada, próximo experimento
quando nenhuma for confirmada) e zero identidade/conteúdo clínico.

## Referências

- Change OpenSpec `characterize-fullsync-chronic-failures` (proposal,
  design, specs delta, tasks e relatórios CFC-S1 a CFC-S4).
- Relatório de caracterização (gerado por
  `generate_fullsync_failure_report`) e `verdicts.json` do laboratório
  sintético (`automation/lab/playwright_experiments/fullsync_failure_lab.py`).
