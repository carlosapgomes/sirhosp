<!-- markdownlint-disable MD013 -->

# Tasks: admission-period-representation

## Fase 1 — Núcleo de ingestão e associação

### Slice S1 — Captura de snapshot de internações no conector/extractor

Escopo: capturar e exportar lista de internações conhecidas no fluxo Playwright, com contrato consumível pelo extractor Django.

Limite: até **7 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S1.md`.

- [x] 1.1 (RED) Criar testes de extractor para leitura/normalização de snapshot de internações.
- [x] 1.2 Estender `path2.py` para produzir artefato de internações conhecidas do paciente.
- [x] 1.3 Estender `PlaywrightEvolutionExtractor` para carregar snapshot de internações em método explícito (sem quebrar API atual de evoluções).
- [x] 1.4 Garantir comportamento determinístico para snapshot vazio/ausente com erro claro.
- [x] 1.5 **Gate obrigatório S1**:
  - `uv run python manage.py check`
  - `uv run pytest -q tests/unit/test_evolution_extractor.py`
  - `uv run ruff check config apps tests manage.py`
- [x] 1.6 Gerar `/tmp/sirhosp-slice-APR-S1-report.md` com snippets before/after.

### Slice S2 — Persistência de internações + fallback determinístico evento->internação

Escopo: persistir catálogo de internações e resolver associação de evoluções com fallback determinístico por `happened_at`.

Limite: até **8 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S2.md`.

- [x] 2.1 (RED) Criar testes para:
  - upsert de internações com campos de período;
  - política de atualização de `ward/bed` (somente non-empty);
  - fallback determinístico de associação por período.
- [x] 2.2 Implementar serviço de upsert de snapshot de internações.
- [x] 2.3 Implementar resolvedor determinístico de admissão para evoluções sem chave válida.
- [x] 2.4 Garantir ingestão canônica com `admission_date/discharge_date` corretamente persistidos quando disponíveis.
- [x] 2.5 **Gate obrigatório S2**:
  - `uv run python manage.py check`
  - `uv run pytest -q tests/unit/test_ingestion_service.py tests/unit/test_regression_edge_cases.py`
  - `uv run ruff check config apps tests manage.py`
- [x] 2.6 Gerar `/tmp/sirhosp-slice-APR-S2-report.md` com snippets before/after.

### Slice S3 — Worker: semântica de falha + métricas de internações no run

Escopo: aplicar regras operacionais confirmadas (falha em capture, persistência parcial, métricas no status de run).

Limite: até **8 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S3.md`.

- [x] 3.1 (RED) Criar testes de lifecycle do worker para os cenários:
  - falha na captura de internações => run failed;
  - captura ok + falha nas evoluções => internações persistidas + run failed;
  - captura ok + 0 evoluções => run succeeded.
- [x] 3.2 Adicionar campos de observabilidade em `IngestionRun` (`admissions_seen/created/updated`) + migration.
- [x] 3.3 Ajustar worker para etapa explícita de captura/persistência de internações antes da extração de evoluções.
- [x] 3.4 Atualizar tela de status para exibir métricas de internações.
- [x] 3.5 **Gate obrigatório S3**:
  - `uv run python manage.py check`
  - `uv run pytest -q tests/integration/test_worker_lifecycle.py tests/integration/test_worker_gap_planning.py tests/integration/test_ingestion_http.py`
  - `uv run ruff check config apps tests manage.py`
  - `uv run mypy config apps tests manage.py`
- [x] 3.6 Gerar `/tmp/sirhosp-slice-APR-S3-report.md` com snippets before/after.

## Fase 2 — Representação no portal

### Slice S4 — Cobertura de internações no portal (pacientes + admissões)

Escopo: mostrar claramente internações conhecidas, internações com eventos e status "Sem eventos extraídos".

Limite: até **7 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S4.md`.

- [x] 4.1 (RED) Criar/ajustar testes para resumo de cobertura na lista de pacientes e badge de admissão sem eventos.
- [x] 4.2 Implementar anotações/queries para contadores por paciente.
- [x] 4.3 Atualizar templates `patient_list` e `admission_list` com os novos elementos visuais.
- [x] 4.4 **Gate obrigatório S4**:
  - `uv run python manage.py check`
  - `uv run pytest -q tests/unit/test_patient_list_view.py tests/unit/test_navigation_views.py`
  - `uv run ruff check config apps tests manage.py`
- [x] 4.5 Gerar `/tmp/sirhosp-slice-APR-S4-report.md` com snippets before/after.

## Fase 3 — Hardening final e aceite de change

### Slice S5 — Regressão completa + artefatos finais

Escopo: validação final end-to-end da change, atualização de tarefas e relatório de fechamento.

Limite: até **5 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S5.md`.

- [x] 5.1 Rodar suite completa e quality gates finais.
- [x] 5.2 Ajustar testes/documentação residuais sem ampliar escopo funcional.
- [x] 5.3 Atualizar este `tasks.md` marcando itens concluídos.
- [x] 5.4 **Gate obrigatório S5 (DoD do change)**:
  - `uv run python manage.py check`
  - `uv run pytest -q`
  - `uv run ruff check config apps tests manage.py`
  - `uv run mypy config apps tests manage.py`
  - `./scripts/markdown-lint.sh` (se houver `.md` alterado)
- [x] 5.5 Gerar `/tmp/sirhosp-slice-APR-S5-report.md` com consolidação final.

## Regras gerais de execução

- Executar em branch separada: **`feature/admission-period-representation`**.
- Um slice por vez; parar ao final de cada slice.
- Próximo slice só após aceite explícito do relatório pelo revisor.
