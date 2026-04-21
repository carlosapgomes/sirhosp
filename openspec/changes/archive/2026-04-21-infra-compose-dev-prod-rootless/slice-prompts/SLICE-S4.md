# SLICE-S4 — Modo deploy local (prod) com Gunicorn

## Handoff de entrada (contexto zero)

Leia primeiro:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. artefatos da change `infra-compose-dev-prod-rootless`
4. `/tmp/sirhosp-slice-S3-report.md`

## Objetivo

Implementar modo `prod` separado do `dev` com servidor web de produção.

## Escopo permitido

- `Dockerfile`
- `compose.prod.yml`
- dependência/runtime de produção (ex.: `pyproject.toml` + `uv.lock`, se necessário)
- scripts `docker/` de start para web/worker (se necessário)

## Escopo proibido

- alterações de domínio clínico
- Fase B
- infraestrutura fora do escopo Compose

## Limite de alteração

Máximo: **7 arquivos**.

## Estratégia de validação (RED/GREEN operacional)

1. RED: evidenciar ausência de modo prod funcional antes do ajuste.
2. GREEN:
   - build target prod ok;
   - `compose -f compose.yml -f compose.prod.yml up` ok;
   - `/health/` responde;
   - logs mostram web server de produção.

## Gate de saída obrigatório (S4)

Só marque o slice como concluído se **todos** os comandos abaixo passarem:

1. `docker compose -f compose.yml -f compose.prod.yml build web worker`
2. `docker compose -f compose.yml -f compose.prod.yml up -d db web worker`
3. `docker compose -f compose.yml -f compose.prod.yml ps`
4. `curl -fsS http://localhost:8000/health/`
5. `docker compose -f compose.yml -f compose.prod.yml logs web --tail=100` com evidência de Gunicorn (`gunicorn`/`Booting worker`).
6. `docker compose -f compose.yml -f compose.prod.yml down -v`

Regras:

- Sem evidência explícita de Gunicorn em logs, slice **não concluído**.
- Não vale apenas build de imagem; runtime `prod` é obrigatório.

## Observação

Se incluir nova dependência, atualizar lockfile de forma consistente.

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-S4-report.md` com evidências RED/GREEN, arquivos alterados, exit code e trecho de saída dos comandos do gate obrigatório.

Pare ao concluir o slice.
