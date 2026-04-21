# Tasks: fundacao-modelo-eventos-e-ingestao-evolucoes

## 1. Slice S1 - Fundação de domínio (Patient, Admission, ClinicalEvent, IngestionRun)

Escopo: implementar núcleo de dados com migrações e testes de domínio.

Limite: até 8 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S1.md`.

- [x] 1.1 (TDD) Criar testes de modelo e constraints para unicidade de
  paciente e internação por chave externa.
- [x] 1.2 Implementar modelos iniciais com campos canônicos e relacionamentos.
- [x] 1.3 Implementar `PatientIdentifierHistory` já neste slice.
- [x] 1.4 Criar e aplicar migrações com `uv run python manage.py makemigrations`
  e `uv run python manage.py migrate`.
- [x] 1.5 Executar validações do slice e gerar
  `/tmp/sirhosp-slice-S1-report.md` com antes/depois dos arquivos alterados.

## 2. Slice S2 - Ingestão em memória + idempotência

Escopo: fluxo vertical de ingestão on-demand de evoluções sem arquivo de origem.

Limite: até 10 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S2.md`.

- [x] 2.1 (TDD) Criar testes para `event_identity_key`, `content_hash` e
  normalização de timezone.
- [x] 2.2 Implementar serviço de ingestão em memória com upsert de
  paciente/internação e persistência de evento.
- [x] 2.3 Implementar deduplicação por `event_identity_key + content_hash`.
- [x] 2.4 Implementar registro operacional em `IngestionRun`.
- [x] 2.5 Expor comando mínimo de execução do fluxo on-demand.
- [x] 2.6 Executar validações do slice e gerar
  `/tmp/sirhosp-slice-S2-report.md` com antes/depois dos arquivos alterados.

## 3. Slice S3 - Busca global FTS com filtros avançados (MVP)

Escopo: entregar busca textual global por conteúdo clínico com filtros
operacionais.

Limite: até 8 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S3.md`.

- [x] 3.1 (TDD) Criar testes para consulta FTS por relevância com filtros
  combinados.
- [x] 3.2 Implementar query/service de busca global em `content_text`.
- [x] 3.3 Implementar filtros por paciente, internação, período e tipo
  profissional.
- [x] 3.4 Expor endpoint/view inicial para busca global com payload de
  rastreabilidade (event_id, patient_id, admission_id, happened_at).
- [x] 3.5 Executar validações do slice e gerar
  `/tmp/sirhosp-slice-S3-report.md` com antes/depois dos arquivos alterados.

## 4. Slice S4 - Navegação de internação e timeline por cards

Escopo: navegação inicial de internações do paciente e timeline da internação
selecionada com filtros por tipo profissional.

Limite: até 10 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S4.md`.

- [x] 4.1 (TDD) Criar testes de integração para listagem de internações e
  timeline filtrada.
- [x] 4.2 Implementar view de lista de internações por paciente.
- [x] 4.3 Implementar view da timeline da internação com filtros por tipo
  profissional.
- [x] 4.4 Implementar template inicial mobile friendly em lista vertical de
  cards.
- [x] 4.5 Executar validações do slice e gerar
  `/tmp/sirhosp-slice-S4-report.md` com antes/depois dos arquivos alterados.

## 5. Slice S5 - Hardening, docs e evidências finais do change

Escopo: consolidar documentação técnica, ADR e evidências de qualidade para
encerramento do change.

Limite: até 6 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S5.md`.

- [x] 5.1 (TDD de regressão) Cobrir casos de borda identificados nos slices
  anteriores.
- [x] 5.2 Verificar sincronia de `design.md`, `proposal.md` e specs com o
  implementado; atualizar onde necessário.
- [x] 5.3 Registrar/atualizar ADR de modelagem canônica e reconciliação.
- [x] 5.4 Executar quality gate completo (check, pytest, ruff, mypy,
  markdown-lint).
- [x] 5.5 Gerar `/tmp/sirhosp-slice-S5-report.md` com antes/depois,
  evidências e checklist final para `/opsx:archive`.
