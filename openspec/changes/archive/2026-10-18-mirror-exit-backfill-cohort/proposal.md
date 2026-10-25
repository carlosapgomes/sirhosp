# Proposal: mirror-exit-backfill-cohort

## Why

A reconciliação canônica de saídas exige `ReconciliationEvent`
reconciled com `exit_type=hospital_discharge` (definição S8: a série
canônica conta somente saídas com procedência). Meses cujo espelho de
internações foi re-extraído em massa (abril e agosto de 2026, legado do
defeito pré-28/08) têm internações que chegam ao domínio **já fechadas**
(`discharge_date` espelhado do fonte) — a saída está registrada, mas sem
evento, e portanto **não conta na série canônica** do gráfico e do
agregado. Em produção (2026-09-07): agosto 528/1.630 e abril 294/1.615
reconciled, com ~2.400 altas `pending` cuja internação-âncora existe
fechada. O resultado é um gráfico histórico incompatível com a realidade
operacional (sumários ≫ saídas canônicas).

## What Changes

- Nova coorte aprovada no backfill (`mirror_exits`): altas `pending`
  cujo paciente resolve unicamente para **uma internação já fechada cujo
  intervalo espelhado `[admission_date, discharge_date]` contém a
  `alta_em`** — o espelho corrobora a saída.
- Aplicação da coorte: cria `ReconciliationEvent`
  `reconciled`/`hospital_discharge` com `reason_code="mirror_exit"` e
  linkage de batch em `details_json` (procedência auditável:
  **espelho**, não extração do dia); marca a `DischargeRecord` como
  `reconciled`; **não altera a internação** (a data já está correta por
  espelho).
- Ordem determinística do plano: duplicados → altas exatas →
  **mirror exits** → óbitos → revisão manual.
- Reversibilidade: rollback por batch estendido à coorte (evento inverso
  restaura o estado anterior da evidência).
- Consequência direta: a série canônica (`saida_em` por evento) passa a
  cobrir o histórico espelhado, fechando a lacuna apontada na operação.

## Impact

- **Código**: `apps/patients/backfill.py` (nova coorte no planner e no
  apply/rollback), comando `reconcile_admission_history` (linha de
  saída da coorte), testes unitários novos.
- **Specs**: `admission-reconciliation-backfill` (MODIFIED nos
  requisitos de coortes aprovadas, ordem e reversibilidade).
- **Dados**: nenhum schema novo (evento append-only com
  `reason_code`/`details_json` existentes); aplicação é bounded por
  `--limit` e auditada por batch UUID como as demais coortes.
- **Risco controlado**: a coorte nunca muta `Admission`; pares com mais
  de uma candidata fechada vão para revisão manual (não elegíveis).
