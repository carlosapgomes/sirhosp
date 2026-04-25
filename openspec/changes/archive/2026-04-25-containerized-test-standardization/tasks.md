<!-- markdownlint-disable MD013 -->
# Tasks: containerized-test-standardization

## 1. Slice S1 - Infra base para testes em container

Escopo: criar suíte de teste compose e entrypoint de execução em container.

Limite: até **6 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S1.md`.

- [x] 1.1 (RED) Demonstrar falha atual do comando oficial de pytest no host (erro de infraestrutura).
- [x] 1.2 Criar `compose.test.yml` com serviço `test-runner` conectado ao `db`.
- [x] 1.3 Criar `scripts/test-in-container.sh` com `up/wait/run/down` e subcomandos básicos (`check`, `unit`, `lint`, `typecheck`).
- [x] 1.4 (GREEN) Executar `check` + `unit` via container com sucesso.
- [x] 1.5 **Gate obrigatório S1**:
  - `docker compose -f compose.yml -f compose.test.yml config`
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
- [x] 1.6 Gerar `/tmp/sirhosp-slice-CTS-S1-report.md`.

## 2. Slice S2 - Padronização dos comandos oficiais do projeto

Escopo: tornar o fluxo containerizado o caminho oficial em docs e comandos de equipe.

Limite: até **6 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S2.md`.

- [x] 2.1 (RED) Identificar comandos oficiais atuais que dependem de ambiente host.
- [x] 2.2 Atualizar `AGENTS.md` seção de Quality Gate para comandos containerizados.
- [x] 2.3 Atualizar `README.md` com seção "Testes em container (oficial)".
- [ ] 2.4 (Opcional) Adicionar `Makefile` mínimo (`test`, `test-unit`, `quality-gate`) apontando para o script.
- [x] 2.5 **Gate obrigatório S2**:
  - `./scripts/test-in-container.sh check`
  - `./scripts/test-in-container.sh unit`
  - `./scripts/test-in-container.sh lint`
  - `./scripts/test-in-container.sh typecheck`
  - `./scripts/markdown-lint.sh` (se `.md` alterado)
- [x] 2.6 Gerar `/tmp/sirhosp-slice-CTS-S2-report.md`.

## 3. Slice S3 - CI alinhado com a mesma suíte de container

Escopo: configurar pipeline para usar exatamente o mesmo entrypoint local.

Limite: até **5 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S3.md`.

- [x] 3.1 (RED) Criar pipeline CI mínimo falhando por ausência de workflow/comando.
- [x] 3.2 Adicionar workflow (ex.: `.github/workflows/quality-gate.yml`) executando script containerizado.
- [x] 3.3 Garantir teardown e coleta de logs em caso de falha.
- [x] 3.4 (GREEN) Validar sintaxe do workflow e execução local equivalente.
- [x] 3.5 **Gate obrigatório S3**:
  - `./scripts/test-in-container.sh quality-gate`
  - validação YAML do workflow (ferramenta disponível no ambiente)
- [x] 3.6 Gerar `/tmp/sirhosp-slice-CTS-S3-report.md`.

## 4. Slice S4 - Hardening operacional e transição limpa

Escopo: remover ambiguidades e registrar fallback explícito para diagnóstico.

Limite: até **6 arquivos alterados**.

Prompt executor: `slice-prompts/SLICE-S4.md`.

- [x] 4.1 Definir política clara: host-level `pytest` é diagnóstico, não gate oficial.
- [x] 4.2 Adicionar troubleshooting no README (Docker indisponível, porta ocupada, healthcheck timeout).
- [x] 4.3 Revisar prompts e docs de execução de slices para referenciar comandos containerizados.
- [x] 4.4 **Gate obrigatório S4**:
  - `./scripts/test-in-container.sh quality-gate`
  - `uv run python manage.py check` (somente sanity local)
  - `./scripts/markdown-lint.sh` (se `.md` alterado)
- [x] 4.5 Gerar `/tmp/sirhosp-slice-CTS-S4-report.md`.

## Stop Rule

- Implementar **um slice por vez**.
- Encerrar cada slice com relatório obrigatório e aguardar decisão explícita para o próximo.
