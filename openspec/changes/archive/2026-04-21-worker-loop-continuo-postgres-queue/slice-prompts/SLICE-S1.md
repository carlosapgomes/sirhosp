# SLICE-S1 — Worker contínuo (loop + sleep)

## Handoff de entrada (contexto zero)

Leia primeiro:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/worker-loop-continuo-postgres-queue/proposal.md`
4. `openspec/changes/worker-loop-continuo-postgres-queue/design.md`
5. `openspec/changes/worker-loop-continuo-postgres-queue/tasks.md`

## Objetivo

Eliminar restart flapping do worker no compose e manter processamento contínuo de fila PostgreSQL via polling.

## Escopo permitido

- `apps/ingestion/management/commands/process_ingestion_runs.py`
- `compose.dev.yml`
- `compose.prod.yml`
- ajuste mínimo de documentação inline no próprio command (se necessário)

## Escopo proibido

- alterar domínio clínico (models/services/views/templates)
- Celery/Redis
- qualquer escopo de Fase B

## Limite de alteração

Máximo: **5 arquivos**.

## Implementação esperada

1. No command `process_ingestion_runs`, adicionar argumentos:
   - `--loop` (bool)
   - `--sleep-seconds` (int, default 5)
2. Com `--loop`, manter processo vivo:
   - processar queued runs
   - se não houver runs, dormir `sleep-seconds`
   - repetir
3. Sem `--loop`, manter comportamento one-shot atual para compatibilidade.
4. Ajustar `compose.dev.yml` e `compose.prod.yml` worker command para:
   - `uv run --no-sync python manage.py process_ingestion_runs --loop --sleep-seconds 5`

## RED/GREEN operacional

### RED obrigatório

- Subir stack atual e mostrar worker em restart flapping (`docker compose ... ps -a`).

### GREEN obrigatório

- Worker em loop permanece `Up` estável por 20s sem fila pendente.
- Criar run `queued` e observar worker processar para estado terminal.

## Gate obrigatório S1

Registrar comandos + exit code + trecho de saída:

1. `docker compose -f compose.yml -f compose.dev.yml up -d --build db web worker`
2. `docker compose -f compose.yml -f compose.dev.yml exec -T web uv run --no-sync python manage.py migrate`
3. `docker compose -f compose.yml -f compose.dev.yml ps -a` (esperado: worker `Up`, sem `Restarting`)
4. Aguardar 20s e repetir `ps -a` (continuar `Up`)
5. Criar run queued via shell do web e guardar ID
6. Consultar status da run após até 15s (esperado: terminal)
7. `docker compose -f compose.yml -f compose.dev.yml logs worker --tail=120`
8. `docker compose -f compose.yml -f compose.dev.yml down -v`

Regras:

- Se worker aparecer em `Restarting` após ajustes, slice **não concluído**.
- Se run não sair de `queued` no cenário verde, slice **não concluído**.

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-WL1-report.md` com:

- resumo do que mudou;
- arquivos alterados (contagem);
- before/after dos trechos críticos;
- tabela dos 8 comandos de gate com exit code;
- conclusão objetiva (aprovado/reprovado);
- próximo passo sugerido.

Pare ao concluir o slice.
