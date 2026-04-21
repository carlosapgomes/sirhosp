# SLICE-S3 — Worker no ambiente dev

## Handoff de entrada (contexto zero)

Leia primeiro:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. artefatos da change `infra-compose-dev-prod-rootless`
4. `/tmp/sirhosp-slice-S2-report.md`

## Objetivo

Adicionar serviço `worker` no Compose dev para processar `IngestionRun`.

## Escopo permitido

- `compose.dev.yml` (principal)
- script de startup do worker em `docker/` (se necessário)
- ajuste mínimo em `compose.yml` para dependências/healthchecks

## Escopo proibido

- mexer em domínio de ingestão (models/services/gap planner)
- alterar endpoints/templates além de necessidade operacional de startup

## Limite de alteração

Máximo: **5 arquivos**.

## Estratégia de validação (RED/GREEN operacional)

1. RED: com stack sem worker, demonstrar run presa em `queued`.
2. GREEN:
   - subir worker;
   - criar run via UI;
   - observar transição de status (running -> terminal).

## Gate de saída obrigatório (S3)

Só marque o slice como concluído se **todos** os itens abaixo forem comprovados:

1. Subir stack sem worker e criar run: evidência de status `queued` persistente.
2. Subir worker e reprocessar: run deve sair de `queued` para estado terminal (`succeeded` ou `failed`).
3. Capturar logs do worker com processamento da run (`docker compose logs worker --tail=100`).
4. Encerrar stack (`down -v`) sem erro.

Regras:

- É obrigatório mostrar IDs de run usados na validação.
- Se não houver prova de transição de status + logs, slice **não concluído**.

## Evidências mínimas esperadas

- logs do worker processando run
- captura de status antes/depois (ou saída de comando equivalente)

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-S3-report.md` com:

- comandos;
- evidências RED/GREEN;
- evidência dos gates obrigatórios (status queued antes, terminal depois, logs worker);
- arquivos alterados;
- riscos/pendências.

Pare ao concluir o slice.
