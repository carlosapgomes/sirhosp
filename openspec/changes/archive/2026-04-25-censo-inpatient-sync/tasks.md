<!-- markdownlint-disable MD013 -->
# Tasks: censo-inpatient-sync

## 1. Slice S1 — App `census` + modelo `CensusSnapshot`

Escopo: criar o app Django `census` com modelo, migração e admin básico.

Limite: até **5 arquivos novos**.

Prompt executor: `slice-prompts/SLICE-S1.md`.

- [ ] 1.1 Criar `apps/census/__init__.py`
- [ ] 1.2 Criar `apps/census/apps.py` com `CensusConfig`
- [ ] 1.3 Criar `apps/census/models.py` com `BedStatus(TextChoices)` e `CensusSnapshot`
- [ ] 1.4 Criar `apps/census/admin.py` com `CensusSnapshotAdmin`
- [ ] 1.5 Criar migração `0001_initial.py`
- [ ] 1.6 (RED) Criar `tests/unit/test_census_models.py` com teste de criação e classificação
- [ ] 1.7 Registrar `apps.census` em `INSTALLED_APPS`
- [ ] 1.8 **Gate S1**: `./scripts/test-in-container.sh check unit`
- [ ] 1.9 Gerar `/tmp/sirhosp-slice-CIS-S1-report.md`

## 2. Slice S2 — Script de extração do censo integrado

Escopo: copiar/adaptar `busca_todos_pacientes_slim.py` para `automation/source_system/current_inpatients/extract_census.py` e extrair o módulo `source_system` compartilhado.

Limite: até **4 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S2.md`.

- [ ] 2.1 Copiar `busca_todos_pacientes_slim.py` → `automation/source_system/current_inpatients/extract_census.py`
- [ ] 2.2 Adaptar imports para usar `automation/source_system/medical_evolution/source_system.py`
- [ ] 2.3 Extrair helpers compartilhados (`get_censo_frame`, `wait_ajax_idle`, etc.) para manter dry
- [ ] 2.4 Garantir que o script aceita parâmetros CLI: `--headless`, `--output-dir`, `--csv-output`
- [ ] 2.5 (RED) Teste unitário do contrato de saída (CSV com colunas corretas, via mock)
- [ ] 2.6 **Gate S2**: `./scripts/test-in-container.sh check unit lint`
- [ ] 2.7 Gerar `/tmp/sirhosp-slice-CIS-S2-report.md`

## 3. Slice S3 — Management command `extract_census` + parser CSV + classificador de leitos

Escopo: command que executa o script, faz parse do CSV, classifica `bed_status` e popula `CensusSnapshot`.

Limite: até **5 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S3.md`.

- [ ] 3.1 Criar `apps/census/services.py` com `classify_bed_status(prontuario, nome) -> str`
- [ ] 3.2 Criar `apps/census/census_parser.py` com `parse_census_csv(csv_path) -> list[dict]`
- [ ] 3.3 Criar `apps/census/management/commands/extract_census.py`
- [ ] 3.4 (RED) Tests: `test_bed_classification.py` (todos os padrões), `test_extract_census_command.py` (com mock)
- [ ] 3.5 **Gate S3**: `./scripts/test-in-container.sh check unit lint`
- [ ] 3.6 Gerar `/tmp/sirhosp-slice-CIS-S3-report.md`

## 4. Slice S4 — Processador de censo: descoberta de pacientes + enfileiramento

Escopo: serviço `process_census_snapshot()` que lê snapshot, cria/atualiza `Patient`, enfileira `admissions_only` runs.

Limite: até **5 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S4.md`.

- [ ] 4.1 Criar `apps/census/services.py` — função `process_census_snapshot(run_id) -> dict` com métricas
- [ ] 4.2 Criar `apps/census/management/commands/process_census_snapshot.py`
- [ ] 4.3 Para cada prontuário ocupado: `get_or_create Patient` + atualizar nome se diferente
- [ ] 4.4 Enfileirar `IngestionRun(intent="admissions_only")` para cada paciente (novo ou existente)
- [ ] 4.5 (RED) Tests: `test_process_census_snapshot.py` com fixtures sintéticas de `CensusSnapshot`
- [ ] 4.6 **Gate S4**: `./scripts/test-in-container.sh check unit lint`
- [ ] 4.7 Gerar `/tmp/sirhosp-slice-CIS-S4-report.md`

## 5. Slice S5 — Worker: auto-enfileira `full_sync` da admissão mais recente

Escopo: modificar `_process_admissions_only` no worker para detectar a admissão mais recente e enfileirar extração de evoluções.

Limite: até **4 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S5.md`.

- [ ] 5.1 Modificar `_process_admissions_only()` em `process_ingestion_runs.py` — adicionar `_enqueue_most_recent_full_sync()`
- [ ] 5.2 (RED) Testes: `test_worker_auto_full_sync.py` — verificar que após `admissions_only` um novo `IngestionRun` com `intent="full_sync"` é criado
- [ ] 5.3 (RED) Teste: admissions_only sem admissões não enfileira full_sync
- [ ] 5.4 (RED) Teste: admission mais recente é escolhida corretamente entre múltiplas
- [ ] 5.5 **Gate S5**: `./scripts/test-in-container.sh check unit lint`
- [ ] 5.6 Gerar `/tmp/sirhosp-slice-CIS-S5-report.md`

## 6. Slice S6 — Página de leitos + merge_patients + admin action

Escopo: view `/beds/`, template, função `merge_patients()`, ação no Django Admin.

Limite: até **7 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S6.md`.

- [ ] 6.1 Criar `merge_patients(keep, merge)` em `apps/patients/services.py`
- [ ] 6.2 Adicionar ação admin "Merge selected patients" em `apps/patients/admin.py`
- [ ] 6.3 Criar `apps/census/views.py` com view `bed_status_view` (autenticada)
- [ ] 6.4 Criar `apps/census/urls.py` com rota `/beds/`
- [ ] 6.5 Criar template `census/bed_status.html` com tabela agrupada por setor
- [ ] 6.6 Incluir `census` URLs no `config/urls.py`
- [ ] 6.7 (RED) Tests: `test_merge_patients.py`, `test_bed_status_view.py`
- [ ] 6.8 **Gate S6**: `./scripts/test-in-container.sh check unit lint`
- [ ] 6.9 Gerar `/tmp/sirhosp-slice-CIS-S6-report.md`

## Stop Rule

- Implementar **um slice por vez**.
- Cada slice com ciclo TDD (red → green → refactor).
- Ao concluir um slice, parar e aguardar decisão explícita para o próximo.
- Relatório obrigatório em `/tmp/sirhosp-slice-S<ID>-report.md`.
