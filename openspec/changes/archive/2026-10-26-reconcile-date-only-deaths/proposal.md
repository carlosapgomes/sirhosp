# Proposal: reconcile-date-only-deaths

## Why

O sistema fonte **nunca fornece hora de óbito**: 100% dos `DeathRecord` são
apenas data em todos os meses observados (ago/2026: 120/120, set/2026:
97/97, out/2026: 75/75). O critério atual exige datetime completo, então
**nenhum óbito reconcilia nunca**: 777 acumulados hoje, crescendo
~75–120/mês, com episódios que jamais fecham por morte.

Decisão do operador (2026-10-25): o critério de óbito passa a aceitar
apenas data.

## What Changes

- Evidência de óbito com somente data reconcilia **em precisão de data**:
  fecha a internação **única** cujo período conhecido contém a data local
  do óbito (`America/Bahia`), com `exit_type=death` e **marcador explícito
  de precisão date-only** no evento; nenhuma superfície pode exibir ou usar
  a hora desse fechamento.
- Ambiguidade (mais de uma internação contém a data) ou não-resolução
  continuam fail-closed: pendente + revisão manual, sem fechamento.
- Evidência com datetime completo mantém o comportamento atual.
- A coorte `deaths` do backfill passa a aceitar óbitos date-only; a
  aplicação retroativa dos 777 usa o fluxo delimitado existente
  (dry-run → canário 50 → lotes ≤100, backup e rollback).
- Óbitos seguem excluídos dos indicadores de altas hospitalares
  (`exit_type=death` ≠ `hospital_discharge`; S8 inalterada).

### Fora de escopo

- Reconciliação automática diária de óbitos pelo runtime adaptativo
  (permanece fluxo de backfill operado);
- mudança na taxonomia de saídas ou nos indicadores;
- as pendências de abril/agosto (ruído do fonte, ADR-0013);
- o gotejamento mensal de ~40 `admission_not_found` de altas.

## Capabilities

### New Capabilities

Nenhuma.

### Modified Capabilities

- `admission-exit-reconciliation` — o requisito de óbito date-only muda de
  "não reconcilia, não sintetiza hora" para "reconcilia em precisão de
  data com marcador explícito; hora jamais apresentada como informação do
  fonte; ambíguo continua pendente".
- `admission-reconciliation-backfill` — a coorte `deaths` aceita evidência
  date-only única; ordem determinística e guardrails (dry-run default,
  canário, lotes, rollback) inalterados.

## Impact

- Código: matcher de óbito (`decide_discharge_match`/evidências),
  planner (`_death_candidates`), caminho de apply/rollback do item de
  óbito (marcador de precisão). Sem migrations (marcador vive em
  `details_json`; fechamento usa data local a 00:00 como portadora da
  data — ver design D2).
- Ativação: operação delimitada sobre 777 registros históricos após
  implementação, com backup e rollback.
- Risco clínico: fechamento de episódio por morte em precisão de data —
  mitigado por unicidade obrigatória, marcador de precisão e exclusão dos
  indicadores de alta.
