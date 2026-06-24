# Change Proposal: stale-ingestion-run-recovery

## Why

O orquestrador adaptativo de censo pode ficar bloqueado indefinidamente quando
uma única `IngestionRun` permanece em `running` após o worker morrer ou perder o
controle do job. Em produção, batches completos podem durar horas, mas os jobs
individuais observados duram minutos; portanto uma run individual abandonada não
deve impedir 4 a 5 ciclos de censo por dia.

## What Changes

- Adicionar heartbeat persistido para o worker de ingestão enquanto uma
  `IngestionRun` está em processamento, sem depender de PID ou Docker socket.
- Definir critérios explícitos para classificar uma run `running` como
  abandonada usando idade por `intent` e heartbeat ausente/antigo.
- Adicionar recuperação terminal de stale runs: marcar como `failed` sem requeue
  automático, registrar mensagem segura, marcar timeout operacional e tentar
  fechar o batch quando a fila do batch drenar.
- Expor comando operacional separado com `--dry-run` e `--apply` para inspeção e
  intervenção manual controlada.
- Integrar a mesma rotina de recuperação ao loop do orquestrador adaptativo antes
  da avaliação de elegibilidade, para que o serviço em background não fique
  refém de um job zumbi.
- Adicionar circuit breaker para evitar marcação em massa quando houver sinal de
  falha sistêmica.
- Não introduzir Celery, Redis, Docker socket, dependência de PID do host, nem
  requeue automático para runs abandonadas.

## Capabilities

### New Capabilities

- `ingestion-run-stale-recovery`: cobre identificação, dry-run, aplicação e
  fechamento de batch após recuperação de `IngestionRun` abandonada.

### Modified Capabilities

- `ingestion-run-observability`: adiciona heartbeat de worker para distinguir
  run ativa saudável de run abandonada sem depender de processo local.
- `adaptive-census-orchestration`: o loop do orquestrador passa a executar a
  recuperação de stale runs antes de decidir se um novo ciclo pode começar.

## Impact

- Código afetado: modelo `IngestionRun`, migração, worker
  `process_ingestion_runs`, novo serviço/comando de recuperação, orquestrador
  adaptativo e testes focados.
- Operação: o worker contínuo continua necessário; o orquestrador em systemd no
  host poderá recuperar runs abandonadas via banco, mesmo com workers em Docker
  rootless.
- Banco de dados: nova coluna de heartbeat em `IngestionRun`; sem nova tabela e
  sem dependência externa.
- Segurança: logs e mensagens devem conter apenas ids técnicos, `intent`, status,
  timestamps e contagens; nunca nomes de pacientes, textos clínicos ou
  credenciais.
- Risco principal: falso positivo ao marcar como failed uma run ainda viva;
  mitigação por heartbeat, limites por intent, margem conservadora e circuit
  breaker.
- Não objetivo: recuperar ou reprocessar imediatamente cada paciente perdido; o
  próximo batch de censo poderá reenfileirar pacientes ainda relevantes.
