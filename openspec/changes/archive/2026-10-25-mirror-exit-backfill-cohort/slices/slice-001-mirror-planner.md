# SLICE-BME-S1 — Coorte mirror no planner (plano e dry-run)

## Objetivo

O planner do backfill ganha a coorte `mirror_exits`: `DischargeRecord`
`pending` cujo paciente resolve unicamente e existe **exatamente uma**
`Admission` canônica já fechada com intervalo espelhado contendo
`alta_em`. O dry-run do comando imprime a coorte; ambiguidades viram
contadores de revisão manual com reasons explícitos.

## Contexto necessário

- `apps/patients/backfill.py` — dataclasses `DuplicateItem`,
  `DischargeItem`, `DeathItem`, `CohortPlan`, `BackfillPlan`, e as
  funções de planejamento existentes (cohortes duplicates/discharges/
  deaths e `manual_review`). Siga o padrão de pureza (sem I/O além do
  ORM de consulta).
- `apps/ingestion/management/commands/reconcile_admission_history.py` —
  onde cada coorte imprime `cohort=<nome> eligible=N bounded=M`.
- `openspec/changes/mirror-exit-backfill-cohort/design.md` — decisões
  D1, D3 e D4 (critério exato, reasons manuais, ordem).
- Fixtures: use `tests/unit/` existentes de backfill como referência de
  estilo (nomes sintéticos, sem dados reais).

## Requisitos verificáveis

- R1: pending + **não elegível para a coorte exact** + paciente único +
  exatamente 1 Admission canônica (`merged_into` nulo) com
  `admission_date <= alta_em <= discharge_date` e `discharge_date`
  não-nulo → item da coorte `mirror_exits`.
- R2: mais de uma candidata fechada na janela → `manual_review`
  `discharges:mirror_ambiguous` (contagem, sem item).
- R3: paciente não resolvível → `manual_review`
  `discharges:mirror_patient_not_found`; `alta_em` nula permanece no
  reason existente `discharges:missing_saida_em` (nunca mirror).
- R4: internação aberta (discharge_date nulo) **ou** record reivindicado
  pela coorte exact (`decide_discharge_match`) NÃO vira mirror — o
  mesmo `record_id` jamais aparece em `discharges` e `mirror_exits`
  no mesmo plano.
- R5: ordem do plano `duplicates → discharges → mirror_exits → deaths`.
- R6: `--limit` borna a coorte como às demais (`truncated` verdadeiro
  quando total > itens).
- R7: invocação do comando **sem `--apply`** (dry-run é o padrão; a
  flag `--dry-run` NÃO existe) imprime
  `cohort=mirror_exits eligible=N bounded=M` e nada é mutado.
- R8: payload `MirrorExitItem` que chegar ao `_execute_item` antes do
  SLICE-BME-S2 levanta `BackfillItemFailed` com motivo explícito de
  payload ainda não suportado (guard de roteamento; nunca cai no branch
  de óbitos).

## Matriz requisito -> arquivo -> teste/check

| Requisito | Arquivo(s)                                                                | Teste/check                                                                                   |
| --------- | ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------- |
| R1        | `apps/patients/backfill.py`, `tests/unit/test_backfill_mirror_exit.py`    | `test_unique_closed_anchor_is_eligible`                                                       |
| R2        | idem                                                                      | `test_two_closed_candidates_go_to_manual_review`                                              |
| R3        | idem                                                                      | `test_unresolvable_patient_goes_to_manual_review`, `test_null_alta_em_stays_missing_saida_em` |
| R4        | idem                                                                      | `test_open_admission_never_becomes_mirror`, `test_exact_eligible_record_never_becomes_mirror` |
| R5        | idem                                                                      | `test_plan_order_duplicates_discharges_mirror_deaths`                                         |
| R6        | idem                                                                      | `test_limit_truncates_mirror_cohort`                                                          |
| R7        | `apps/ingestion/management/commands/reconcile_admission_history.py`, idem | `test_dry_run_prints_mirror_cohort_line` (chama o comando sem `--apply` e captura stdout)     |
| R8        | `apps/patients/backfill.py`, idem                                         | `test_mirror_payload_apply_raises_not_supported`                                              |

## Escopo e expected blast radius

```yaml
expected_files:
  - apps/patients/backfill.py
  - apps/ingestion/management/commands/reconcile_admission_history.py
  - tests/unit/test_backfill_mirror_exit.py
allowed_incidental_files: []
out_of_scope:
  - apply/rollback (SLICE-BME-S2)
  - agregado S8, specs, tasks.md, migrations
```

Se a coorte exigir tocar qualquer outro arquivo (ex.: modelos), PARE e
reporte bloqueio — não crie migrations nem campos novos.

## RED

- comando:
  `uv run pytest -q tests/unit/test_backfill_mirror_exit.py`
- falha esperada: `AttributeError`/assertos de plano sem a coorte
  (`BackfillPlan` atual não tem `mirror_exits`; a linha
  `cohort=mirror_exits` não é impressa) — provando que o planejamento
  ainda não existe.

## GREEN / verificação local

- mesmo comando — exit 0.
- regressão local: `uv run pytest -q tests/unit/test_admission_reconciliation_backfill.py`
  (suíte de planner existente; se não existir no layout final, descubra
  com `rg -l "BackfillPlan" tests/unit` e rode os arquivos listados) —
  exit 0.
- lint parcial dos arquivos tocados.

## Gates do slice (após GREEN)

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
uv run openspec validate mirror-exit-backfill-cohort --strict
```

## Critérios de aceitação

- [ ] R1..R8 verdes
- [ ] Suítes de planner existentes verdes (sem mudança de comportamento
      nas coortes atuais)
- [ ] Gates do slice verdes
- [ ] Blast radius respeitado

## Entrega

Relatório em `/tmp/sirhosp-slice-BME-S1-report.md` (snippets
antes/depois, contagens, comandos/resultados, riscos). Sem commit, sem
`tasks.md`, sem dados sensíveis.
