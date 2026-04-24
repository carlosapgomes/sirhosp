<!-- markdownlint-disable MD013 -->
# Tasks: admission-first-missing-patient-flow

## Fase 1 — Fluxo portal admission-first para paciente ausente

### Slice S1 — Estado "não encontrado" com recuperação operacional

Escopo: ajustar `/patients/` para oferecer ação primária de sincronização de internações quando a busca não encontrar paciente local.

Limite: até **6 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S1.md`.

- [x] 1.1 (RED) Criar testes para estado vazio com query (`q`) exibindo CTA primária "Buscar/sincronizar internações".
- [x] 1.2 Implementar UI do estado vazio em `/patients/` com CTA primária e CTA secundária contextual.
- [x] 1.3 Garantir que CTA primária carregue o registro pesquisado como contexto para sincronização.
- [x] 1.4 **Gate obrigatório S1**:
  - `./scripts/test-in-container.sh check`
  - `docker compose -p sirhosp-test -f compose.yml -f compose.test.yml run --rm test-runner bash -lc "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q tests/unit/test_patient_list_view.py"`
  - `./scripts/test-in-container.sh lint`
- [x] 1.5 Gerar `/tmp/sirhosp-slice-AFMF-S1-report.md` com snippets before/after.

### Slice S2 — Sincronização de internações como operação explícita

Escopo: introduzir run admissions-only para descoberta/sincronização de internações sem extração de evoluções.

Limite: até **8 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S2.md`.

- [x] 2.1 (RED) Criar testes de integração HTTP/worker para run admissions-only (sucesso, falha e snapshot vazio).
- [x] 2.2 Implementar criação de run com intent operacional de sincronização de internações.
- [x] 2.3 Ajustar worker para processar admissions-only e persistir resultado observável sem extração de evoluções.
- [x] 2.4 Bloquear fluxo de extração quando resultado da sincronização for "sem internações".
- [x] 2.5 **Gate obrigatório S2**:
  - `./scripts/test-in-container.sh check`
  - `docker compose -p sirhosp-test -f compose.yml -f compose.test.yml run --rm test-runner bash -lc "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q tests/integration/test_ingestion_http.py tests/integration/test_worker_lifecycle.py"`
  - `./scripts/test-in-container.sh lint`
  - `./scripts/test-in-container.sh typecheck`
- [x] 2.6 Gerar `/tmp/sirhosp-slice-AFMF-S2-report.md` com snippets before/after.

## Fase 2 — Seleção de internação e sincronização dirigida

### Slice S3 — Seleção de internação com ação principal "sincronizar internação completa"

Escopo: após sincronização de internações bem-sucedida, conduzir usuário para seleção de internação e disparo de sincronização completa.

Limite: até **7 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S3.md`.

- [x] 3.1 (RED) Criar/ajustar testes para redirecionamento pós-sync e ação principal por internação.
- [x] 3.2 Implementar navegação pós-run para lista de admissões com CTA de sincronização completa por admissão.
- [x] 3.3 Implementar criação de run de sincronização completa com janela derivada de `admission_date` até `discharge_date`/hoje.
- [x] 3.4 Atualizar status run para exibir intent e contexto (registro/admissão/faixa efetiva).
- [x] 3.5 **Gate obrigatório S3**:
  - `./scripts/test-in-container.sh check`
  - `docker compose -p sirhosp-test -f compose.yml -f compose.test.yml run --rm test-runner bash -lc "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q tests/unit/test_navigation_views.py tests/integration/test_ingestion_http.py"`
  - `./scripts/test-in-container.sh lint`
- [x] 3.6 Gerar `/tmp/sirhosp-slice-AFMF-S3-report.md` com snippets before/after.

### Slice S4 — `/ingestao/criar/` como rota secundária contextual

Escopo: manter extração por período como opção secundária, pré-preenchida e validada dentro dos limites da internação selecionada.

Limite: até **8 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S4.md`.

- [x] 4.1 (RED) Criar testes para acesso contextual vs acesso solto em `/ingestao/criar/`.
- [x] 4.2 Implementar redirecionamento de acesso sem contexto válido para `/patients/` com mensagem orientativa.
- [x] 4.3 Implementar prefill de período baseado na internação selecionada e validação de faixa dentro da internação.
- [x] 4.4 Preservar criação de run por período como ação secundária contextual.
- [x] 4.5 **Gate obrigatório S4**:
  - `./scripts/test-in-container.sh check`
  - `docker compose -p sirhosp-test -f compose.yml -f compose.test.yml run --rm test-runner bash -lc "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q tests/integration/test_ingestion_http.py tests/unit/test_navigation_views.py"`
  - `./scripts/test-in-container.sh lint`
  - `./scripts/test-in-container.sh typecheck`
- [x] 4.6 Gerar `/tmp/sirhosp-slice-AFMF-S4-report.md` com snippets before/after.

## Fase 3 — Hardening operacional e regressão final

### Slice S5 — Contrato de chunking e aceite final da change

Escopo: consolidar contrato de fragmentação (<=15 dias por chunk), regressão completa e fechamento de artefatos.

Limite: até **6 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S5.md`.

- [x] 5.1 (RED) Criar/ajustar testes de chunking para períodos longos (incluindo >29 dias) garantindo chunks <=15 dias.
- [x] 5.2 Garantir que implementação do conector preserve chunking determinístico com sobreposição configurada.
- [x] 5.3 Executar regressão final de unit + integration + lint + typecheck.
- [x] 5.4 Atualizar `tasks.md` desta change com itens concluídos e gerar relatório final.
- [x] 5.5 **Gate obrigatório S5 (DoD da change)**:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
  - `./scripts/test-in-container.sh integration`
  - `./scripts/test-in-container.sh lint`
  - `./scripts/test-in-container.sh typecheck`
  - `./scripts/markdown-lint.sh` (se houver `.md` alterado)
- [x] 5.6 Gerar `/tmp/sirhosp-slice-AFMF-S5-report.md` com consolidação final.

## Stop Rule

- Implementar **um slice por vez**.
- Ao concluir um slice, parar e aguardar aprovação explícita para o próximo.
