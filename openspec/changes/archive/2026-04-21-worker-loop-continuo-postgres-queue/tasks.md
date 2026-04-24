<!-- markdownlint-disable MD013 -->

# Tasks: worker-loop-continuo-postgres-queue

## 1. Slice S1 - Worker contínuo (loop + sleep)

Escopo: eliminar flapping do worker no compose usando loop contínuo com polling no PostgreSQL.

Limite: até 5 arquivos alterados.

Prompt executor: `slice-prompts/SLICE-S1.md`.

- [x] 1.1 (RED operacional) Demonstrar estado atual de restart contínuo do worker em ambiente sem fila pendente.
- [x] 1.2 Implementar modo contínuo no command `process_ingestion_runs` com flags `--loop` e `--sleep-seconds`.
- [x] 1.3 Ajustar `compose.dev.yml` para usar worker em loop contínuo.
- [x] 1.4 Ajustar `compose.prod.yml` para usar worker em loop contínuo.
- [x] 1.5 **Gate obrigatório S1**: comprovar worker `Up` estável (sem restart flapping) por pelo menos 20s sem fila.
- [x] 1.6 **Gate obrigatório S1**: criar run `queued` e comprovar transição para estado terminal com logs do worker.
- [x] 1.7 Executar checks relevantes e gerar `/tmp/sirhosp-slice-WL1-report.md`.
