# Design: containerized-test-standardization

## Contexto

O projeto já possui stack Docker Compose com `db` e overrides para dev/prod.
O problema atual não é de domínio clínico; é operacional de testes:

- `pytest` direto no host exige PostgreSQL acessível com configuração consistente;
- `POSTGRES_HOST=db` funciona dentro da rede Compose, mas não no host;
- o comando oficial fica frágil fora do contexto correto.

## Objetivos de design

1. Um único caminho oficial de execução de gates.
2. Infraestrutura de teste autogerenciada (up/wait/run/down).
3. Mesmo mecanismo local e CI.
4. Mudança incremental (sem big-bang).

## Arquitetura proposta

### 1) Compose de testes dedicado

Criar `compose.test.yml` com serviço `test-runner` (sem exposição de portas) usando imagem dev do projeto.

Responsabilidades:

- compartilhar código do repositório via volume;
- apontar `POSTGRES_HOST=db` internamente;
- executar comandos de validação (`manage.py check`, `pytest`, `ruff`, `mypy`) via `uv run`.

### 2) Entry point único para quality gate

Criar `scripts/test-in-container.sh` com subcomandos previsíveis:

- `check`
- `unit`
- `integration`
- `lint`
- `typecheck`
- `quality-gate` (check + unit/integration + lint + typecheck)

Fluxo padrão do script:

1. `docker compose -f compose.yml -f compose.test.yml up -d db`
2. aguarda healthcheck do banco
3. `docker compose ... run --rm test-runner <comando>`
4. teardown (`down`) automático no `trap EXIT`

### 3) Padronização documental

Atualizar `AGENTS.md` e `README.md` para declarar explicitamente:

- comando oficial de teste é o script/container;
- execução direta de `pytest` no host é não-oficial (diagnóstico local).

### 4) CI alinhado ao mesmo contrato

Adicionar workflow CI usando o **mesmo script** para evitar duplicação de lógica.

## Decisões

### D1 — Não interceptar `pytest` puro automaticamente

Não vamos "enganchar" `pytest` com auto-start de Docker por hook em `conftest.py`.

Motivo:

- comportamento mágico e surpreendente;
- mais difícil de depurar;
- pior para ambientes sem Docker.

### D2 — Caminho oficial = wrapper/script

Toda automação (LLM executor inclusive) usa script de container.

Motivo:

- comportamento explícito;
- fácil de registrar em relatórios de slice;
- convergência local/CI.

## Trade-offs

- **Pró:** previsibilidade e isolamento operacional.
- **Contra:** execução pode ficar um pouco mais lenta.
- **Mitigação:** cache de imagem e dependências; uso de `run --rm` enxuto.

## Rollout

- S1: infraestrutura de teste containerizada mínima funcionando.
- S2: migração dos comandos oficiais e documentação.
- S3: integração em CI com mesmo entrypoint.
- S4: hardening/guardrails e limpeza de legado operacional.
