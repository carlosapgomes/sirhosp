# Tasks: patient-movement-tracking

## Convenções desta change

- Prefixo de slice: `PMT` (Patient Movement Tracking).
- Execução estrita: 1 slice por vez, com TDD (`red -> green -> refactor`).
- Cada slice deve ter prompt próprio em `slice-prompts/SLICE-PMT-SX.md`.
- Cada slice gera relatório obrigatório em
  `/tmp/sirhosp-slice-PMT-SX-report.md`.
- Se precisar extrapolar escopo/limite de arquivos, parar e reportar bloqueio.

## Slice PMT-S1 — Modelo PatientMovement e migração

**Objetivo vertical:** criar o modelo com unique constraint, índices e campo
`sequence`, com migração funcional.

**Escopo máximo:** 2 arquivos de código + 1 arquivo de teste.

- [ ] 1.1 (RED) Criar `tests/unit/test_patient_movement_model.py` com:
  - `test_create_movement`: cria movimento com campos obrigatórios.
  - `test_unique_constraint`: duplicar `(patient, movement_date, sector)`
    levanta `IntegrityError`.
  - `test_ordering_by_sequence`: ordenação padrão é por `patient` + `sequence`.
  - `test_discharge_type_optional`: `discharge_type` pode ser vazio.
  - `test_admission_nullable`: `admission` pode ser `None`.
  - `test_first_seen_at_and_last_seen_at`: campos de rastreamento temporal.
- [ ] 1.2 Implementar `PatientMovement` em `apps/census/models.py`.
- [ ] 1.3 Gerar migration `0013_patientmovement.py`.
- [ ] 1.4 Gate PMT-S1:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
  - `./scripts/test-in-container.sh lint`
  - `./scripts/test-in-container.sh typecheck`

## Slice PMT-S2 — Serviço de upsert e hook no process_census_snapshot

**Objetivo vertical:** implementar `upsert_patient_movements` que, dado o
último snapshot, faz upsert em `PatientMovement` e recalcula `sequence`.

**Escopo máximo:** 3 arquivos de código + 1 arquivo de teste.

- [ ] 2.1 (RED) Criar `tests/unit/test_patient_movement_service.py` com:
  - `test_creates_movement_for_new_patient`:
    snapshot com paciente novo → cria `PatientMovement`.
  - `test_does_not_duplicate_same_state`:
    mesmo `(patient, movement_date, sector)` em snapshots consecutivos →
    não duplica, apenas atualiza `last_seen_at`.
  - `test_creates_movement_for_new_sector_same_day`:
    mesmo paciente, mesmo dia, setor diferente → cria novo movimento.
  - `test_recalculates_sequence_after_upsert`:
    após upsert de 3 movimentos, `sequence` fica 0, 1, 2 em ordem cronológica.
  - `test_upsert_no_occupied_beds`:
    se não há snapshot com `bed_status=OCCUPIED`, não faz nada.
  - `test_discharge_type_populated_from_alta`:
    `tipo_alta` do snapshot vai para `discharge_type`.
- [ ] 2.2 Implementar `upsert_patient_movements()` em `apps/census/services.py`:
  - busca último snapshot.
  - para cada `bed_status=OCCUPIED`, faz `get_or_create`.
  - recalcula `sequence` com `_recalc_sequences(patient)`.
  - helper `_parse_movement_date` usando a lógica já existente de
    `_parse_dt_int`.
- [ ] 2.3 Adicionar hook no `process_census_snapshot` management command ou
      criar comando `sync_patient_movements` standalone. Decidir durante
      implementação com base no acoplamento.
- [ ] 2.4 Gate PMT-S2:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
  - `./scripts/test-in-container.sh lint`
  - `./scripts/test-in-container.sh typecheck`

## Slice PMT-S3 — Trajetória nos detalhes da internação

**Objetivo vertical:** exibir timeline de movimentações e dias por setor na
página de detalhes da internação.

**Escopo máximo:** 2 templates + 1 view (ajuste) + 1 arquivo de teste.

- [ ] 3.1 (RED) Criar/estender testes em
      `tests/unit/test_services_portal_sectors.py` (ou arquivo dedicado):
  - `test_admission_detail_includes_trajectory`:
    contexto da view contém `movements` quando há `PatientMovement`.
  - `test_trajectory_shows_sector_sequence`:
    template renderiza setores em ordem.
  - `test_trajectory_calculates_days_per_sector`:
    diferença de datas entre movimentos consecutivos é exibida.
  - `test_trajectory_empty_state`:
    sem movimentos, mostra mensagem informativa.
  - `test_trajectory_shows_discharge_when_present`:
    quando `discharge_type` está preenchido, mostra status de saída.
- [ ] 3.2 Criar partial `_patient_trajectory.html` em
      `apps/patients/templates/patients/`:
  - Timeline horizontal com cards por setor.
  - Tabela resumo: setor, entrada, dias, destino.
  - Estado vazio.
- [ ] 3.3 Incluir partial no template de detalhes da internação
      (ex: `admission_detail.html`).
- [ ] 3.4 Gate PMT-S3:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
  - `./scripts/test-in-container.sh lint`
  - `./scripts/test-in-container.sh typecheck`

## Slice PMT-S4 — Página Setores > Ocupação

**Objetivo vertical:** página de ocupação por setor com filtros, cards de
resumo e tabela de pacientes.

**Escopo máximo:** 1 view + 1 template + 1 sidebar update + 1 arquivo de teste.

- [ ] 4.1 (RED) Adicionar testes em
      `tests/unit/test_services_portal_sectors.py`:
  - `test_occupation_page_requires_auth`: anônimo redireciona.
  - `test_occupation_page_renders_with_sector_filter`:
    filtra por setor selecionado.
  - `test_occupation_page_default_period`: sem período, usa 7 dias.
  - `test_occupation_cards_show_correct_totals`:
    total que passaram, ainda no setor, já saíram, permanência média.
  - `test_occupation_table_lists_patients_ordered_by_entry`:
    tabela ordenada por data de entrada.
  - `test_occupation_empty_state`: setor sem movimentos no período.
- [ ] 4.2 Criar view `sector_occupation` em `apps/services_portal/views.py`.
- [ ] 4.3 Criar rota `setores/ocupacao/` em `apps/services_portal/urls.py`.
- [ ] 4.4 Criar template `sector_occupation.html`.
- [ ] 4.5 Atualizar `base_sidebar.html` com menu `Setores` expansível.
- [ ] 4.6 Gate PMT-S4:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
  - `./scripts/test-in-container.sh lint`
  - `./scripts/test-in-container.sh typecheck`

## Slice PMT-S5 — Página Setores > Indicadores

**Objetivo vertical:** página de indicadores agregados com 4 cards analíticos.

**Escopo máximo:** 1 view + 1 template + 1 sidebar update (se necessário) +
1 arquivo de teste.

- [ ] 5.1 (RED) Adicionar testes em
      `tests/unit/test_services_portal_sectors.py`:
  - `test_indicators_page_requires_auth`: anônimo redireciona.
  - `test_indicators_avg_stay_by_sector`:
    card de permanência média mostra valores corretos.
  - `test_indicators_top_destinations_from_origin`:
    card de setores que mais recebem de origem X (com dropdown).
  - `test_indicators_long_stay_patients`:
    card de pacientes >15 dias no mesmo setor.
  - `test_indicators_bottlenecks`:
    card de gargalos (entradas > saídas) por setor.
  - `test_indicators_empty_state`: sem dados no período.
- [ ] 5.2 Criar view `sector_indicators` em `apps/services_portal/views.py`.
- [ ] 5.3 Criar rota `setores/indicadores/` em `apps/services_portal/urls.py`.
- [ ] 5.4 Criar template `sector_indicators.html`.
- [ ] 5.5 Gate PMT-S5:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
  - `./scripts/test-in-container.sh lint`
  - `./scripts/test-in-container.sh typecheck`

## Stop Rule

- Implementar somente o slice atual.
- Parar ao final de cada slice e aguardar aprovação humana.
- Não avançar de slice sem relatório completo e gates verdes.
