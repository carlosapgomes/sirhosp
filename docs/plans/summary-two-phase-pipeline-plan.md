# Plano de Arquitetura e UI/UX — Pipeline de Resumo em Duas Fases

## 1) Objetivo de produto

Manter simplicidade para o usuário ("gerar resumo"), com pipeline interno em 2 fases:

- **Fase 1 (canônica, fixa):** Mistral Large + prompt institucional fixo (`aps-s9-v1+`), foco em completude, cronologia e evidências.
- **Fase 2 (apresentação/reprocessamento):** transforma a saída da fase 1 em versões padrão ou customizada.

## 2) Fluxo funcional (visão do usuário)

### Entrada: página de internações do paciente

No card de resumo da internação:

- Botão principal: **Gerar resumo** (ou Atualizar/Regenerar).
- Clique abre página de configuração (wizard simples, sem expor termos técnicos de fase 1/fase 2):
  - **Tipo de saída (preset):** manter saída padrão em modo markdown (renderizar em um elemento com botão para copiar o conteúdo)
  - **LLM da versão final** (fase 2) com valor padrão.
  - **Prompt:** padrão (visualizável) ou customizado (textarea).
  - Opçao futura: ter mais de um prompt padrão com finalidades distintas

### Execução

Sistema enfileira job composto:

1. Executa fase 1 (sempre fixa).
2. Executa fase 2 com as preferências da tela.

Status para o usuário em linha única:

- Preparando base clínica
- Gerando versão final
- Concluído

### Resultado

Página de leitura exibe:

- resumo final (fase 2);
- selo: base clínica gerada em data/hora;
- ações: reprocessar com outro perfil (sem refazer parte cara, quando possível) e ver rastreabilidade/custos.

## 3) Arquitetura backend proposta

### 3.1 Entidades novas (mínimas)

1. **SummaryPipelineRun** (run pai)
   - admission, requested_by, mode, status global, started_at, finished_at, total_cost, currency.
2. **SummaryPipelineStepRun** (chamada por etapa)
   - pipeline_run FK.
   - step_type: `phase1_canonical` | `phase2_render`.
   - provider/model.
   - prompt_version.
   - prompt_text_snapshot.
   - request_payload_snapshot_hash (ou JSON redigido).
   - response_snapshot_hash (ou JSON redigido).
   - input_tokens, output_tokens, cached_tokens (se houver).
   - unit_cost_input, unit_cost_output, step_cost_total.
   - status, error_message, latency_ms.
3. **SummaryRenderProfile** (preset)
   - scope (system/user), name, description, default_model, default_prompt_template, active.

Observação: reaproveitar `SummaryRun`, `SummaryRunChunk`, `AdmissionSummaryState`, `AdmissionSummaryVersion`. A fase 1 continua gravando estado/versionamento como hoje.

### 3.2 Orquestração

- `SummaryRun` permanece como gatilho assíncrono (ou evoluir para fila dedicada depois).
- Worker executa:
  - Step A: fase 1 (chunked e robusta).
  - Step B: fase 2 (single-shot sobre estado consolidado da fase 1).
- Otimização opcional: permitir rerender de fase 2 sem recomputar fase 1 quando base canônica ainda estiver fresca.

### 3.3 Contratos

- **Fase 1 output:** contrato atual + `alertas_consistencia`.
- **Fase 2 input:**
  - `narrative_markdown` canônico;
  - `structured_state_json` canônico;
  - evidências e alertas da fase 1;
  - instruções do perfil/prompt custom.
- **Fase 2 output:** markdown final + metadados de transformação.

## 4) UI/UX proposta

### 4.1 Página de internações (origem)

- Mantém CTA atual, direcionando para tela de configuração do resumo.

### 4.2 Tela Configurar resumo

Blocos sugeridos:

1. Objetivo do resumo (presets).
2. Modelo da versão final (fase 2).
3. Prompt:
   - padrão (readonly com opção de visualizar);
   - customizado (textarea).
4. Custo estimado:
   - base clínica (fixa);
   - finalização (variável).
5. Botão: **Gerar resumo**.

### 4.3 Status

- Barra única de progresso com subtarefas:
  - Base clínica.
  - Versão final.
- Em falha: mensagem por etapa e retry da etapa final quando possível.

### 4.4 Leitura

Abas sugeridas:

- Resumo final.
- Rastreabilidade/custos.
- Base clínica (auditoria, opcional por permissão).

## 5) Rastreabilidade e custo

Registrar por chamada:

- usuário, admissão e run;
- fase (1/2);
- provider/model;
- prompt_version + snapshot do prompt;
- tokens entrada/saída;
- custo da chamada;
- duração;
- status/erro.

Agregações:

- custo total por pipeline run;
- custo por internação;
- custo por usuário/período;
- custo por perfil (Executivo/Jurídico/Qualidade/SANO).

## 6) Governança e segurança

- Prompt custom somente para perfis autorizados.
- Snapshot de prompt imutável para auditoria.
- Redação de payload sensível em logs.
- Limites operacionais:
  - tamanho máximo de prompt custom;
  - timeout e retries por fase;
  - rate limit por usuário.
- página de logs, acessível para qualquer usuário listando todos as execuções de sumario com data/hora, paciente, usuário, custo, etc (isso vai deixar claro para todos os usuários que o uso é monitorado)
- página de logs, acessível somente pelo administrador, dando acesso também aos prompts utilizados em cada chamada customizada, além dos dados de log públicos

## 7) Plano de implementação (slices sugeridos)

1. **Slice A:** modelos de pipeline/etapa/custo (sem UI).
2. **Slice B:** execução backend em 2 fases (fase 2 inicialmente com prompt padrão).
3. **Slice C:** tela de configuração (preset + modelo + prompt padrão/custom).
4. **Slice D:** rastreabilidade/custos na UI.
5. **Slice E:** otimização de rerender de fase 2 sem refazer fase 1.

## 8) Pontos para revisão/comentários

- Quais perfis podem usar prompt custom? todos os perfis
- Quais presets devem ser padrão no MVP? preciso env vars para configurar 3-4 LLMs opcionais e seus respectivos provedores e endpoints. Explique melhor o que vc inclui em um preset.
- Política de reuso da fase 1 (janela de validade). preferencialmente reutiliza-la sempre, desde que o período nao mudou (paciente ainda internado), ainda assim para paciente internado a gente poderia apenas atualizar o resultado da fase 1.
- Nível de detalhe visível na aba de rastreabilidade para cada perfil (data/hora, custo, usuário que solicitou,etc).
- Modelo padrão da fase 2 por preset (ou único inicialmente). precisamos de env vars para modelos 1-4 na fase 2 e env var para model padrão para a fase 1.
