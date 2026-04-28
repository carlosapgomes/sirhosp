# Design: run-status-progress-feedback

## Context

O fluxo de sincronização atual:

1. Usuário seleciona internação e clica "Sincronizar" (`admission_list.html`)
2. POST para `ingestion:create_run` → cria `IngestionRun` com `status=queued`
3. Redireciona para `ingestion:run_status`
4. `run_status.html` usa `<meta http-equiv="refresh" content="5">` enquanto
   `status ∈ {queued, running}`
5. Worker assíncrono processa o run em 4 estágios e atualiza `IngestionRun`
   - cria `IngestionRunStageMetric`
6. Quando status terminal, meta-refresh para

**Problema**: entre os passos 4 e 6, o operador vê apenas um spinner e o texto
"Em execução..." por 30s–5min, sem visibilidade do que está acontecendo.

**Infraestrutura já existente não utilizada**:
`IngestionRunStageMetric` já é populado pelo worker a cada estágio. A view
`run_status` não consulta nem expõe esses dados.

## Goals / Non-Goals

**Goals:**

- Expor estágios de execução na página de status com atualização automática
- Substituir full-page refresh por atualização parcial via HTMX
- Exibir: nome do estágio, status (concluído/em andamento/pendente/falhou),
  duração de cada estágio concluído
- Parar polling automaticamente ao atingir estado terminal
- Funcionar para todos os intents de run existentes

**Non-Goals:**

- Não modificar o worker
- Não adicionar barra de progresso percentual
- Não usar SSE/WebSockets
- Não persistir novos dados

## Decisions

### D1) Endpoint separado para fragmento de progresso

**Decisão**: criar view `run_status_fragment` dedicada que retorna apenas o
HTML da seção de progresso, em vez de verificar header `HX-Request` na view
existente.

**Justificativa**:

- Separação clara de responsabilidades
- Testável isoladamente (teste unitário da view de fragmento)
- Evita poluir a view principal com lógica condicional de renderização parcial
- Permite evolução independente (ex: retornar JSON no futuro)

### D2) Template parcial dedicado `_run_progress.html`

**Decisão**: criar template parcial separado, incluído tanto pelo fragmento
quanto pela página principal (para renderização inicial sem flicker).

**Justificativa**:

- DRY: mesma lógica de renderização nos dois contextos
- O include no template principal garante que o conteúdo aparece imediatamente
  (antes do primeiro polling)
- O fragmento reusa o mesmo partial

### D3) HTMX via CDN (unpkg)

**Decisão**: carregar HTMX via `<script src="https://unpkg.com/htmx.org@2.0.4">`
no `base.html`, em vez de servir localmente.

**Alternativa considerada**: baixar e servir como static file.
**Por que CDN**: mais simples, sem build step, versão explícita, cache do
browser. Para produção futura, pode-se migrar para static file local.

### D4) Intervalo de polling fixo de 3 segundos

**Decisão**: `hx-trigger="every 3s"` fixo, sem backoff adaptativo.

**Justificativa**:

- Simplicidade — sem JavaScript customizado
- 3s é responsivo o suficiente para feedback operacional
- Estágios rápidos (<1s) podem ser "pulados" na UI, mas o estágio final sempre
  aparece (o run fica em `running` até todos os estágios terminarem)
- Carga no banco: 1 query leve a cada 3s por usuário ativo

### D5) Sem indicador de "estágio atual" inferido — usar estado dos registros

**Decisão**: determinar visualmente qual estágio está "em andamento" pelo fato
de ser o último registrado com `finished_at=NULL` e status não-falho.

**Lógica no template**:

- Estágio com `finished_at` preenchido e `status=succeeded`: ✅ Concluído
- Estágio com `finished_at` preenchido e `status=failed`: ❌ Falhou
- Estágio com `finished_at` preenchido e `status=skipped`: ⏭️ Pulado
- Estágio sem `finished_at` (ainda não registrado): ⏳ Pendente
- Se o run está `running` e há estágios, o último registrado que ainda não
  tem um próximo estágio iniciado é o "em andamento" (🔄)

## Risks / Trade-offs

- **[Estágio rápido demais para ser visto]**: Estágios que duram <3s podem
  ser criados e concluídos entre dois polls. Isso é aceitável — o operador
  verá o estágio como concluído no próximo poll.
- **[HTMX CDN offline]**: Em ambiente sem internet, o HTMX não carrega e a
  página degrada para comportamento estático (sem polling). Adicionar
  fallback ou servir localmente em change futuro.
- **[Múltiplos estágios "em andamento"]**: Não ocorre na prática porque o
  worker é sequencial. Se ocorrer por bug, a UI mostrará o primeiro sem
  `finished_at` como ativo.

## Migration Plan

1. Slice PF-1: Criar view + URL + template parcial + testes unitários
2. Slice PF-2: Integrar HTMX no template principal + carregar lib + testes
   de integração
3. Slice PF-3: Hardening, quality gate, atualização de specs

**Rollback**: remover `<script>` HTMX do `base.html` e restaurar
`<meta refresh>` no `run_status.html`. Remover rota do fragmento. Nenhum
dado é perdido.

## Open Questions

1. Queremos exibir duração formatada (ex: "12s", "1m30s") ou ISO?
   → **Decidido**: formato humano ("12s", "1m 30s").
2. O que mostrar quando `admissions_only` só tem 1 estágio
   (`admissions_capture`)? → Mostrar só o que existe; não mostrar estágios
   que não se aplicam.
3. Em caso de falha, mostrar `details_json` com erro?
   → Sim, em tooltip ou texto pequeno abaixo do nome do estágio.
