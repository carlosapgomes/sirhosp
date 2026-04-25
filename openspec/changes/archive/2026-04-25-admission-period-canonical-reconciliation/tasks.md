<!-- markdownlint-disable MD013 -->
# Tasks: admission-period-canonical-reconciliation

## 1. Slice S1 - Reconciliação canônica por paciente+período

Escopo: impedir criação de novas admissões duplicadas quando `admission_key` externo variar entre runs para o mesmo paciente/período.

Limite: até **4 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S1.md`.

- [ ] 1.1 (RED) Adicionar testes unitários em `tests/unit/test_ingestion_service.py` para provar que mesma internação (mesmo período) não duplica quando `admission_key` muda.
- [ ] 1.2 (GREEN) Ajustar `upsert_admission_snapshot` em `apps/ingestion/services.py` para reconciliar por período quando não houver match confiável por chave de origem.
- [ ] 1.3 (REFACTOR) Limpeza mínima de helpers/nomes sem ampliar escopo.
- [ ] 1.4 **Gate obrigatório S1**:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
- [ ] 1.5 Gerar `/tmp/sirhosp-slice-APCR-S1-report.md` com snippets before/after por arquivo alterado.

## 2. Slice S2 - Consolidação de duplicatas existentes no upsert

Escopo: quando já houver múltiplas admissões do mesmo paciente/período, consolidar em uma canônica preservando eventos vinculados.

Limite: até **5 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S2.md`.

- [ ] 2.1 (RED) Adicionar testes unitários para cenário com duplicatas pré-existentes (mesmo período, chaves diferentes) validando merge determinístico e reapontamento de eventos.
- [ ] 2.2 (GREEN) Implementar consolidação no `upsert_admission_snapshot` (seleção canônica determinística + merge + delete duplicadas).
- [ ] 2.3 (REFACTOR) Minimizar duplicação de lógica sem alterar comportamento fora do slice.
- [ ] 2.4 **Gate obrigatório S2**:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
- [ ] 2.5 Gerar `/tmp/sirhosp-slice-APCR-S2-report.md` com snippets before/after por arquivo alterado.

## 3. Slice S3 - Regressão de lifecycle do worker para reruns com chave volátil

Escopo: garantir em integração que reruns (incluindo falha/sucesso subsequentes) não aumentam cardinalidade de admissões para o mesmo período.

Limite: até **4 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S3.md`.

- [ ] 3.1 (RED) Adicionar teste de integração em `tests/integration/test_worker_lifecycle.py` cobrindo dois snapshots do mesmo período com `admission_key` diferente e assert de `Admission.count()==1` para o paciente.
- [ ] 3.2 (GREEN) Ajustar implementação apenas se o novo teste expuser gap residual.
- [ ] 3.3 Atualizar artefatos OpenSpec do change se o comportamento final divergir do planejado.
- [ ] 3.4 **Gate obrigatório S3**:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh integration`
  - `./scripts/test-in-container.sh unit`
- [ ] 3.5 Gerar `/tmp/sirhosp-slice-APCR-S3-report.md` com snippets before/after por arquivo alterado.

## Stop Rule

- Implementar **um slice por vez**.
- Ao concluir um slice, parar e aguardar decisão explícita para o próximo.
