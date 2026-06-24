# Change Proposal: adaptive-census-orchestrator

## Why

A rotina manual atual depende de monitoramento humano dos workers para evitar
que uma nova coleta de censo enfileire jobs enquanto o batch anterior ainda está
drenando. Como a duração real varia de cerca de 3,5 horas até 7 horas em dias
ruins, timer fixo aumenta o risco de backlog, travamento operacional e atraso
para gestão de leitos, qualidade, jurídico e prontuários.

## What Changes

- Introduzir um orquestrador adaptativo de ciclos de censo que monitora a fila
  de ingestão e dispara `extract_census` seguido de
  `process_census_snapshot` somente quando for seguro.
- Usar PostgreSQL como mecanismo de coordenação, preservando a decisão de não
  introduzir Celery/Redis na fase 1.
- Definir critérios explícitos de fila drenada, cooldown mínimo, tratamento de
  falha de extração e proteção contra execução concorrente.
- Garantir que o processamento do snapshot use o `run_id` da extração recém
  concluída, evitando ambiguidade com execuções manuais concorrentes.
- Expor saída operacional clara em CLI/logs para o operador entender se o
  orquestrador está aguardando, disparando ciclo, em backoff ou bloqueado por
  runs presas.
- Remover a estratégia de timer fixo de censo do deploy documentado e dos
  artefatos `systemd` correspondentes, pois ela não é mais o caminho
  operacional recomendado.
- Não alterar o worker `process_ingestion_runs` para assumir responsabilidade de
  orquestração de ciclos.

## Capabilities

### New Capabilities

- `adaptive-census-orchestration`: cobre o comportamento do orquestrador
  adaptativo, incluindo monitoramento da fila, disparo seguro do ciclo, lock,
  cooldown, backoff e modo contínuo.

### Modified Capabilities

- `census-snapshot-processing`: o ciclo orquestrado deve processar
  explicitamente o snapshot produzido pela extração recém-executada, mantendo o
  comportamento existente para uso manual sem `run_id`.
- `ingestion-run-observability`: a observabilidade operacional deve permitir
  distinguir espera por fila ativa, execução de ciclo e condições de bloqueio
  por runs ativas há tempo excessivo sem expor dados sensíveis.

## Impact

- Código afetado: novo management command de orquestração, pequena camada de
  serviço operacional quando necessário, testes unitários e testes focados de
  comando.
- Deploy afetado: remover documentação e units de timer fixo de censo;
  adicionar documentação para rodar o orquestrador como serviço contínuo ou em
  foreground.
- Banco de dados: sem nova dependência externa; preferir lock advisory do
  PostgreSQL. Migração só será necessária se a implementação optar por persistir
  estado próprio do orquestrador, o que não é o plano inicial.
- Operação: o timer fixo deixa de ser recomendado; o worker contínuo permanece
  necessário para processar os `IngestionRun` enfileirados.
- Não objetivos: não implementar Celery, Redis, microserviço externo, UI de
  controle do orquestrador ou reprocessamento automático agressivo de runs
  presas neste change.
- Riscos principais: runs `running` abandonadas podem bloquear novos ciclos;
  mitigação inicial será detecção e mensagem operacional explícita, sem marcar
  runs como falhas automaticamente neste change.
