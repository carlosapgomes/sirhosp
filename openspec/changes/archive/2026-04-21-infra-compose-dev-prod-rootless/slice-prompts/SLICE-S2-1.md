# SLICE-S2.1 — Hardening do `uv` no Docker (rootless + bind mount)

## Handoff de entrada (contexto zero)

Leia primeiro:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/infra-compose-dev-prod-rootless/proposal.md`
4. `openspec/changes/infra-compose-dev-prod-rootless/design.md`
5. `openspec/changes/infra-compose-dev-prod-rootless/tasks.md`
6. `/tmp/sirhosp-slice-S2-report.md`

## Contexto do problema

No S2, a stack dev subiu, porém o Dockerfile foi para caminho de instalação manual (`uv pip install ...` hardcoded + `python manage.py ...`) para contornar conflitos de permissão com `.venv` em ambiente rootless com bind mount `.:/app`.

Objetivo deste mini-slice: **manter `uv` também no runtime do container**, sem usar `.venv` em `/app`.

## Objetivo

Padronizar `uv` no Docker dev/prod sem drift de dependências, usando lockfile e ambiente virtual fora do bind mount.

## Escopo permitido

- `Dockerfile`
- `compose.dev.yml`
- `compose.prod.yml` (somente se necessário para manter consistência de runtime)
- `docker/entrypoint.sh` (somente se estritamente necessário)

## Escopo proibido

- regras de negócio, models, migrations, views, templates
- introduzir ferramentas fora do escopo (Celery/Redis/k8s)
- mexer em fases funcionais (Fase B)

## Limite de alteração

Máximo: **4 arquivos**.

Se precisar de mais, **pare e reporte bloqueio**.

## Implementação esperada (diretriz obrigatória)

1. Configurar ambiente do `uv` fora de `/app`, por exemplo:
   - `UV_PROJECT_ENVIRONMENT=/opt/venv`
   - `UV_CACHE_DIR` em diretório gravável pelo usuário não-root
2. No build, instalar dependências via lockfile (`uv sync --frozen ...`), evitando lista manual hardcoded de pacotes.
3. No runtime, usar `uv run --no-sync ...` para evitar sync implícito e recriação de ambiente.
4. Garantir que com bind mount `.:/app` o runtime do container use `/opt/venv` (via `UV_PROJECT_ENVIRONMENT`), mesmo que `/app/.venv` exista por vir do host.

## RED/GREEN operacional

### RED (obrigatório)

Demonstrar o risco/estado atual (antes do ajuste), com pelo menos uma evidência:

- comando de runtime sem `uv` (uso de `python manage.py ...`), ou
- evidência de tentativa de uso de `.venv` em `/app`, ou
- dependências fora do lockfile (instalação manual hardcoded).

### GREEN (obrigatório)

Após ajuste, comprovar runtime com `uv` + health da stack.

## Gate de saída obrigatório (S2.1)

Só marque concluído se **todos** passarem com exit code 0.

1. `docker compose -f compose.yml -f compose.dev.yml up -d --build db web`
2. `docker compose -f compose.yml -f compose.dev.yml exec -T web sh -lc 'echo $UV_PROJECT_ENVIRONMENT && test -d "$UV_PROJECT_ENVIRONMENT"'`
3. `docker compose -f compose.yml -f compose.dev.yml exec -T web uv run --no-sync python -c 'import sys; print(sys.prefix)'` (deve imprimir `/opt/venv`)
4. `docker compose -f compose.yml -f compose.dev.yml exec -T web uv run --no-sync python manage.py check`
5. `curl -fsS http://localhost:8000/health/`
6. `docker compose -f compose.yml -f compose.dev.yml down -v`

Regras de aceite:

- Se qualquer comando falhar, slice = **não concluído**.
- Sem evidência de `uv run --no-sync` em runtime, slice = **não concluído**.
- Se `sys.prefix` não apontar para `/opt/venv`, slice = **não concluído**.
- A existência de `/app/.venv` (quando vinda do bind mount do host) **não reprova** o slice por si só.

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-S2-1-report.md` com:

- resumo objetivo;
- arquivos alterados (com contagem total);
- before/after dos trechos críticos;
- tabela dos 6 comandos de gate com exit code;
- evidência explícita de `sys.prefix=/opt/venv` no runtime (`uv run --no-sync`);
- riscos remanescentes + próximo passo (S3).

Pare ao concluir o slice.
