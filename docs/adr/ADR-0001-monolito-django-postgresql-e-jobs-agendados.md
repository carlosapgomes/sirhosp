# ADR-0001 — Adotar monólito modular em Django com PostgreSQL e jobs agendados por systemd/cron

## Status

Accepted

## Contexto

O SIRHOSP é um sistema interno voltado para extração automatizada de dados clínicos do sistema fonte hospitalar, armazenamento em banco paralelo e oferta de consultas rápidas, busca textual e resumos institucionais.

O contexto operacional atual é o seguinte:

- o sistema não é missão crítica
- a implantação inicial ocorrerá em uma única VM Linux
- os jobs serão executados em horários específicos
- o volume inicial de concorrência é baixo
- a equipe de manutenção será pequena
- o sistema precisa de autenticação própria, páginas web internas, persistência relacional e automações Playwright
- a fase 1 prioriza simplicidade operacional, rapidez de entrega e baixa carga de manutenção

Na discussão inicial, foi considerada a adoção de **Celery + Redis** para filas e processamento assíncrono. Após revisão do cenário real de uso, essa combinação foi considerada mais complexa do que o necessário para a fase 1.

## Decisão

Adotar a seguinte arquitetura para a fase 1 do SIRHOSP:

- **aplicação principal em Django**
- **PostgreSQL como banco principal**
- **`uv` como padrão para gerenciamento de ambiente virtual, dependências e execução de comandos Python**
- **jobs executados por Django management commands**
- **agendamento via systemd timers**, com `cron` como alternativa aceitável
- **coordenação operacional de jobs no próprio PostgreSQL**, usando tabelas de controle e locks
- **Playwright + Python** para automações de extração
- **Django Templates + HTMX + Bootstrap** para interface inicial

Também fica decidido que:

- **Celery + Redis não serão adotados na fase 1**
- essa decisão poderá ser revista futuramente se houver aumento relevante de volume, criticidade ou complexidade operacional

## Justificativa

### 1. Suficiência técnica para o cenário atual

A fase 1 não exige processamento distribuído sofisticado, filas em tempo real nem orquestração complexa entre múltiplos serviços. Os jobs ocorrerão em janelas programadas e com concorrência limitada.

### 2. Redução de complexidade operacional

Remover Redis e Celery simplifica:

- deployment
- monitoramento
- troubleshooting
- manutenção por equipe pequena
- operação em VM única

### 3. Aproveitamento do PostgreSQL já necessário

O PostgreSQL já será parte obrigatória da solução. Ele pode, além de persistir os dados clínicos, servir para:

- armazenar jobs agendados
- registrar execuções
- controlar concorrência
- impedir duplicidade
- registrar falhas e retries

### 4. Melhor alinhamento com o perfil do projeto

Como o sistema é interno, não missão crítica e orientado a rotinas programadas, a simplicidade arquitetural gera mais benefício do que a adoção precoce de uma fila distribuída.

## Alternativas consideradas

### Alternativa A — Django + PostgreSQL + Celery + Redis

**Vantagens:**

- ecossistema maduro para tarefas assíncronas
- retries e chaining mais sofisticados
- caminho natural para maior escala futura

**Desvantagens:**

- mais serviços para operar
- maior complexidade de deploy
- troubleshooting adicional
- custo de manutenção desnecessário para a fase 1

**Motivo para não escolher agora:**
A solução é tecnicamente válida, mas está acima da necessidade real do projeto neste momento.

### Alternativa B — Microserviços separados para portal, scraper e scheduler

**Vantagens:**

- separação máxima entre responsabilidades
- escalabilidade independente por componente

**Desvantagens:**

- alto custo arquitetural inicial
- mais difícil de operar em equipe pequena
- desproporcional ao estágio do produto

**Motivo para não escolher:**
Complexidade excessiva para o momento atual.

### Alternativa C — Flask/FastAPI + scripts independentes + PostgreSQL

**Vantagens:**

- flexibilidade
- estrutura potencialmente mais leve

**Desvantagens:**

- mais trabalho manual para auth, admin e área interna
- menor vantagem estrutural para o tipo de sistema pretendido

**Motivo para não escolher:**
Django oferece melhor base para auth, admin, modelos relacionais e portal institucional interno.

## Consequências

### Positivas

- arquitetura mais simples de implantar e manter
- menos moving parts na fase inicial
- menor custo de troubleshooting
- melhor aderência ao contexto de VM única
- uso de componentes maduros e conhecidos
- base sólida para crescimento incremental

### Negativas / Trade-offs

- menos recursos prontos de fila distribuída
- retries e encadeamentos exigirão implementação própria, ainda que simples
- crescimento futuro pode exigir migração para Celery + Redis
- disciplina de coordenação no banco será importante para evitar duplicidades

## Detalhes de implementação decorrentes

A decisão implica a criação de:

- tabelas para `scheduled_job` e `ingestion_run`
- status explícitos de execução
- management commands para execução programada
- padronização de execução local e operacional via `uv` e `uv run`
- locks no PostgreSQL, preferencialmente advisory locks
- controle explícito de concorrência, com limite inicial de até 3 automações simultâneas
- separação entre modo laboratório e modo produção para as automações Playwright

## Critérios para reavaliar esta ADR

A adoção de Celery + Redis deverá ser reconsiderada se ocorrer um ou mais dos cenários abaixo:

- aumento importante do número de jobs e frequência de execução
- necessidade de execução assíncrona em tempo real acionada por usuários
- necessidade de filas com prioridades complexas
- necessidade de múltiplos workers distribuídos em vários hosts
- aumento da criticidade operacional do sistema
- necessidade de workflows de processamento mais sofisticados

## Consequência prática imediata

A fundação do SIRHOSP será projetada sobre:

- Django
- PostgreSQL
- `uv`
- systemd timers/cron
- Django management commands
- Playwright

sem Redis e sem Celery na fase 1.
