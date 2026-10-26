# SLICE-DD-S2 — Apply/rollback com marcador de precisão

## Objetivo

O apply do item de óbito date-only fecha a internação em D 00:00
`America/Bahia` (portadora da data, D2) com evento `exit_type=death`
carregando marcador explícito de precisão em `details_json`; rollback e
idempotência preservados; nenhuma agregação por data local muda com a hora
portadora.

## Contexto necessário

- `apps/patients/backfill.py` — `_execute_item`, `apply_backfill_plan`,
  rollback por batch/operacao (`collect_backfill_batch_items`,
  `_validate_batch_post_states`).
- Serviço online de reconciliação de óbito usado pelo apply (mesmo caminho
  do datetime completo hoje).
- `openspec/changes/reconcile-date-only-deaths/design.md` — D2, D4 e D6.
- Spec delta `admission-exit-reconciliation` (cenários date-only).

## Requisitos verificáveis

- R1: apply cria evento `status=reconciled`, `exit_type=death`,
  `new_discharge_date` = D 00:00 `America/Bahia`, com
  `details_json.death_exit={"precision": "date", "local_date": D}` (forma
  exata definida na implementação junto ao formato existente de
  `details_json`).
- R2: internação fechada em D; `obito_em` do `DeathRecord` permanece nulo
  (nenhuma hora sintetizada no evidência).
- R3: rollback por batch e por operação restaura internação e evidência
  (pós-estado validado, zero escritas em conflito).
- R4: reaplicar item já reconciliado é idempotente (already_reconciled).
- R5: agregações por data local (contagens diárias, indicadores) idênticas
  com hora portadora 00:00; indicadores de altas seguem excluindo óbitos.
- R6: nenhum template/serialização novo exibe hora para fechamento
  date-only (checagem mecânica de superfícies existentes que renderizam
  `discharge_date` de óbito — se alguma exibir, esconder/mostrar data
  apenas, com teste).

## Expected blast radius

- `apps/patients/backfill.py` (apply/rollback do item de óbito, marcador);
- serviço online de reconciliação de óbito (se o marcador for gravado lá);
- `tests/unit/` e `tests/integration/` de backfill/óbito.

## Estratégia de teste/verification

TDD: unitários R1–R5; integração do comando em `--apply` com banco
sintético efêmero (canário `--limit` pequeno, label e backup-ref falsos
em teste) validando batch e rollback. Gates: `check`, `unit`,
`integration`, `lint`, `typecheck`.

## Condições de bloqueio

- superficie existente que exiba hora de fechamento de óbito e cujo ajuste
  escape do blast radius → escalar;
- qualquer consumo analítico que trate 00:00 como hora clínica real →
  `BLOCKED_NEEDS_DECISION`.
