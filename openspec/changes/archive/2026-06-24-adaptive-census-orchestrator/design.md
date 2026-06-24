# Design: adaptive-census-orchestrator

## Context

O fluxo operacional atual é manual: o operador observa os logs dos workers,
espera a fila ficar ociosa e então executa `extract_census` seguido de
`process_census_snapshot`. O timer fixo de 8 horas existe no repositório, mas
não está em uso porque a duração real do batch varia muito conforme rede e
sistema legado.

O projeto já possui os blocos necessários para uma solução simples:

- `IngestionRun` registra jobs `queued`, `running`, `succeeded` e `failed`.
- `CensusExecutionBatch` agrupa os jobs criados por `process_census_snapshot`.
- `process_ingestion_runs --loop` drena a fila continuamente.
- PostgreSQL já é usado para coordenação operacional básica.

A mudança deve preservar o monólito Django e não introduzir Celery, Redis ou
outro serviço de fila.

## Goals / Non-Goals

**Goals:**

- Automatizar o mesmo julgamento que hoje é feito manualmente pelo operador:
  disparar novo ciclo somente quando a fila estiver drenada.
- Evitar acúmulo de batches quando rede ou sistema legado estiverem lentos.
- Manter implementação pequena, testável e baseada em management command.
- Processar o snapshot produzido pela extração recém-executada.
- Remover o timer fixo de censo como caminho operacional documentado.
- Dividir implementação em slices verticais e enxutos, cada um com prompt
  próprio para executor LLM com contexto zero.

**Non-Goals:**

- Não criar UI administrativa para controlar o orquestrador.
- Não adicionar Celery, Redis, fila externa, microserviço ou scheduler externo.
- Não recuperar automaticamente runs `running` abandonadas.
- Não alterar a lógica clínica de parsing ou persistência do censo.
- Não alterar o worker para executar o papel de orquestrador.

## Decisions

### 1. Novo management command separado

Criar um comando dedicado, por exemplo `run_adaptive_census_cycles`, em vez de
embutir a lógica no worker.

Racional:

- Mantém separação clara entre produtor de ciclos e consumidor de jobs.
- Permite execução manual, `systemd service` contínuo ou foreground para debug.
- Evita transformar `process_ingestion_runs` em componente com duas
  responsabilidades.

Alternativa considerada: colocar a lógica no worker. Rejeitada por acoplar
drenagem de fila com disparo de novas coletas e dificultar paralelismo futuro.

### 2. Critério conservador de fila drenada

O orquestrador só pode iniciar novo ciclo quando não existir `IngestionRun` com
`status` em `queued` ou `running` e não existir batch de censo ainda aberto.

Racional:

- A regra é fácil de explicar e auditar.
- Evita enfileirar novo batch enquanto ainda há trabalho pendente.
- Sacrifica um pouco de throughput para proteger o sistema legado.

Alternativa considerada: filtrar apenas intents ligadas ao censo. Rejeitada no
primeiro momento porque a fila é compartilhada e o risco operacional principal
é sobrecarga global de automações Playwright.

### 3. Lock advisory no PostgreSQL

Usar lock advisory para impedir dois orquestradores simultâneos. A
implementação deve falhar de forma segura quando não conseguir adquirir o lock.

Racional:

- Usa infraestrutura já permitida pelo projeto.
- Não exige modelo novo nem migração.
- Funciona bem para comando único em produção.

Alternativa considerada: tabela persistente de `CensusOrchestratorRun`.
Rejeitada como complexidade desnecessária para a primeira versão.

### 4. Ciclo explícito: extração seguida de processamento por `run_id`

O comando deve executar `extract_census`, identificar exatamente um novo
`IngestionRun(intent="census_extraction")` bem-sucedido criado durante a
extração e chamar `process_census_snapshot --run-id=<id>`.

Racional:

- Evita processar snapshot errado caso exista histórico recente.
- Preserva compatibilidade dos comandos existentes.
- Evita refatorar toda a extração de censo em um primeiro slice.

Se zero ou mais de um run novo forem encontrados, o comando deve abortar com
mensagem operacional clara, sem enfileirar novo batch.

### 5. Cooldown e backoff explícitos

Mesmo com fila drenada, o comando deve respeitar intervalo mínimo entre ciclos.
Em caso de falha de extração ou processamento, o modo loop deve aplicar backoff
antes de tentar novamente.

Racional:

- Evita martelar o sistema legado em dias bons.
- Evita loop de falhas rápidas quando credenciais, rede ou legado estão ruins.

Valores padrão sugeridos:

- `--sleep-seconds 60`
- `--min-interval-minutes 30`
- `--failure-backoff-minutes 30`
- `--stale-running-minutes 180`

### 6. Runs ativas antigas bloqueiam e alertam

Se houver run `running` além do limite configurado, o orquestrador deve reportar
bloqueio operacional, mas não deve marcar a run como falha automaticamente.

Racional:

- Evita perda de rastreabilidade ou encerramento indevido de uma automação lenta.
- Mantém a primeira versão segura e previsível.

### 7. Slices verticais e enxutos

A implementação deve ser dividida em quatro slices:

1. estado operacional e dry-run do orquestrador;
2. execução segura de um ciclo real;
3. modo contínuo com cooldown, backoff e sinais;
4. deploy/documentação e remoção do timer fixo de censo.

Cada slice deve ter prompt próprio em `slice-prompts/`, limitar arquivos
alterados, exigir TDD e gerar relatório em `/tmp` para revisão por terceiro LLM.

## Risks / Trade-offs

- Run `running` abandonada bloqueia ciclos indefinidamente → mitigar com
  detecção de stale e mensagem clara para intervenção manual.
- Execução manual paralela de `extract_census` pode criar ambiguidade de
  `run_id` → abortar se mais de um novo run for detectado durante o ciclo.
- Critério global de fila vazia reduz throughput → aceitar no MVP para proteger
  o sistema legado; refinar por intent em change futuro se necessário.
- Remover timer fixo pode surpreender quem leu docs antigas → atualizar
  `deploy/README.md` e remover units de censo para evitar caminho obsoleto.
- Testar loop contínuo pode gerar testes lentos → isolar unidade de decisão e
  testar loop com `sleep`/`call_command` mockados.

## Migration Plan

1. Implementar e validar slices em ordem.
2. Manter comandos manuais existentes funcionando durante toda a mudança.
3. Após S4, operar com worker contínuo e orquestrador contínuo; não instalar
   `sirhosp-census.timer`.
4. Rollback: parar o serviço do orquestrador e voltar ao disparo manual dos dois
   comandos existentes. Nenhuma migração de banco deve ser necessária.

## Open Questions

- O intervalo mínimo padrão deve ser 30 ou 60 minutos em produção?
- O limite de stale `running` deve ser 180 minutos ou mais próximo de 8 horas,
  considerando dias ruins já observados?
- Futuramente, vale permitir janela diária de operação para evitar coletas em
  horários de pico do sistema legado?
