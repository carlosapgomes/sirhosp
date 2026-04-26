# Tasks: infra-compose-dev-prod-rootless

## 1. Slice S1 - Base de imagem container (dev/prod targets)

Escopo: criar base de build da aplicação com Dockerfile multi-stage e `.dockerignore`.

Limite: até 5 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S1.md`.

- [x] 1.1 (RED operacional) Demonstrar falha inicial de build inexistente ou incompleta.
- [x] 1.2 Criar `Dockerfile` com targets nomeados `dev` e `prod`.
- [x] 1.3 Criar `.dockerignore` para reduzir contexto e evitar vazamento de artefatos locais.
- [x] 1.4 Definir entrypoint/script mínimo para execução consistente no container.
- [x] 1.5 Validar `compose build`/`docker build` dos targets e gerar `/tmp/sirhosp-slice-S1-report.md`.

## 2. Slice S2 - Stack dev mínima (db + web)

Escopo: subir PostgreSQL e web em modo desenvolvimento com acesso via browser do host.

Limite: até 6 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S2.md`.

- [x] 2.1 (RED operacional) `compose up` deve falhar antes da configuração da stack.
- [x] 2.2 Criar `compose.yml` com serviço `db` (volume persistente, healthcheck).
- [x] 2.3 Criar `compose.dev.yml` com serviço `web` em modo dev (bind mount + runserver).
- [x] 2.4 Padronizar variáveis em arquivo de exemplo (ex.: `.env.docker.example`).
- [x] 2.5 Validar `migrate`, `check` e acesso a `/health/`.
- [x] 2.6 **Gate obrigatório S2**: comprovar runtime real do `web` (não só build) com stack `up -d`, `manage.py check` dentro do container, `curl` em `/health/` e evidência de `docker compose ps`.
- [x] 2.7 Gerar `/tmp/sirhosp-slice-S2-report.md` com saída dos comandos de gate.

## 2.1 Slice S2.1 - Hardening do `uv` no Docker (sem `.venv` no bind mount)

Escopo: manter `uv` como runtime oficial também no container, evitando conflitos de permissão com `.:/app` em ambiente rootless.

Limite: até 4 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S2-1.md`.

- [x] 2.1.1 (RED operacional) Demonstrar falha/risco atual: runtime dependente de `python` direto ou conflito potencial com `.venv` em `/app`.
- [x] 2.1.2 Configurar ambiente do `uv` fora do bind mount (ex.: `UV_PROJECT_ENVIRONMENT=/opt/venv` e cache em diretório gravável pelo usuário do container).
- [x] 2.1.3 Remover instalação manual de pacotes via `uv pip install ...` hardcoded no Dockerfile e voltar para sincronização via lockfile (`uv sync --frozen ...`).
- [x] 2.1.4 Ajustar comandos de runtime para usar `uv run --no-sync` (dev e, quando aplicável, prod) sem recriar `.venv` em `/app`.
- [x] 2.1.5 **Gate obrigatório S2.1**: comprovar que `uv` executa `manage.py check` dentro do container, `/health/` responde e o runtime usa explicitamente `/opt/venv` (`sys.prefix`), mesmo que exista `/app/.venv` vindo do bind mount.
- [x] 2.1.6 Gerar `/tmp/sirhosp-slice-S2-1-report.md` com comandos, exit code e evidências dos gates.

## 3. Slice S3 - Serviço worker no ambiente dev

Escopo: adicionar worker no Compose dev para processar `IngestionRun` sem intervenção manual contínua.

Limite: até 5 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S3.md`.

- [x] 3.1 (RED operacional) Criar run sob demanda e evidenciar que fica presa sem worker.
- [x] 3.2 Adicionar serviço `worker` em `compose.dev.yml` com comando estável.
- [x] 3.3 Garantir dependência/ordem de inicialização mínima entre `db`, `web`, `worker`.
- [x] 3.4 Validar fluxo manual ponta-a-ponta: criar run e observar transição de status.
- [x] 3.5 **Gate obrigatório S3**: comprovar que sem `worker` a run fica `queued`, depois com `worker` vai para estado terminal (`succeeded|failed`) com evidência em logs e consulta de status.
- [x] 3.6 Gerar `/tmp/sirhosp-slice-S3-report.md` com saída dos comandos de gate.

## 4. Slice S4 - Modo deploy local (prod) com Gunicorn

Escopo: configurar execução de produção local com Compose específico.

Limite: até 7 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S4.md`.

- [x] 4.1 (RED operacional) provar ausência de comando de produção antes do ajuste.
- [x] 4.2 Incluir runtime web de produção (Gunicorn) no empacotamento.
- [x] 4.3 Criar `compose.prod.yml` com `web` target `prod` e comando de produção.
- [x] 4.4 Ajustar worker para modo compatível com deploy local.
- [x] 4.5 Validar startup `prod` + `/health/`.
- [x] 4.6 **Gate obrigatório S4**: comprovar runtime `prod` com evidência explícita de Gunicorn em logs + `curl` `/health/` + `docker compose ps`.
- [x] 4.7 Gerar `/tmp/sirhosp-slice-S4-report.md` com saída dos comandos de gate.

## 5. Slice S5 - Runbook operacional + smoke script

Escopo: consolidar documentação e script de validação rápida para dev/prod.

Limite: até 6 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S5.md`.

- [x] 5.1 Criar script de smoke test containerizado (build/up/check/health/down).
- [x] 5.2 Atualizar README com instruções de dev e deploy local via Compose.
- [x] 5.3 Corrigir warning/erro de permissões do Gunicorn em prod (`Permission denied: '/.gunicorn'`) com diretório de runtime gravável (ex.: `/tmp`) e configuração explícita.
- [x] 5.4 Documentar notas de rootless (Docker/Podman) e troubleshooting essencial.
- [x] 5.5 Executar quality gate aplicável e smoke script final.
- [x] 5.6 **Gate obrigatório S5**: smoke script deve falhar com código != 0 em erro e encerrar com código 0 no cenário verde (dev e prod), com evidência de saída.
- [x] 5.7 **Gate obrigatório S5 (Gunicorn)**: logs do `web` em modo prod não devem conter `Permission denied: '/.gunicorn'`.
- [x] 5.8 Gerar `/tmp/sirhosp-slice-S5-report.md` com checklist final + logs resumidos do smoke.
