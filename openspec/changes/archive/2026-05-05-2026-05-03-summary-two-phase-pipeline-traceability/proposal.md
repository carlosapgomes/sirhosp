# Change Proposal: summary-two-phase-pipeline-traceability

## Why

O resumo progressivo atual já gera boa base clínica, mas precisa evoluir para:

1. separar custo pesado (base canônica) de custo flexível (apresentação final);
2. permitir reprocessamento de saída para diferentes usos com prompt custom;
3. garantir rastreabilidade completa de chamadas LLM e custos por fase/run;
4. tornar o uso transparente para todos os usuários via página pública de logs.

Sem essa evolução, o custo por resumo cresce desnecessariamente, a adaptação para
públicos distintos fica limitada, e a governança financeira/auditável fica
incompleta.

## What Changes

1. Introduzir pipeline de resumo em duas fases:
   - **Fase 1 canônica (fixa):** modelo padrão via env, prompt institucional
     fixo em arquivo versionado no repositório, persistência de estado
     estruturado e narrativa base.
   - **Fase 2 de renderização (configurável):** modelo opcional (1..4 via env)
     e prompt padrão em arquivo versionado ou prompt customizado por usuário.
2. Criar rastreabilidade por execução e por fase/chamada, com:
   - usuário solicitante;
   - provider/model/endpoint lógico;
   - prompt/versionamento e snapshots de entrada/saída;
   - tokens e custo por fase;
   - custo total por run;
   - armazenamento do conteúdo de prompt efetivamente usado (snapshot textual),
     sem dependência de referência a prompt salvo.
3. Permitir reuso da fase 1:
   - se período/cutoff não mudou, custo da fase 1 = 0 (reuso completo);
   - se paciente segue internado com novos eventos, atualizar fase 1
     incrementalmente e reexecutar fase 2.
4. Implementar tela de configuração de resumo (origem: página de internações):
   - saída padrão markdown;
   - seleção de LLM da fase 2 entre opções configuradas;
   - prompt padrão visualizável ou prompt custom (todos perfis).
5. Implementar logs com duas visões:
   - **Pública (todos usuários autenticados):** data/hora, paciente, usuário,
     fase, modelo, status, custo.
   - **Admin:** tudo da pública + prompts e payloads/respostas completos.
6. Criar biblioteca de prompts customizados por usuário:
   - salvar prompt com título obrigatório;
   - marcar prompt como público ou privado;
   - reutilizar prompts salvos em novas sessões;
   - oferecer CRUD (listar, visualizar, editar, apagar) com controle de acesso.
7. Padronizar custos financeiros:
   - persistir custo bruto das execuções em USD;
   - converter para BRL apenas na apresentação ao usuário;
   - obter cotação USD/BRL diária por command com fonte primária e fallback;
   - configurar API key por env apenas para fallback (`exchangerate-api.com`),
     mantendo fonte primária (`frankfurter.dev`) sem autenticação.

## Scope / Non-Goals / Risks

### Scope

- Evolução da sumarização para pipeline 2 fases.
- Configuração de até 4 opções de LLM para fase 2 por env, cada uma com
  endpoint e API key próprios.
- Modelo padrão de fase 1 por env.
- Persistência completa de logs/snapshots de chamadas LLM.
- Prompts padrão da fase 1 e fase 2 versionados em arquivos no repositório.
- Biblioteca de prompts customizados com título e visibilidade público/privado.
- UI de configuração, CRUD de prompts e UI de logs públicos/admin.
- Persistência de custos em USD com conversão para BRL em tempo de exibição.
- Coleta diária de cotação USD/BRL com fallback de provedor.
- Configuração por env da API key do fallback de câmbio
  (`SUMMARY_EXCHANGE_FALLBACK_API_KEY`).

### Non-Goals

- Não alterar o princípio de execução assíncrona com PostgreSQL (sem Celery).
- Não liberar endpoint/modelo arbitrário digitável pelo usuário no MVP.
- Não anonimizar dados de paciente na página pública interna (decisão atual).
- Não impor política de retenção/expurgo nesta primeira entrega.

### Main Risks

- Armazenar payload/resposta completos aumenta volume de dados sensíveis.
- Prompt custom para todos os perfis pode elevar variabilidade de qualidade.
- Estimativa/precificação por provider pode divergir sem tabela versionada.
- Falha/instabilidade de provedores de câmbio pode afetar exibição em BRL.
- Prompts públicos podem disseminar instruções de baixa qualidade sem curadoria.

## Capabilities

### Added Capabilities

- `summary-llm-traceability`: trilha completa por fase/chamada com custos,
  prompts e snapshots.
- `summary-prompt-library`: catálogo de prompts customizados com título,
  visibilidade e reutilização.
- `usd-brl-exchange-rates`: coleta e consulta operacional de câmbio para
  apresentação de custos em BRL.

### Modified Capabilities

- `admission-progressive-summary`: passa a operar em duas fases com reuso da
  fase canônica e renderização configurável.
- `services-portal-navigation`: adiciona fluxo de configuração de resumo e
  páginas de logs de sumarização.

## Impact

- `apps/summaries/`: modelos, serviços de orquestração, worker, gateway,
  views/templates de configuração, CRUD de prompts e logs.
- `apps/summaries/prompts/`: prompts padrão versionados da fase 1 e fase 2.
- `apps/summaries/management/commands/`: command de sincronização cambial.
- `config/settings.py` / envs: catálogo de modelos fase 2 e modelo padrão fase 1.
- `apps/patients/`: CTA de resumo direcionando para configuração.
- Testes unitários/integrados para reuso de fase 1, prompt library, custos e
  visões de log.
