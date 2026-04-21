# SLICE-S5 — Runbook + smoke script + fechamento da change

## Handoff de entrada (contexto zero)

Leia primeiro:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. artefatos da change `infra-compose-dev-prod-rootless`
4. `/tmp/sirhosp-slice-S4-report.md`

## Objetivo

Consolidar operação com documentação clara + script único de smoke,
**incluindo correção do warning/erro de permissões do Gunicorn em prod** (`Permission denied: '/.gunicorn'`).

## Escopo permitido

- `README.md` (seção de execução containerizada)
- `scripts/` para smoke test (ex.: `scripts/container-smoke.sh`)
- pequenos ajustes de compose para estabilidade de smoke
- `compose.prod.yml` e/ou `Dockerfile` para corrigir runtime path do Gunicorn em ambiente rootless
- atualização de `tasks.md` da change

## Escopo proibido

- alterar regras de negócio
- iniciar Fase B

## Limite de alteração

Máximo: **6 arquivos**.

## Estratégia de validação

Executar smoke completo (dev e prod local) e quality gate aplicável.

Mínimo esperado:

- stack sobe
- migrações aplicam
- `/health/` responde
- worker sobe sem crash
- logs do Gunicorn em prod sem `Permission denied: '/.gunicorn'`
- stack derruba sem resíduos inesperados

## Gate de saída obrigatório (S5)

1. Smoke script deve usar comportamento fail-fast (`set -e` ou equivalente) e retornar exit code != 0 em erro.
2. Executar smoke em modo dev e prod local com exit code 0 no cenário verde.
3. Registrar no relatório o comando executado, exit code e resumo de logs para cada modo.
4. Confirmar que após `down -v` não restam containers ativos da stack.
5. Em prod, validar explicitamente que o log do web **não** contém `Permission denied: '/.gunicorn'`.

Comando sugerido para o gate 5:

- `docker compose -f compose.yml -f compose.prod.yml logs web --tail=200 | grep -F "Permission denied: '/.gunicorn'"`
- esperado: **sem match** (exit code 1 do `grep`)

Regras:

- Se o smoke não falhar corretamente em cenário de erro simulado (ou não houver evidência), slice **não concluído**.
- Se não houver evidência de execução em ambos os modos (dev e prod), slice **não concluído**.
- Se houver ocorrência de `Permission denied: '/.gunicorn'` em logs, slice **não concluído**.

## Comandos de qualidade

- `uv run python manage.py check`
- `uv run pytest -q tests/integration/test_ingestion_http.py tests/integration/test_worker_lifecycle.py` (escopo mínimo)
- `uv run ruff check config apps tests manage.py`

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-S5-report.md` com checklist final,
evidência dos gates obrigatórios (dev/prod + Gunicorn), e recomendar próximo passo (abrir change Fase B).

Pare ao concluir o slice.
