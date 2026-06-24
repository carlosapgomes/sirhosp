# Design: stale-ingestion-run-recovery

## Context

O orquestrador adaptativo de censo agora roda como produtor contínuo de batches,
mas ainda depende de a fila de `IngestionRun` drenar completamente. A política
atual detecta runs `running` antigas e apenas alerta. Isso é seguro no primeiro
momento, mas inadequado para produção contínua: uma única run abandonada
mantém o batch aberto e impede novos ciclos.

Dados operacionais levantados em produção indicam que jobs individuais duram
minutos, enquanto batches completos podem durar horas. Isso separa dois conceitos
que não devem compartilhar o mesmo limite de tempo:

- batch: conjunto grande, esperado durar horas em dias ruins;
- run individual: unidade de trabalho, esperada durar minutos.

O ambiente de produção roda workers em Docker rootless e o orquestrador via
`systemd` no host. Por isso, confirmação por PID/container não é uma base
confiável. O sinal de vida deve estar no PostgreSQL, que já é a coordenação
permitida na fase 1.

## Goals / Non-Goals

**Goals:**

- Persistir heartbeat para runs em processamento sem expor dados sensíveis.
- Identificar runs `running` abandonadas por idade individual e heartbeat.
- Marcar runs abandonadas como `failed` terminal, sem requeue automático.
- Fechar batches drenados após a recuperação para liberar o próximo ciclo.
- Permitir execução manual via comando e automática via loop do orquestrador.
- Manter slices pequenos, testáveis e adequados para implementação por LLM com
  contexto zero.

**Non-Goals:**

- Não adicionar Celery, Redis, Docker socket, API Docker ou dependência de PID do
  host.
- Não reprocessar imediatamente runs abandonadas no mesmo batch.
- Não alterar parsing clínico, scraping do censo ou lógica de ingestão de
  evoluções além do heartbeat operacional.
- Não criar UI administrativa nesta mudança.
- Não introduzir tabela nova de job recovery ou scheduler separado.

## Decisions

### 1. Heartbeat persistido no `IngestionRun`

Adicionar um campo nullable de timestamp, por exemplo
`worker_heartbeat_at`, atualizado enquanto o worker processa uma run.

Racional:

- Funciona com worker em Docker rootless e orquestrador no host.
- Evita depender de PID, namespace de processo ou Docker socket.
- Mantém a coordenação dentro do PostgreSQL, como o restante da fase 1.

Alternativa considerada: usar `worker_label` para confirmar PID/container vivo.
Rejeitada como critério principal porque o orquestrador no host pode não ter
acesso confiável ao processo do container rootless. O `worker_label` permanece
útil para diagnóstico em logs e relatórios.

### 2. Heartbeat deve sobreviver a subprocessos bloqueantes

O worker deve atualizar heartbeat durante o processamento, não apenas quando muda
de estágio. A implementação preferida é um helper pequeno com contexto ou thread
de baixa frequência, iniciado por run e encerrado no `finally` do processamento.

Valores sugeridos:

- intervalo de heartbeat: 60 segundos;
- margem de heartbeat stale: 10 minutos.

Racional:

- Extrações usam subprocessos Playwright e podem bloquear a thread principal por
  minutos.
- Atualizações a cada minuto geram carga baixa no PostgreSQL mesmo com poucos
  workers contínuos.

### 3. Limites por `intent`, não limite global de batch

Uma run é candidata a stale quando sua idade individual excede o limite do seu
`intent`. A idade deve usar `COALESCE(processing_started_at, queued_at,
started_at)`.

Limites iniciais recomendados:

| Intent | Limite inicial |
| --- | ---: |
| `admissions_only` | 20 min |
| `demographics_only` | 20 min |
| `full_sync` | 60 min |
| `census_extraction` | 120 min |
| vazio/desconhecido | 60 min |

Racional:

- `admissions_only` e `demographics_only` têm timeout curto e p99 de poucos
  minutos.
- `full_sync` pode ter múltiplas janelas e deve receber margem maior.
- `census_extraction` tem timeout próprio de 80 minutos e precisa de margem
  acima disso.

Alternativa considerada: 30 minutos global. Rejeitada porque poderia matar
`full_sync` legítimo em dias lentos e é curto demais para `census_extraction`.

### 4. Critério composto para marcar abandoned

Uma run deve ser marcada como abandoned somente quando todos forem verdadeiros:

1. `status = 'running'`;
2. idade individual acima do limite por `intent`;
3. `worker_heartbeat_at` está ausente ou é mais antigo que a margem de stale.

Racional:

- O tempo sozinho evita jobs absurdamente longos.
- O heartbeat reduz falso positivo contra jobs longos ainda vivos.
- `worker_label` vazio deve aparecer em logs, mas não é necessário para a regra.

### 5. Recuperação terminal sem requeue automático

A recuperação automática deve marcar a run como terminalmente `failed`:

- `status = 'failed'`;
- `finished_at = now()`;
- `timed_out = True`;
- `failure_reason = 'timeout'`;
- `next_retry_at = None`;
- `error_message` seguro indicando stale recovery e parâmetros usados.

Ela não deve chamar a lógica de retry normal do worker.

Racional:

- O objetivo operacional é liberar o batch e preservar cadência de ciclos.
- Em batches de 1300 a 1400 jobs, perder 1 ou 2 jobs é tolerável para o uso
  atual.
- O próximo batch reenfileira pacientes ainda presentes no censo.

Alternativa considerada: requeue se houver tentativas restantes. Rejeitada
para o caminho automático porque pode manter o batch aberto e derrotar a
recuperação.

### 6. Serviço reutilizável e comando separado

A lógica central deve ficar em um serviço de domínio operacional, por exemplo em
`apps.ingestion.stale_recovery`, e ser chamada por:

- management command `recover_stale_ingestion_runs`;
- loop do orquestrador adaptativo.

O comando deve suportar `--dry-run` e `--apply`. O dry-run não deve mutar dados.

Racional:

- DRY: uma regra de recuperação, dois pontos de entrada.
- Operação manual pode validar candidatos antes de ativar automação.
- Testes unitários podem exercitar o serviço sem depender de CLI.

### 7. Circuit breaker simples por sweep

A recuperação automática deve ter limite máximo por execução, por exemplo
`--max-runs-per-sweep 20`. Se o número de candidatos exceder o limite, a execução
deve abortar sem mutar dados e emitir alerta operacional.

Racional:

- Um número alto de stale runs pode indicar falha sistêmica de worker, banco ou
  deploy.
- É mais seguro bloquear e chamar operador do que marcar centenas de runs como
  failed em massa.

### 8. Integração no orquestrador antes da elegibilidade

No loop contínuo, o orquestrador deve executar a recuperação antes de calcular o
estado operacional. Assim, uma run abandonada pode ser encerrada, o batch pode
fechar, e a próxima avaliação de elegibilidade pode iniciar novo ciclo.

A integração deve ser configurável por flags, mas o comportamento de produção
recomendado deve ser habilitado no loop.

## Risks / Trade-offs

- Falso positivo em job vivo mas sem heartbeat → mitigar com heartbeat em thread,
  margem de 10 minutos e limites por intent.
- Falha sistêmica gera muitos candidatos → mitigar com circuit breaker e logs
  explícitos sem mutação em massa.
- Migração adiciona campo nullable em tabela grande → mitigar com coluna nullable
  sem backfill obrigatório.
- Recovery terminal perde um job específico → aceitável pela tolerância
  operacional declarada; próximo batch pode recuperar pacientes ainda ativos.
- Heartbeat aumenta writes no banco → intervalo de 60 segundos e baixo número de
  workers tornam o custo aceitável.

## Migration Plan

1. Aplicar migração do campo de heartbeat.
2. Implantar worker com heartbeat e reiniciar workers contínuos.
3. Validar manualmente o comando `recover_stale_ingestion_runs --dry-run`.
4. Habilitar recuperação no loop do orquestrador.
5. Monitorar logs de auto-fail e quantidade de batches liberados.
6. Rollback: desabilitar recuperação no orquestrador, parar o comando manual e
   deixar o campo nullable sem uso até nova decisão.

## Open Questions

- O limite de `full_sync` deve começar em 60 minutos ou 45 minutos após alguns
  dias de observação?
- O `max-runs-per-sweep` padrão deve ser 20 ou menor em produção inicial?
- Deve haver relatório operacional periódico dos failed por stale recovery em
  change futuro?
