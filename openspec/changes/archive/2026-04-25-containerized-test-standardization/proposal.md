# Change Proposal: containerized-test-standardization

## Why

Hoje os gates de qualidade dependem de PostgreSQL acessível no host local.
Na prática, o comando oficial de teste pode falhar por resolução de host (`POSTGRES_HOST=db`) quando executado fora da rede Docker Compose.

Para quem opera múltiplos projetos em paralelo (inclusive com LLM executando slices), essa dependência manual de infraestrutura aumenta muito a carga operacional e gera falhas não determinísticas.

## What Changes

Padronizar a execução de testes e quality gates para rodar **sempre em container**, com orquestração automática de infraestrutura de teste.

- Criar suíte de teste em Docker Compose (`compose.test.yml`) com serviço `test-runner`.
- Criar entrypoint único de execução (`scripts/test-in-container.sh`) para:
  - subir dependências (db),
  - aguardar healthcheck,
  - executar comando de validação,
  - derrubar stack ao final.
- Atualizar comandos oficiais no `AGENTS.md` e `README.md` para usar a suíte em container.
- (Opcional/fase final) configurar CI para usar o mesmo entrypoint e evitar divergência local x CI.

## Non-Goals

- Não alterar regras de negócio, models ou fluxo clínico.
- Não migrar aplicação para "100% container-only" em desenvolvimento de código.
- Não remover imediatamente comandos locais auxiliares (fallback), apenas rebaixá-los de "oficiais" para "diagnóstico".

## Capabilities

### Added Capabilities

- `developer-quality-gates`: execução determinística e padronizada de quality gates em container, sem dependência de setup manual de banco no host.

## Impact

- Reduz falhas por ambiente (`host db`, `porta ocupada`, `serviço não iniciado`).
- Permite delegação segura para LLMs: o próprio executor sobe e derruba o ambiente de teste.
- Alinha caminho local e CI, reduzindo drift operacional.
