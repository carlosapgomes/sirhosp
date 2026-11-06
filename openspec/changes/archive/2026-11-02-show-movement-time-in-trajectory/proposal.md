# Proposal

## Why

A coleta de censo por DOM (rc.44) passou a capturar e persistir a hora real
de movimentação do portal em `CensusSnapshot.source_movement_at`, mas essa
informação não chega à equipe clínica: a seção `Trajetória` da página de
admissão continua exibindo apenas datas. A equipe precisa da hora visível
quando disponível para localizar o paciente no tempo (por exemplo,
movimentação noturna entre setores).

## What Changes

- `PatientMovement` ganha campo opcional `source_movement_at`
  (timestamp aware, anulável): a hora real de movimentação propagada do
  snapshot do censo que originou/atualizou o movimento.
- `upsert_patient_movements` propaga `CensusSnapshot.source_movement_at`
  para o movimento correspondente na mesma execução (snapshot mais recente
  vence; movimento sem hora no snapshot permanece sem hora; sem backfill de
  movimentos históricos).
- A view de admissão inclui a hora (quando presente) em cada entrada da
  trajetória; o template exibe `DD/MM/AAAA HH:MM` quando a hora existe e
  apenas `DD/MM/AAAA` quando não existe — pacientes em trajetória há tempo
  verão entradas antigas só com data e recentes com data e hora.
- Durações por setor ("dias") continuam calculadas por **data**; identidade,
  deduplicação e ordenação da trajetória permanecem inalteradas.

## Capabilities

### New Capabilities

- (nenhuma)

### Modified Capabilities

- `patient-movement-model` — campo opcional de hora de origem com política
  de propagação a partir do snapshot do censo.
- `patient-trajectory-view` — exibição condicional da hora de movimentação
  na linha do tempo.

## Impact

- Migração aditiva (coluna anulável em `PatientMovement`); sem backfill e
  sem alteração de constraints existentes.
- Afeta: `apps/census/models.py`, `apps/census/services.py`
  (`upsert_patient_movements`), `apps/patients/views.py`,
  `apps/patients/templates/patients/timeline.html` e respectivos testes.
- Não muda: identidade única `(patient, movement_date, sector)`, cálculo de
  durações, consumidor date-only existente, extração de censo, semântica
  clínica ou UI além da anotação de hora na trajetória.
- Privacidade: a hora exibida vem exclusivamente da fonte (tooltip do
  portal); nenhuma inferência de hora é introduzida.
