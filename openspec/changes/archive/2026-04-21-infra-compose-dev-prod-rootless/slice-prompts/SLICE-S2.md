# SLICE-S2 — Stack dev mínima (db + web)

## Handoff de entrada (contexto zero)

Leia primeiro:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/infra-compose-dev-prod-rootless/proposal.md`
4. `openspec/changes/infra-compose-dev-prod-rootless/design.md`
5. `openspec/changes/infra-compose-dev-prod-rootless/tasks.md`
6. relatório anterior `/tmp/sirhosp-slice-S1-report.md`

## Objetivo

Subir ambiente dev com PostgreSQL + web Django acessível no browser do host.

## Escopo permitido

- `compose.yml`
- `compose.dev.yml`
- `.env.docker.example` (ou equivalente)
- eventual ajuste mínimo em script de entrypoint criado no S1

## Escopo proibido

- Fase B
- alteração de regras de negócio/modelos
- criação de infraestrutura fora de Compose (k8s, celery, redis)

## Limite de alteração

Máximo: **6 arquivos**.

## Estratégia de validação (RED/GREEN operacional)

1. RED: `compose up` falha por ausência de stack dev completa.
2. GREEN:
   - stack sobe;
   - `uv run python manage.py check` (dentro do web) passa;
   - `/health/` responde no host.

## Gate de saída obrigatório (S2)

Só marque o slice como concluído se **todos** os comandos abaixo passarem.

1. `docker compose -f compose.yml -f compose.dev.yml up -d --build db web`
2. `docker compose -f compose.yml -f compose.dev.yml ps`
3. `docker compose -f compose.yml -f compose.dev.yml exec -T web uv run python manage.py migrate`
4. `docker compose -f compose.yml -f compose.dev.yml exec -T web uv run python manage.py check`
5. `curl -fsS http://localhost:8000/health/`
6. `docker compose -f compose.yml -f compose.dev.yml down -v`

Regras:

- Se qualquer comando falhar (exit code != 0), o slice fica **não concluído**.
- Não vale evidência só de `docker build`; runtime é obrigatório.

## Comandos mínimos sugeridos

- build/up de `db` e `web`
- migrate (se necessário)
- check
- curl/browser em `/health/`
- down ao final

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-S2-report.md` com evidências RED/GREEN, lista de arquivos alterados, **exit code** e trecho de saída dos 6 comandos do gate obrigatório.

Pare ao concluir o slice.
