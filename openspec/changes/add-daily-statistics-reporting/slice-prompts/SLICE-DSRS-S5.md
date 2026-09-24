# SLICE-DSRS-S5 — Fechamento diário operacional

## Handoff de entrada

Você inicia com contexto zero após DSRS-S4 aceito. Leia `AGENTS.md`,
`PROJECT_CONTEXT.md`, `proposal.md`, as decisões 3 e 11 de `design.md`, os
requisitos de materialização/versionamento e os relatórios S1–S4 em `/tmp`.
Implemente somente comandos de materialização por data e finalização limitada.
Não adicione systemd, UI, XLSX, backfill ou correção manual.

## Objetivo

Expor um management command seguro e idempotente que materialize uma data
explícita ou finalize datas elegíveis pós-ativação, com coordenação PostgreSQL,
falha atômica e saída operacional sem identidade clínica.

## Requisitos verificáveis

- **R1:** `--date` materializa somente a data Bahia solicitada e retorna resumo
  agregado de revisão/status/contagens.
- **R2:** modo de finalização automática considera somente datas encerradas,
  completas e iguais/posteriores à data de ativação; nunca seleciona hoje.
- **R3:** repetição sem mudança é no-op idempotente; evidência mudada usa a
  revisão automática definida no slice anterior.
- **R4:** concorrência não publica duas revisões correntes nem executa o mesmo
  fechamento sem coordenação.
- **R5:** falha deixa a revisão pronta anterior intacta e retorna erro seguro.
- **R6:** dia incompleto ou degradado é relatado estruturalmente sem inventar
  dados; nenhum rebuild histórico implícito ocorre.
- **R7:** stdout/stderr/logs contêm apenas IDs técnicos, datas, status e
  contagens agregadas.

## Escopo e blast radius

```yaml
expected_files:
  - apps/statistics_reports/management/__init__.py
  - apps/statistics_reports/management/commands/__init__.py
  - apps/statistics_reports/management/commands/materialize_daily_statistics.py
  - apps/statistics_reports/materialization.py
  - config/settings.py
  - tests/integration/test_daily_statistics_command.py
allowed_incidental_files: []
out_of_scope:
  - systemd e documentação de deploy
  - página, menu, XLSX e export logs
  - execução ou inspeção de produção
  - backfill pré-ativação e correções manuais
```

Limite: seis arquivos. Pare se a solução exigir Celery/Redis, mutação de runs de
origem ou lock fora do PostgreSQL.

## Matriz requisito -> arquivo -> teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| R1–R3 | command, materializer | testes por data/finalização/no-op |
| R4–R5 | materializer/command | concorrência e rollback transacional |
| R6–R7 | command | datas incompletas e captura de stdout/log |

## Plano de testes

### RED

Adicione os testes antes do comando e execute:

```bash
./scripts/test-in-container.sh integration \
  tests/integration/test_daily_statistics_command.py
```

Falha esperada: command inexistente e ausência dos contratos de ativação,
idempotência e falha segura.

### GREEN / verificação local

Implemente o mínimo e repita o RED. Depois:

```bash
./scripts/test-in-container.sh integration \
  tests/integration/test_daily_statistics_materialization.py \
  tests/integration/test_daily_statistics_entries.py \
  tests/integration/test_daily_statistics_exits.py
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

## Critérios de aceitação

- [ ] R1–R7 cobertos por RED→GREEN.
- [ ] Nenhuma data pré-ativação ou hoje é finalizada automaticamente.
- [ ] Logs de teste não contêm nomes ou prontuários sintéticos.
- [ ] Relatório criado em `/tmp/sirhosp-slice-DSRS-S5-report.md`.
- [ ] Checks e Markdown alterado passam.
