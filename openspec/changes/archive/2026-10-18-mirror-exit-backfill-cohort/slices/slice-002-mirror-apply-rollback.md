# SLICE-BME-S2 — Apply e rollback da coorte mirror

## Objetivo

`apply_backfill_plan` processa itens `mirror_exits` emitindo o evento de
procedência (sem mutar a internação) e o rollback por batch/operação
restaura a evidência ao estado anterior. Comportamento observável
end-to-end: apply → evento + evidência reconciled + Admission intacta;
rollback → evidência `pending` novamente.

## Contexto necessário

- `apps/patients/backfill.py` — `apply_backfill_plan`, payloads de batch
  (`details_json["backfill"]`), funções de rollback por batch/operação
  implementadas no S9 (leia o tratamento das coortes existentes:
  discharges replay e merges).
- `apps/patients/models.py` — `ReconciliationEvent`
  (`status`, `exit_type`, `reason_code`, `prior_discharge_date`,
  `new_discharge_date`, `source_kind/source_id`, `details_json`). A
  `DischargeRecord` vive em `apps/discharges/models.py`
  (`reconciliation_status`, `reconciled_at`).
- `apps/patients/reconciliation.py` — `reverse_reconciliation` (o
  rollback existente emite o evento inverso e **não toca** a evidência;
  a restauração é responsabilidade do rollback do backfill — design D5).
- `openspec/changes/mirror-exit-backfill-cohort/design.md` — decisões D2
  e D5 (formato do evento, inversão).
- Pré-requisito: SLICE-BME-S1 aplicado (coorte no planner).

## Requisitos verificáveis

- R1: apply de item mirror cria `ReconciliationEvent` com
  `status=reconciled`, `exit_type=hospital_discharge`,
  `reason_code="mirror_exit"`, `new_discharge_date` = `discharge_date`
  espelhado, `source_kind/source_id` da evidência e
  `details_json["backfill"]` com o batch UUID.
- R2: `DischargeRecord` fica `reconciled` com `reconciled_at`;
  `Admission` permanece byte-a-byte igual (assert de não-mutação:
  `refresh_from_db` e comparação dos campos relevantes, incluindo
  `discharge_date`).
- R3: idempotência — re-planejar após apply não gera item mirror para a
  mesma evidência (ela não é mais `pending`).
- R4: rollback por batch restaura `DischargeRecord` para o status prévio
  (`pending`, `reconciled_at` limpo) — mecanismo: no rollback de
  `backfill.py`, **após** `reverse_reconciliation` emitir o evento
  inverso, resolver a evidência por `event.source_kind`/`event.source_id`
  e restaurá-la **na mesma transação**; a `Admission` segue intacta.
  Assimetria documentada: a internação permanece contada na série
  canônica enquanto o último evento reconciled for `hospital_discharge`
  (D5) — o teste afirma esse comportamento, não a exclusão da série.
- R5: rollback de operação única (UUID do evento mirror) funciona com o
  mesmo contrato.
- R6: saída agregada do apply/rollback sem identidade (contadores,
  batch, status); o apply imprime `applied cohort=mirror_exits` (estenda
  a impressão de cohorts do comando — incluída no blast radius).

## Matriz requisito -> arquivo -> teste/check

| Requisito        | Arquivo(s)                                                                | Teste/check                                                                                                                           |
| ---------------- | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| R1, R2           | `apps/patients/backfill.py`, `tests/unit/test_backfill_mirror_exit.py`    | `test_apply_emits_mirror_event_and_marks_evidence`                                                                                    |
| R2 (não-mutação) | idem                                                                      | `test_apply_leaves_admission_untouched`                                                                                               |
| R3               | idem                                                                      | `test_replan_after_apply_has_no_mirror_item`                                                                                          |
| R4               | idem                                                                      | `test_batch_rollback_restores_pending` (inclui assert da assimetria documentada: último evento reconciled segue `hospital_discharge`) |
| R5               | idem                                                                      | `test_single_operation_rollback_restores_pending`                                                                                     |
| R6               | `apps/ingestion/management/commands/reconcile_admission_history.py`, idem | `test_apply_output_is_aggregate_only`, `test_apply_prints_mirror_cohort_line`                                                         |

## Escopo e expected blast radius

```yaml
expected_files:
  - apps/patients/backfill.py
  - apps/ingestion/management/commands/reconcile_admission_history.py
  - tests/unit/test_backfill_mirror_exit.py
allowed_incidental_files: []
out_of_scope:
  - agregado S8/refresh, specs, tasks.md, migrations
  - qualquer mudança em apps/patients/reconciliation.py (a restauração da
    evidência vive no rollback do backfill, não no serviço online)
```

Migrações ou novos campos de modelo são **bloqueio**, não trabalho deste
slice.

## RED

- comando:
  `uv run pytest -q tests/unit/test_backfill_mirror_exit.py -k "apply or rollback or replan or aggregate"`
- falha esperada: com o guard R8 do S1, o apply de item mirror levanta
  `BackfillItemFailed` com o motivo de payload ainda não suportado (e o
  asserto do evento `mirror_exit` ausente falha) — provando que a
  execução não existe.

## GREEN / verificação local

- mesmo comando — exit 0.
- regressão local: `uv run pytest -q tests/unit/test_admission_reconciliation_backfill.py
tests/unit/test_backfill_mirror_exit.py` e a suíte de integração de
  apply/rollback:
  `./scripts/test-in-container.sh integration` (a cobertura existente
  vive em
  `tests/integration/test_admission_reconciliation_backfill_commands.py`,
  acionada pelos comandos por nome) — exit 0.
- lint parcial dos arquivos tocados.

## Gates do slice (após GREEN)

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
uv run openspec validate mirror-exit-backfill-cohort --strict
```

## Critérios de aceitação

- [ ] R1..R6 verdes
- [ ] Suítes de apply/rollback existentes verdes
- [ ] Gates do slice verdes
- [ ] Nenhum arquivo fora do blast radius; zero migrations

## Entrega

Relatório em `/tmp/sirhosp-slice-BME-S2-report.md` (mesmo formato).
Sem commit, sem `tasks.md`, sem dados sensíveis.
