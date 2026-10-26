# SLICE-DD-S1 — Matching date-only no planner

## Objetivo

O caminho de óbito passa a casar evidência date-only em granularidade de
data local: fecha como elegível da coorte `deaths` o óbito sem hora que
resolve **exatamente uma** internação cujo período conhecido contém a data
local. Ambiguidades e não-resoluções continuam fail-closed como contadores
de revisão manual.

## Contexto necessário

- `apps/patients/reconciliation.py` — `decide_discharge_match` e
  `DischargeExitEvidence` (camadas de identidade, fail-closed, janelas em
  `America/Bahia`).
- `apps/patients/backfill.py` — `_death_candidates`, `_parse_death_datetime`,
  reasons `REVIEW_DATE_ONLY`/`REVIEW_*`, `COHORT_DEATHS`.
- `apps/ingestion/management/commands/reconcile_admission_history.py` —
  impressão `cohort=deaths eligible=N bounded=M`.
- `openspec/changes/reconcile-date-only-deaths/design.md` — D1 e D3.
- Testes de backfill existentes em `tests/unit/` como referência de estilo
  (fixtures sintéticos, nunca dados reais).

## Requisitos verificáveis

- R1: `DeathRecord` sem hora + paciente único + exatamente 1 internação
  canônica com data local de `admission_date` ≤ D e (`discharge_date`
  nulo ou data local ≥ D) → item da coorte `deaths`.
- R2: mais de uma internação contendo D → revisão manual
  `deaths:ambiguous`; paciente inexistente → `deaths:patient_not_found`;
  sem internação compatível → `deaths:admission_not_found`. Nenhuma
  heurística de desempate.
- R3: `deaths:date_only` deixa de existir como reason; dry-run imprime a
  coorte `deaths` com a nova elegibilidade.
- R4: óbito com datetime completo → comportamento atual inalterado
  (regressão).
- R5: ordem determinística do plano mesclado preservada.

## Expected blast radius

- `apps/patients/reconciliation.py` (evidência/matching de óbito);
- `apps/patients/backfill.py` (`_death_candidates`, reasons);
- `tests/unit/` de reconciliação/backfill.

## Estratégia de teste/verification

TDD: unitários primeiro (R1–R5), depois integração do comando em dry-run
com fixture sintético mostrando `cohort=deaths` elegível e reasons
corretos. Gates: `check`, `unit`, `lint`, `typecheck`.

## Condições de bloqueio

- descoberta de consumidor da hora de fechamento que exija hora real de
  óbito (clínico) → `BLOCKED_NEEDS_DECISION`;
- ambiguidade na semântica de "período conhecido contém a data" que
  contradiga a spec → escalar antes de codar.
