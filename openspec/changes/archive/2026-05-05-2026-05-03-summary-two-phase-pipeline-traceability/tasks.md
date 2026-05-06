# Tasks: summary-two-phase-pipeline-traceability

## Convenções desta change

- Prefixo de slice: `STP` (Summary Two-Phase Pipeline).
- Execução: 1 slice por vez, com TDD (`red -> green -> refactor`).
- Relatório obrigatório por slice em `/tmp/sirhosp-slice-STP-SX-report.md`.
- Se exceder escopo do slice, parar e reportar bloqueio.

## Slice STP-S1 — Modelo de dados de pipeline e rastreabilidade

**Objetivo vertical:** persistir run pai e etapas por fase com custo em USD e
snapshots de prompt/payload.

**Escopo máximo:** 5 arquivos.

- [ ] S1.1 (RED) Criar `tests/unit/test_summary_pipeline_models.py` cobrindo:
  - criação de `SummaryPipelineRun`;
  - criação de `SummaryPipelineStepRun` por fase;
  - custo total = custo fase1 + custo fase2;
  - `currency` padrão em USD.
- [ ] S1.2 Implementar modelos em `apps/summaries/models.py`:
  - `SummaryPipelineRun`
  - `SummaryPipelineStepRun`
- [ ] S1.3 Criar migração correspondente em `apps/summaries/migrations/`.
- [ ] S1.4 Registrar modelos no admin (`apps/summaries/admin.py`).
- [ ] S1.5 Gate STP-S1:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
  - `./scripts/test-in-container.sh lint`
  - `./scripts/test-in-container.sh typecheck`
- [ ] S1.6 Gerar `/tmp/sirhosp-slice-STP-S1-report.md`.

## Slice STP-S2 — Prompts padrão em arquivo (fase 1 e fase 2)

**Objetivo vertical:** externalizar prompts padrão para arquivos versionados e
fornecer loader tipado com falha explícita.

**Escopo máximo:** 5 arquivos.

- [ ] S2.1 (RED) Criar `tests/unit/test_summary_prompt_loader.py` cobrindo:
  - carregamento do prompt padrão da fase 1 por arquivo;
  - carregamento do prompt padrão da fase 2 por arquivo;
  - falha explícita quando arquivo obrigatório não existir.
- [ ] S2.2 Implementar `apps/summaries/prompt_loader.py`.
- [ ] S2.3 Criar arquivos versionados:
  - `apps/summaries/prompts/phase1_canonical_v1.md`
  - `apps/summaries/prompts/phase2_default_v1.md`
- [ ] S2.4 Ajustar gateway para consumir prompts carregados por arquivo.
- [ ] S2.5 Gate STP-S2:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
  - `./scripts/test-in-container.sh lint`
- [ ] S2.6 Gerar `/tmp/sirhosp-slice-STP-S2-report.md`.

## Slice STP-S3 — Config LLM por env (fase 1 fixa + fase 2 opções)

**Objetivo vertical:** carregar modelos/credenciais de LLM por env, incluindo
novas envs de câmbio.

**Escopo máximo:** 5 arquivos.

- [ ] S3.1 (RED) Criar `tests/unit/test_summary_llm_env_config.py` cobrindo:
  - leitura obrigatória de fase 1;
  - leitura de até 4 opções de fase 2;
  - exibição apenas de opções habilitadas.
- [ ] S3.2 Implementar `apps/summaries/llm_config.py`.
- [ ] S3.3 Atualizar `.env.example` e `.env.docker.example` com:
  - `SUMMARY_PHASE1_*`
  - `SUMMARY_PHASE2_OPTION_N_*`
  - `SUMMARY_EXCHANGE_*` (incluindo
    `SUMMARY_EXCHANGE_FALLBACK_API_KEY`)
- [ ] S3.4 Ajustar gateway/orquestrador para consumir config centralizada.
- [ ] S3.5 Gate STP-S3:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
  - `./scripts/test-in-container.sh lint`
- [ ] S3.6 Gerar `/tmp/sirhosp-slice-STP-S3-report.md`.

## Slice STP-S4 — Câmbio USD/BRL (modelo + command diário)

**Objetivo vertical:** coletar cotação diária USD/BRL com primária sem API key
(`frankfurter.dev`) e fallback com API key (`exchangerate-api.com`).

**Escopo máximo:** 5 arquivos.

- [ ] S4.1 (RED) Criar `tests/unit/test_exchange_rate_sync_command.py` cobrindo:
  - sucesso via `frankfurter.dev`;
  - fallback para `exchangerate-api.com` em falha da primária;
  - fallback só executa com
    `SUMMARY_EXCHANGE_FALLBACK_API_KEY` configurada;
  - persistência/atualização da cotação do dia;
  - retenção de ao menos 2 últimas cotações válidas.
- [ ] S4.2 Implementar modelo `ExchangeRateSnapshot` + migração.
- [ ] S4.3 Implementar command `sync_exchange_rates`.
- [ ] S4.4 Implementar utilitário para obter cotação mais recente disponível.
- [ ] S4.5 Gate STP-S4:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
  - `./scripts/test-in-container.sh lint`
  - `./scripts/test-in-container.sh typecheck`
- [ ] S4.6 Gerar `/tmp/sirhosp-slice-STP-S4-report.md`.

## Slice STP-S5 — Biblioteca de prompts (modelo + CRUD + permissões)

**Objetivo vertical:** permitir CRUD de prompts customizados com título e
visibilidade público/privado.

**Escopo máximo:** 5 arquivos.

- [ ] S5.1 (RED) Criar `tests/integration/test_user_prompt_templates_http.py`:
  - criar prompt com título obrigatório;
  - listar prompts próprios + públicos;
  - editar/apagar apenas prompt próprio;
  - bloquear edição/apagamento de prompt de terceiro.
- [ ] S5.2 Implementar modelo `UserPromptTemplate` + migração.
- [ ] S5.3 Implementar views/urls/templates de CRUD em `apps/summaries/`.
- [ ] S5.4 Aplicar controle de acesso por ownership.
- [ ] S5.5 Gate STP-S5:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh integration`
  - `./scripts/test-in-container.sh lint`
- [ ] S5.6 Gerar `/tmp/sirhosp-slice-STP-S5-report.md`.

## Slice STP-S6 — Orquestração duas fases + persistência de trilha

**Objetivo vertical:** executar fase 1/2 com reuso, registrar step runs e
custos em USD.

**Escopo máximo:** 5 arquivos.

- [ ] S6.1 (RED) Criar `tests/integration/test_summary_two_phase_orchestration.py`:
  - run completo fase1+fase2;
  - reuso completo fase1 => step `skipped` e custo fase1 = 0;
  - internação aberta com novos eventos => update incremental fase1;
  - snapshot textual de prompt salvo no step run.
- [ ] S6.2 Implementar orquestrador em `apps/summaries/services.py`.
- [ ] S6.3 Integrar worker `process_summary_runs` ao novo orquestrador.
- [ ] S6.4 Persistir `SummaryPipelineStepRun` com prompt/payload/response.
- [ ] S6.5 Gate STP-S6:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh integration`
  - `./scripts/test-in-container.sh lint`
- [ ] S6.6 Gerar `/tmp/sirhosp-slice-STP-S6-report.md`.

## Slice STP-S7 — UI de configuração de resumo (origem: internações)

**Objetivo vertical:** escolher LLM fase 2 e prompt (padrão/custom/salvo) antes
de enfileirar.

**Escopo máximo:** 5 arquivos.

- [ ] S7.1 (RED) Criar `tests/integration/test_summary_config_http.py` cobrindo:
  - acesso autenticado;
  - opções LLM habilitadas;
  - seletor com prompt padrão + customizados disponíveis;
  - POST com prompt padrão;
  - POST com prompt custom;
  - POST com `salvar_prompt=true` exige título e persiste prompt.
- [ ] S7.2 Implementar view/URL/template de configuração em `apps/summaries/`.
- [ ] S7.3 Integrar seleção de prompt salvo e criação inline de prompt novo.
- [ ] S7.4 Ajustar CTA da página de internações para abrir configuração.
- [ ] S7.5 Gate STP-S7:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh integration`
  - `./scripts/test-in-container.sh lint`
- [ ] S7.6 Gerar `/tmp/sirhosp-slice-STP-S7-report.md`.

## Slice STP-S8 — Logs públicos/admin com USD + BRL

**Objetivo vertical:** transparência operacional para todos e detalhe sensível
para admin, com conversão monetária em BRL.

**Escopo máximo:** 5 arquivos.

- [ ] S8.1 (RED) Criar `tests/integration/test_summary_logs_http.py` cobrindo:
  - logs públicos mostram fase/status/modelo/custo USD e BRL;
  - BRL usa cotação mais recente disponível;
  - logs admin exigem staff/superuser;
  - logs admin exibem prompt/payload/response completos.
- [ ] S8.2 Implementar views/urls/templates de logs em `apps/summaries/`.
- [ ] S8.3 Aplicar controle de acesso por perfil.
- [ ] S8.4 Incluir links de navegação para logs públicos/admin.
- [ ] S8.5 Gate STP-S8:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh integration`
  - `./scripts/test-in-container.sh lint`
- [ ] S8.6 Gerar `/tmp/sirhosp-slice-STP-S8-report.md`.

## Slice STP-S9 — Status/leitura com custos por fase + hardening final

**Objetivo vertical:** exibir custos em USD/BRL no status e leitura, e fechar
com validação final da change.

**Escopo máximo:** 5 arquivos.

- [x] S9.1 (RED) Criar `tests/integration/test_summary_cost_visibility_http.py`:
  - status mostra custo por fase em USD e BRL;
  - leitura mostra custo total e flag de reuso da fase 1;
  - fallback para última cotação disponível.
- [x] S9.2 Atualizar templates de status/leitura e contexto das views.
- [x] S9.3 Garantir fallback quando custos/tokens/cotação não existirem.
- [x] S9.4 Rodar gate final:
  - `./scripts/test-in-container.sh quality-gate`
  - `./scripts/markdown-lint.sh`
- [x] S9.5 Gerar `/tmp/sirhosp-slice-STP-S9-report.md`.

## Stop Rule

- Implementar apenas o slice atual.
- Parar ao final e aguardar validação humana.
- Não avançar sem relatório completo + gates verdes.
