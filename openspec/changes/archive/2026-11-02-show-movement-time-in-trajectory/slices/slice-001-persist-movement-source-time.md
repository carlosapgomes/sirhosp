# SMT-S1 — Hora de origem persistida no movimento

## 1. Identity

- Change: `show-movement-time-in-trajectory`.
- Task: `openspec/changes/show-movement-time-in-trajectory/tasks.md`, grupo 1.
- Dependências: change `extract-daily-census-from-dom` aceito (hora disponível
  em `CensusSnapshot.source_movement_at` desde a rc.44); contrato proposto,
  não execução autorizada.

## 2. Objective

Persistir a hora real de movimentação no ledger de movimentos, propagada do
snapshot do censo pelo upsert existente, com política explícita e sem
backfill.

Entrega vertical: migração aditiva → campo no modelo → propagação no upsert
→ leitura de volta em PostgreSQL isolado. Helper sem consumidor ou teste só
de schema não aceitam o slice.

## 3. Read first

- `AGENTS.md`, `PROJECT_CONTEXT.md` e `openspec/config.yaml`.
- `openspec/changes/show-movement-time-in-trajectory/{proposal.md,design.md}`
  — decisões D1–D6.
- Delta `specs/patient-movement-model/spec.md` deste change.
- Specs vigentes: `openspec/specs/patient-movement-model/spec.md` e
  `openspec/specs/census-snapshot-processing/spec.md`.
- `apps/census/models.py` (`PatientMovement`, `CensusSnapshot`),
  `apps/census/services.py` (`upsert_patient_movements`, `process_census_snapshot`)
  e migrações recentes de `apps/census/migrations/`.
- Testes entregues por ECD-S1 (`tests/unit/test_census_source_timestamps.py`,
  `tests/integration/test_census_source_timestamps.py`) como referência de
  fixtures e asserções date-only.
- `scripts/test-in-container.sh` (gates oficiais).

## 4. Requirements → Evidence

| ID  | Requisito observável                                                                                                                                   | Evidência planejada                                                                              |
| --- | ------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------ |
| R1  | Movimento criado a partir de snapshot com hora persiste a hora verbatim (aware, timezone configurada); snapshot sem hora produz movimento NULL válido. | Upsert real com snapshots sintéticos; leitura de volta em PostgreSQL; data-only continua aceito. |
| R2  | Política de atualização: último snapshot com hora vence; null não apaga hora existente; movimento NULL ganha hora em reobservação da mesma data.       | Casos de upsert repetido (criação, refresh, ganho-tarde, preservação) em PostgreSQL isolado.     |
| R3  | Sem backfill: movimentos históricos permanecem NULL; constraint `(patient, movement_date, sector)` e comportamentos ECD-S1/S2/S3 preservados.          | Migração em banco com movimento pré-existente; regressões dos slices anteriores.                 |

Referência normativa: delta `patient-movement-model` inteiro; spec de
snapshot na composição, sem reinterpretar D1–D6.

## 5. Expected blast radius

Esperado:

- `apps/census/models.py` (campo),
  `apps/census/migrations/00XX_patientmovement_source_movement_at.py`,
  `apps/census/services.py` (upsert);
- testes unitários do serviço/modelo e teste de integração PostgreSQL.

Sensível: não mudar constraint/identidade, `process_census_snapshot`,
pipeline de extração, `first_seen_at`/`last_seen_at` ou consumidores
date-only. Não adicionar dependência, serviço ou índice.

## 6. Failing-before plan

1. RED R1: snapshot sintético com `source_movement_at` preenchido → upsert
   cria movimento → asserção `source_movement_at` falha (campo inexistente
   na versão atual — usar o erro de atributo/coluna como RED genuíno antes
   do campo existir).
2. RED R2: mesma execução com dois snapshots da mesma data de movimentação
   (primeiro com hora, segundo sem; e primeiro sem, segundo com) → asserções
   da política falham antes da implementação da propagação.
3. Caracterizar R3: movimento pré-existente sem hora permanece NULL após
   migração + upsert de outra data.

TDD nos seams determinísticos; sem dados reais.

## 7. Implementation constraints

- Seguir política de engenharia de `AGENTS.md`; menor mudança correta.
- Campo opcional único (`source_movement_at`), anulável, aware; nenhuma
  inferência de hora (sem meia-noite, sem `captured_at`).
- Propagação ocorre somente no upsert, a partir do snapshot em processamento
  (fonte canônica); nunca em signal, migração de dados ou leitura.
- Snapshot sem hora em update não sobrescreve hora existente (D2).
- Migração aditiva sem backfill e sem índice (D3).
- Sem mudança de API pública, template, view ou CLI neste slice.

## 8. Validation

### Focused validation

- TDD: RED/GREEN por caso R1–R3 com fixtures sintéticos.
- Integração PostgreSQL: mesma suíte isolada usada por ECD-S1.
- Regressões: `tests/unit/test_census_source_timestamps.py`,
  `tests/integration/test_census_source_timestamps.py`,
  suítes de publicação/composição DOM.

### Project-required gates

- `./scripts/test-in-container.sh quality-gate` e `integration` separada
  no estado final.
- `./scripts/markdown-lint.sh` quando `.md` alterado.

## 9. Acceptance criteria

- [ ] R1: hora verbatim persistida e lida de volta; date-only válido.
- [ ] R2: política com quatro casos provada (criar, refresh, ganho-tarde,
      preservar).
- [ ] R3: histórico sem backfill; identidade e regressões preservadas.
- [ ] Gates oficiais e Markdown aprovados; relatório completo.

## 10. Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` se a correspondência snapshot↔movimento
se mostrar ambígua (múltiplos snapshots do mesmo dia com horas divergentes
para o mesmo movimento), se a política D2 conflitar com comportamento
observado do upsert ou se qualquer mudança de identidade/semântica parecer
necessária.

## 11. Evidence report

Produzir `/tmp/sirhosp-slice-SMT-S1-report.md` conforme `AGENTS.md` §13:
status, R1–R3 → evidência/resultado, arquivos/motivo, RED/GREEN, comandos e
exit status, banco, desvios, levers e riscos.

## 12. Worker handoff

Quando aprovado, implementar somente SMT-S1 usando as referências em
contexto fresh. Produzir failing-before evidence, a menor mudança correta,
gates e o relatório. Não atualizar `tasks.md`, criar commit/push/merge ou
iniciar SMT-S2. Finalizar com `READY_FOR_REVIEW` e
`REPORT_PATH=/tmp/sirhosp-slice-SMT-S1-report.md`.
