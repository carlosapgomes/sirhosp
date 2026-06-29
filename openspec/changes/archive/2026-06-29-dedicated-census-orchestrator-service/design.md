# Design: dedicated-census-orchestrator-service

## Context

O fluxo adaptativo de censo executa um ciclo seguro:

```text
run_adaptive_census_cycles --loop
  -> extract_census
  -> process_census_snapshot
  -> workers processam IngestionRun enfileirados
```

Em produção, os workers já têm `tmpfs`, `shm_size` e variáveis de temporário
para reduzir escrita efêmera no NVMe. A fase inicial do ciclo (`extract_census`)
roda hoje a partir do serviço `web` quando acionada pelo systemd existente ou
por comandos manuais com `exec -T web`. Esse serviço não possui tmpfs próprio e
também atende o portal Django/Gunicorn.

O objetivo deste change é isolar o loop do orquestrador em um serviço Docker
Compose dedicado, com runtime volátil semelhante ao dos workers, sem alterar a
lógica Python do orquestrador nem introduzir Celery/Redis.

## Goals / Non-Goals

**Goals:**

- Criar um serviço de produção dedicado para `run_adaptive_census_cycles
  --loop`.
- Garantir que temporários, caches, config e `/dev/shm` usados por Playwright no
  orquestrador sejam conservadoramente limitados e parametrizáveis.
- Evitar que a automação de censo compartilhe temporários e processo com o
  container `web`.
- Atualizar systemd e documentação para operar o serviço dedicado.
- Manter slices pequenos, testáveis e com handoff claro para executor LLM em
  contexto zero.

**Non-Goals:**

- Não alterar o algoritmo de elegibilidade, cooldown, advisory lock ou stale
  recovery do orquestrador.
- Não mudar `extract_census`, `process_census_snapshot` ou parsers Playwright.
- Não adicionar Celery, Redis, scheduler externo ou banco novo.
- Não aplicar tmpfs ao serviço `web` neste change.
- Não reestruturar todos os serviços Compose nem mudar o runtime dos workers.

## Decisions

### 1. Serviço dedicado `census_orchestrator`

Adicionar um serviço de produção chamado `census_orchestrator` em
`compose.prod.yml`. Ele deve usar a mesma imagem `prod`, rede e variáveis
necessárias para Django, PostgreSQL, credenciais do sistema fonte e proxy
Playwright.

Alternativa considerada: adicionar tmpfs ao `web`. Rejeitada como solução
principal porque mistura portal web e automação pesada, aumenta o risco de
`ENOSPC` afetar usuários e dificulta medir o custo real do orquestrador.

### 2. Serviço atrás de profile ou acionamento explícito

O serviço dedicado deve ser iniciado explicitamente, sem surpreender operadores
que executam `docker compose up -d --build` apenas para web/worker. A forma
preferida é usar um Compose profile ou documentar comando explícito que deixa
claro quando o loop contínuo passa a rodar.

A implementação deve evitar duas instâncias long-running simultâneas. Mesmo que
o advisory lock proteja ciclos concorrentes, o deploy deve orientar um único
runtime ativo.

### 3. Tmpfs e `shm_size` próprios do orquestrador

Usar variáveis próprias, por exemplo:

```text
CENSUS_ORCHESTRATOR_SHM_SIZE
CENSUS_ORCHESTRATOR_TMPFS_TMP_SIZE
CENSUS_ORCHESTRATOR_TMPFS_VAR_TMP_SIZE
CENSUS_ORCHESTRATOR_TMPFS_CACHE_SIZE
CENSUS_ORCHESTRATOR_TMPFS_CONFIG_SIZE
```

Os defaults devem ser conservadores e próximos dos workers:

```text
/dev/shm: 512m
/tmp: 1g
/var/tmp: 128m
/home/10001/.cache: 256m
/home/10001/.config: 64m
```

Racional: evita acoplamento operacional com `WORKER_*`, permite ajustar a
extração inicial do censo sem mudar workers escalados e mantém YAGNI sem criar
mecanismo dinâmico de sizing.

### 4. Systemd deve gerenciar o serviço Compose dedicado

Atualizar `deploy/systemd/sirhosp-census-orchestrator.service` para não usar
`docker compose exec -T web`. A unit deve iniciar o serviço dedicado por Docker
Compose e parar esse mesmo serviço no shutdown.

Racional: `exec -T web` depende de um container web já rodando, mistura logs e
runtime, e não expressa o orquestrador como unidade operacional independente.

### 5. Testes de caracterização por texto são suficientes

A mudança é de infraestrutura declarativa. Testes unitários podem ler
`compose.prod.yml`, `deploy/systemd/sirhosp-census-orchestrator.service` e
`deploy/README.md` como texto para garantir contratos relevantes, sem novas
dependências.

Racional: simples, rápido, determinístico e alinhado com testes existentes de
runtime tmpfs dos workers.

## Risks / Trade-offs

- Consumo extra de RAM por tmpfs -> limites conservadores e overrides no `.env`.
- Dois loops rodando em paralelo -> docs e systemd apontam para um único serviço
  dedicado; advisory lock continua como defesa.
- `tmpfs` pequeno durante extração lenta -> orientação de ENOSPC e aumento de
  `CENSUS_ORCHESTRATOR_TMPFS_TMP_SIZE`.
- Profile/acionamento explícito aumenta um pouco a operação -> evita ativação
  acidental do loop contínuo.
- Teste por texto pode ser menos semântico que parser YAML -> mantém zero
  dependências e acompanha padrão já usado no projeto.

## Migration Plan

1. Implementar o serviço `census_orchestrator` com tmpfs e testes.
2. Atualizar a unit systemd para usar o serviço dedicado.
3. Atualizar documentação operacional e comandos de validação.
4. Em produção, garantir que não há loop antigo rodando via `web`.
5. Subir o serviço dedicado explicitamente ou habilitar a unit systemd.
6. Validar tmpfs com `df -hT` no container do orquestrador e comparar `wMB/s`
   no host com `iostat`.

Rollback:

1. Parar `census_orchestrator` ou desabilitar a unit systemd.
2. Voltar temporariamente a comandos manuais via `web` se necessário.
3. Reverter o change caso a topologia dedicada cause regressão operacional.

## Open Questions

- O serviço dedicado deve usar Compose profile obrigatório ou apenas ser
  documentado como acionamento explícito?
- O default de `/tmp` deve começar em `1g` ou `2g` após medição real do
  `extract_census`?
- Convém criar, em change futuro, métrica automática de escrita por fase do
  censo, além de orientação manual com `iostat`?
