# run-status-progress-feedback

## Why

Hoje a página de status de sincronização (`run_status.html`) só mostra
"Em execução..." com um spinner durante todo o processamento, que pode durar
de 30 segundos a 5 minutos. O operador não sabe se o sistema travou, em qual
etapa está, ou quanto falta. Isso gera ansiedade operacional e tentativas de
recarregar/reiniciar desnecessárias.

O projeto já coleta métricas de estágio (`IngestionRunStageMetric`) para cada
execução — com timestamps, status e detalhes — mas esses dados não são expostos
na interface. O meta-refresh a cada 5 segundos também é uma técnica rudimentar
que recarrega a página inteira.

Esta change implementa feedback intermediário de progresso usando HTMX polling,
substituindo o meta-refresh por atualização parcial da seção de progresso com
visibilidade de estágio atual, estágios concluídos e tempos de execução.

## What Changes

- **Nova view** `run_status_fragment`: endpoint que retorna fragmento HTML com
  estágios de progresso do run, para polling via HTMX.
- **Novo template parcial** `_run_progress.html`: exibe estágios com badges
  de status (concluído, em andamento, pendente, falhou) e durações.
- **Template `run_status.html` atualizado**: substitui `<meta refresh>` por
  HTMX `hx-get` com `hx-trigger="every 3s"` que atualiza apenas a seção de
  progresso. Quando o run atinge estado terminal, o polling para.
- **Carregamento da lib HTMX**: adicionar tag `<script>` no `base.html` (a lib
  já está nas dependências Python `django-htmx`, mas o JS do lado cliente
  ainda não é carregado).
- **Exposição de `stage_metrics` no contexto**: a view `run_status` passa a
  incluir os estágios no contexto para renderização inicial.

## Scope / Non-Goals / Risks

### Scope

- Feedback de progresso na página `run_status` para todos os intents de run
  (`full_admission_sync`, `admissions_only`, `demographics_only`, genérico).
- Visualização dos 4 estágios já registrados pelo worker.
- Substituição do meta-refresh por HTMX polling com atualização parcial.
- Funciona com a infraestrutura já existente de `IngestionRunStageMetric`.

### Non-Goals

- Não altera o worker (`process_ingestion_runs`) — os dados de estágio já são
  persistidos.
- Não adiciona barra de progresso percentual (os estágios têm durações
  variáveis; percentual linear seria enganoso).
- Não adiciona notificações push/SSE/WebSockets.
- Não altera a página de criação de run (`create_run.html`).

### Main Risks

- **HTMX não carregado**: risco baixo — `django-htmx` já está em
  `INSTALLED_APPS` e `MIDDLEWARE`; só falta o `<script>` no template base.
- **Polling excessivo em runs de longa duração**: mitigado com intervalo de 3s
  (razoável) e parada automática em estado terminal.
- **Carga adicional no banco**: query de `stage_metrics` a cada 3s é trivial
  (1 run × ~4 registros).
- **Template parcial não acessível diretamente**: o endpoint de fragmento é
  interno, sem link direto. Retorna 404 se acessado sem `run_id` válido.

## Capabilities

### New Capabilities

- `run-status-progress`: feedback intermediário de progresso na página de
  status de sincronização, com visibilidade de estágio atual via HTMX polling.

### Modified Capabilities

- `ingestion-run-observability`: ampliação para exigir que a view de status
  exponha os estágios (`IngestionRunStageMetric`) na interface do usuário.

## Impact

- `apps/ingestion/views.py`: nova view `run_status_fragment` + contexto
  adicional em `run_status`.
- `apps/ingestion/urls.py`: nova rota para fragmento de progresso.
- `apps/ingestion/templates/ingestion/run_status.html`: substituição de
  meta-refresh por HTMX polling + seção de progresso.
- `apps/ingestion/templates/ingestion/_run_progress.html`: NOVO template
  parcial com lista de estágios.
- `templates/base.html`: adição do `<script>` da lib HTMX.
- Testes unitários e de integração para view de fragmento e template.
