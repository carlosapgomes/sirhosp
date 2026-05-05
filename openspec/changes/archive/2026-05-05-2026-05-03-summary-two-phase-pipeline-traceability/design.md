# Design: summary-two-phase-pipeline-traceability

## Context

A sumarização atual é progressiva por chunks e grava estado/versionamento
canônico, mas opera como uma única etapa de geração. O produto precisa separar
explicitamente:

- base clínica canônica de alta fidelidade (fase 1);
- versão final de consumo (fase 2), ajustável por modelo/prompt.

Além disso, há necessidade de governança de custo com rastreabilidade completa
por execução/fase/chamada, mantendo UX simples na página de internações.

## Goals / Non-Goals

### Goals

- Implementar pipeline de duas fases com reuso da fase 1.
- Permitir prompt custom para todos os usuários autenticados na fase 2.
- Disponibilizar até 4 opções configuráveis de LLM para fase 2 via env.
- Registrar logs completos (inclusive payload/resposta) para análise futura.
- Exibir logs operacionais para todos usuários e visão sensível para admin.
- Disponibilizar biblioteca de prompts com título e visibilidade público/privado.
- Persistir custos em USD e converter para BRL com cotação operacional.
- Externalizar prompts padrão (fase 1 e fase 2) para arquivos versionados.

### Non-Goals

- Sem endpoint/modelo livre digitável no MVP.
- Sem política de retenção/expurgo nesta change.
- Sem mudança de arquitetura assíncrona (continua worker com PostgreSQL).

## Domain Model

## 1) SummaryPipelineRun (run pai)

Representa uma solicitação de resumo em duas fases.

Campos principais:

- `admission` (FK)
- `requested_by` (FK user)
- `mode` (`generate`, `update`, `regenerate`)
- `status` (`queued`, `running`, `succeeded`, `partial`, `failed`)
- `phase1_reused` (bool)
- `phase1_cost_total` (decimal)
- `phase2_cost_total` (decimal)
- `total_cost` (decimal)
- `currency` (default `USD`)
- `started_at`, `finished_at`, `error_message`

## 2) SummaryPipelineStepRun (fase/chamada)

Registro auditável por etapa do pipeline.

Campos principais:

- `pipeline_run` (FK)
- `step_type` (`phase1_canonical`, `phase2_render`)
- `status` (`running`, `succeeded`, `failed`, `skipped`)
- `provider_name`, `model_name`, `base_url`
- `prompt_version`
- `prompt_text_snapshot` (texto completo; sempre snapshot imutável)
- `request_payload_json` (JSON completo)
- `response_payload_json` (JSON completo)
- `input_tokens`, `output_tokens`, `cached_tokens`
- `cost_input`, `cost_output`, `cost_total` (sempre em USD)
- `latency_ms`, `error_message`
- `started_at`, `finished_at`

Observação: manter `AdmissionSummaryState` e `AdmissionSummaryVersion` como
fonte canônica da fase 1.

## 3) UserPromptTemplate (biblioteca de prompts)

Catálogo de prompts reutilizáveis para fase 2.

Campos principais:

- `owner` (FK user)
- `title` (obrigatório)
- `content` (texto completo)
- `is_public` (bool)
- `created_at`, `updated_at`

Regras:

- Usuário sempre pode CRUD dos próprios prompts.
- Prompt público de terceiros é visível para seleção, mas não editável/apagável
  por quem não é owner.
- Execução nunca salva FK para `UserPromptTemplate`; salva apenas
  `prompt_text_snapshot` no step run.

## 4) ExchangeRateSnapshot (USD/BRL)

Armazena cotações operacionais para conversão de custo na UI.

Campos principais:

- `base_currency` (fixo `USD`)
- `quote_currency` (fixo `BRL`)
- `rate` (decimal)
- `reference_date` (data da cotação)
- `provider` (ex.: `frankfurter`, `exchangerate_api`)
- `fetched_at`

Regras:

- Command diário faz upsert da cotação do dia.
- Deve preservar ao menos as 2 últimas cotações válidas.
- Conversão na UI usa sempre a cotação mais recente disponível.
- Fonte primária: `frankfurter.dev` (sem API key).
- Fallback: `exchangerate-api.com` (requer API key via env).

## 5) SummaryRun (integração)

`SummaryRun` continua como mecanismo de fila já integrado à UI atual.
A execução do worker passa a delegar para orquestrador em duas fases.

## 6) Prompt defaults storage strategy

Prompts padrão institucionais não serão salvos em banco de dados. Serão
versionados em arquivos no repositório para revisão via Git/PR e
rastreabilidade de mudanças.

Arquivos previstos:

- `apps/summaries/prompts/phase1_canonical_v1.md`
- `apps/summaries/prompts/phase2_default_v1.md`

Regras:

- fase 1 sempre lê prompt padrão do arquivo de fase 1;
- fase 2 em modo padrão lê prompt do arquivo de fase 2;
- prompt custom de usuário continua no banco (`UserPromptTemplate`);
- execução sempre salva `prompt_text_snapshot` no step run.

## LLM Configuration via Environment

## Fase 1 (fixa)

- `SUMMARY_PHASE1_PROVIDER`
- `SUMMARY_PHASE1_MODEL`
- `SUMMARY_PHASE1_BASE_URL`
- `SUMMARY_PHASE1_API_KEY`

## Fase 2 (opções 1..4)

Para cada opção `N` em `1..4`:

- `SUMMARY_PHASE2_OPTION_N_LABEL`
- `SUMMARY_PHASE2_OPTION_N_PROVIDER`
- `SUMMARY_PHASE2_OPTION_N_MODEL`
- `SUMMARY_PHASE2_OPTION_N_BASE_URL`
- `SUMMARY_PHASE2_OPTION_N_API_KEY`
- `SUMMARY_PHASE2_OPTION_N_ENABLED`

A UI mostra apenas opções com `ENABLED=true`.

## Exchange Rate Configuration via Environment

- `SUMMARY_EXCHANGE_PRIMARY_URL` (default: endpoint do `frankfurter.dev`)
- `SUMMARY_EXCHANGE_FALLBACK_URL` (endpoint do `exchangerate-api.com`)
- `SUMMARY_EXCHANGE_FALLBACK_API_KEY` (obrigatória para uso do fallback)

Regras:

- primária (`frankfurter.dev`) não usa API key;
- fallback só é tentado quando `SUMMARY_EXCHANGE_FALLBACK_API_KEY` estiver
  configurada;
- sem API key do fallback, command segue com primária e, em falha, usa última
  cotação persistida.

## Orchestration

## Regra de execução

1. Criar `SummaryPipelineRun` ao disparo do usuário.
2. Avaliar reuso da fase 1:
   - **reuso completo**: período/cutoff equivalentes ao já consolidado;
   - **update incremental**: internação aberta com novos eventos;
   - **recompute**: generate/regenerate.
3. Executar fase 1 (ou marcar `skipped` com custo zero).
4. Executar fase 2 usando:
   - estado/narrativa canônica da fase 1;
   - prompt padrão ou custom do usuário;
   - opção LLM escolhida na tela.
5. Persistir custos por fase e total.

## Custos

- custo persistido no banco é sempre em USD (`currency='USD'`);
- custo é exibido por fase (`phase1_cost_total`, `phase2_cost_total`);
- quando fase 1 for reusada integralmente, custo da fase 1 = 0;
- UI converte USD->BRL usando a cotação mais recente disponível no momento da
  visualização (não a cotação histórica do dia do run).

## UI/UX

## 1) Origem: página de internações

CTA de resumo passa a abrir tela de configuração antes de enfileirar.

## 2) Tela Configurar resumo

Campos mínimos:

- LLM da fase 2 (dropdown com opções configuradas)
- Prompt mode (`padrão` | `custom`)
- Fonte do prompt custom:
  - selecionar prompt salvo (público/privado conforme permissões), ou
  - digitar novo prompt
- Ao digitar novo prompt: checkbox `Salvar prompt` + campo `Título`
  (obrigatório) + checkbox `Tornar público`
- Prompt custom (textarea, quando selecionado)
- Preview textual: saída em Markdown
- Botão `Gerar resumo`

Nota: MVP com "saída padrão" e "custom"; sem múltiplos perfis semânticos.

## 3) Status do run

Manter página de status única com subtarefas:

- Base clínica
- Versão final

## 4) Leitura

Manter leitura em Markdown renderizado com botão de cópia.

## 5) Logs

### Logs públicos (todos autenticados)

Listar:

- data/hora
- paciente/internação
- usuário solicitante
- fase
- provider/model
- status
- custo por fase (USD)
- custo convertido para BRL (cotação mais recente)

### Logs admin

Tudo da visão pública +

- prompt completo por chamada
- request/response completos

## 6) CRUD de prompts

Página dedicada para usuários autenticados:

- listar prompts próprios e públicos;
- criar prompt (título + conteúdo + visibilidade);
- editar/apagar apenas prompts próprios;
- visualizar detalhes de prompt antes de usar.

## Segurança e governança

- Prompt custom permitido para todos perfis (decisão de produto).
- Snapshot imutável dos prompts e payloads para auditoria.
- Logs detalhados com acesso restrito a admin na camada sensível.

## Validation Strategy

- Unit tests:
  - decisão de reuso da fase 1;
  - parser de opções LLM por env;
  - carregamento de prompts padrão a partir de arquivos versionados;
  - cálculo de custo por fase/total em USD;
  - fallback de conversão USD->BRL com última cotação válida;
  - leitura de env de câmbio incluindo API key obrigatória para fallback;
  - regras de visibilidade e ownership de prompts;
  - permissões de logs público/admin.
- Integration tests:
  - fluxo completo configuração -> fila -> fase 1/2 -> leitura;
  - cenário com reuso completo da fase 1 (custo zero);
  - salvar prompt custom e reutilizar em nova sessão;
  - CRUD de prompts por usuário com controle de acesso;
  - visões de log conforme perfil e exibição em BRL.

## Rollout

1. Adicionar migrações dos novos modelos.
2. Configurar envs de fase 1 e fase 2.
3. Criar/publicar arquivos de prompt padrão da fase 1 e fase 2.
4. Configurar envs de câmbio (incluindo
   `SUMMARY_EXCHANGE_FALLBACK_API_KEY`).
5. Ativar fluxo novo de configuração de resumo.
6. Ativar CRUD de prompts customizados.
7. Agendar command diário de cotação USD/BRL.
8. Ativar páginas de logs público/admin com conversão para BRL.
