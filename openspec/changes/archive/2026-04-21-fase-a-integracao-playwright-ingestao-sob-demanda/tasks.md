
# Tasks: fase-a-integracao-playwright-ingestao-sob-demanda

## 1. Slice S1 - Contrato do conector Playwright + adapter de transição

Escopo: definir porta de extração e implementação inicial encapsulando execução do fluxo `path2.py` com parse seguro do JSON.

Limite: até 8 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S1.md`.

- [x] 1.1 (TDD) Criar testes unitários do adapter para parsing/validação do contrato JSON de evoluções.
- [x] 1.2 Definir interface `EvolutionExtractorPort` no SirHosp.
- [x] 1.3 Implementar `PlaywrightEvolutionExtractor` em modo transição (subprocesso + JSON), consumindo `path2.py` do repositório `https://github.com/carlosapgomes/resumo-evolucoes-clinicas` clonado em `/tmp`.
- [x] 1.4 Mapear erros técnicos para exceções de domínio de ingestão.
- [x] 1.5 Executar validações do slice e gerar `/tmp/sirhosp-slice-S1-report.md`.

## 2. Slice S1.5 - Hardening de contrato do adapter (pré-S2)

Escopo: corrigir pontos críticos encontrados na revisão de S1 antes de iniciar orquestração assíncrona.

Limite: até 6 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S1-5.md`.

- [x] 2.1 (TDD) Criar teste falhando para garantir propagação de `patient_source_key` (a partir de `patient_record`) no payload normalizado do extractor.
- [x] 2.2 (TDD) Criar testes para compatibilidade de formato de data no adapter (`DD/MM/YYYY` para `path2.py`), aceitando entrada interna em `YYYY-MM-DD` com conversão explícita.
- [x] 2.3 (TDD) Criar testes de validação de campos obrigatórios por item extraído (`createdAt`, `content`, `createdBy`, `type`, `signatureLine`, `admissionKey`).
- [x] 2.4 Implementar correções mínimas no `PlaywrightEvolutionExtractor` sem ampliar escopo funcional.
- [x] 2.5 Atualizar documentação inline/docstrings do adapter conforme comportamento final.
- [x] 2.6 Executar validações do slice e gerar `/tmp/sirhosp-slice-S1-5-report.md`.

## 3. Slice S1.6 - Correção final de validação obrigatória (pré-S2)

Escopo: completar validação de campos obrigatórios do contrato do extractor conforme definido no S1.5.

Limite: até 4 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S1-6.md`.

- [x] 3.1 (TDD) Criar testes falhando para ausência/vazio de `createdBy` e `signatureLine`.
- [x] 3.2 Incluir `createdBy` e `signatureLine` na validação obrigatória de `_validate_item`.
- [x] 3.3 Garantir mensagens de erro com nomes dos campos faltantes.
- [x] 3.4 Executar validações do slice e gerar `/tmp/sirhosp-slice-S1-6-report.md`.

## 4. Slice S2 - Orquestração assíncrona de runs sob demanda

Escopo: criar fluxo operacional para enfileirar e processar `IngestionRun` pendentes sem Celery.

Limite: até 9 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S2.md`.

- [x] 4.1 (TDD) Criar teste de integração para transição de estados `queued -> running -> succeeded|failed`.
- [x] 4.2 Implementar comando worker para processar runs sob demanda pendentes.
- [x] 4.3 Integrar worker ao serviço de ingestão canônica existente.
- [x] 4.4 Persistir métricas operacionais mínimas da execução.
- [x] 4.5 Executar validações do slice e gerar `/tmp/sirhosp-slice-S2-report.md`.

## 5. Slice S2.1 - Sincronização de migração do status de IngestionRun

Escopo: corrigir pendência de schema detectada após S2 (`makemigrations --check`) sem ampliar escopo funcional.

Limite: até 4 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S2-1.md`.

- [x] 5.1 (Red) Demonstrar falha de consistência de migração com `uv run python manage.py makemigrations --check --dry-run`.
- [x] 5.2 Gerar migração de alteração de `IngestionRun.status` compatível com os novos estados (`queued`, `running`, `succeeded`, `failed`).
- [x] 5.3 Aplicar migrações localmente e validar que `makemigrations --check --dry-run` passa.
- [x] 5.4 Executar validações do slice e gerar `/tmp/sirhosp-slice-S2-1-report.md`.

## 6. Slice S3 - Política cache-first e lacunas temporais

Escopo: evitar extração redundante, disparando scraper apenas para períodos faltantes.

Limite: até 8 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S3.md`.

- [x] 6.1 (TDD) Criar testes para cálculo de cobertura temporal existente e detecção de lacunas.
- [x] 6.2 Implementar serviço de planejamento de janelas a extrair.
- [x] 6.3 Integrar planejamento ao worker de ingestão sob demanda.
- [x] 6.4 Registrar no `IngestionRun` quais lacunas foram processadas.
- [x] 6.5 Executar validações do slice e gerar `/tmp/sirhosp-slice-S3-report.md`.

## 7. Slice S4 - Superfície de produto para demo (trigger + status)

Escopo: disponibilizar interface mínima para disparo sob demanda e acompanhamento de status para reunião de negócio.

Limite: até 10 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S4.md`.

- [x] 7.1 (TDD) Criar teste de integração para fluxo HTTP de criação de run e consulta de status.
- [x] 7.2 Implementar endpoint/view para abrir run sob demanda (registro + período).
- [x] 7.3 Implementar endpoint/view de status com resumo operacional (estado, contagens, timestamps).
- [x] 7.4 Garantir mensagens amigáveis para sucesso, em processamento e falha.
- [x] 7.5 Executar quality gate relevante e gerar `/tmp/sirhosp-slice-S4-report.md`.

## 8. Slice S4.1 - Hardening de autenticação obrigatória

Escopo: corrigir exposição pública indevida dos endpoints de produto, exigindo autenticação para o fluxo sob demanda e consulta de status.

Limite: até 8 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S4-1.md`.

- [x] 8.1 (TDD) Criar testes falhando para acesso anônimo aos endpoints de ingestão (`create_run`, `run_status`) com expectativa de redirecionamento para login.
- [x] 8.2 Exigir autenticação nos endpoints de ingestão com `login_required` (ou mecanismo equivalente do Django) sem quebrar o fluxo autenticado.
- [x] 8.3 Atualizar testes HTTP existentes para autenticar usuário antes de validar os cenários de sucesso/erro.
- [x] 8.4 Manter `health/` público para observabilidade técnica.
- [x] 8.5 Executar validações do slice e gerar `/tmp/sirhosp-slice-S4-1-report.md`.

## 9. Slice S5 - Hardening documental e handoff para Fase B

Escopo: consolidar evidências da fase A e preparar backlog explícito para espelhamento periódico de internados.

Limite: até 6 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S5.md`.

- [x] 9.1 (TDD de regressão) Cobrir um caso de falha operacional realista do conector (timeout/JSON inválido).
- [x] 9.2 Sincronizar `proposal.md`, `design.md`, specs e estado implementado.
- [x] 9.3 Atualizar documentação de roadmap da Fase B sem expandir escopo de código.
- [x] 9.4 Executar quality gate completo (check, pytest, ruff, mypy, markdown-lint).
- [x] 9.5 Gerar `/tmp/sirhosp-slice-S5-report.md` com checklist final.
