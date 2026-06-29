# Change Proposal: dedicated-census-orchestrator-service

## Why

A extração inicial do censo (`extract_census`) roda hoje pelo serviço `web`
quando o operador executa `run_adaptive_census_cycles`, mas esse container não
tem tmpfs configurado para temporários/cache do Playwright. Isolar o
orquestrador em um serviço dedicado com armazenamento volátil reduz escrita
física no NVMe e evita que automação pesada compartilhe recursos efêmeros com o
portal web.

## What Changes

- Criar um serviço Docker Compose de produção dedicado ao orquestrador de censo
  em loop contínuo, em vez de orientar execução long-running via `exec -T web`.
- Configurar esse serviço com `tmpfs`, `shm_size`, variáveis de temporários e
  cache/config em storage volátil, usando limites conservadores e overrides
  específicos.
- Atualizar a unit systemd para iniciar/parar o serviço dedicado via Docker
  Compose, sem depender de shell interativo dentro do container `web`.
- Atualizar `deploy/README.md` com operação, validação, sizing, rollback e
  comandos manuais/dry-run alinhados ao novo serviço.
- Manter compatibilidade dos management commands existentes; `web` continua
  podendo executar comandos manuais de diagnóstico, mas não é o runtime
  recomendado para o loop de produção.
- Não introduzir Celery, Redis, novos serviços externos ou mudanças no fluxo de
  banco de dados.

## Capabilities

### New Capabilities

- `production-census-orchestrator-runtime`: define o runtime de produção do
  orquestrador adaptativo de censo como serviço dedicado com tmpfs, memória
  compartilhada parametrizável, logs limitados e documentação operacional.

### Modified Capabilities

- `adaptive-census-orchestration`: o modo contínuo do orquestrador passa a ter
  contrato de deploy recomendado por serviço dedicado, preservando `--dry-run`,
  `--once` e execução manual para diagnóstico.

## Impact

- Configuração afetada: `compose.prod.yml` e
  `deploy/systemd/sirhosp-census-orchestrator.service`.
- Documentação afetada: `deploy/README.md` e, se necessário, referências
  operacionais curtas em `README.md`/`AGENTS.md` somente se ficarem
  inconsistentes.
- Testes afetados: testes unitários de caracterização da configuração Compose e
  da documentação de deploy.
- Operação: operadores deverão subir/recriar o novo serviço dedicado e remover
  o hábito de rodar loop long-running por `exec -T web`.
- Riscos principais: consumo adicional de RAM por tmpfs, duplicação de
  variáveis de ambiente entre serviços Compose e conflito se o loop antigo for
  mantido rodando em paralelo; mitigação por limites conservadores,
  documentação explícita e systemd apontando para um único serviço.
