# SLICE-DSRS-S1 — Seleção do dia estatístico

## Handoff de entrada

Você inicia com contexto zero no repositório SIRHOSP. Leia `AGENTS.md`,
`PROJECT_CONTEXT.md`, `proposal.md`, as decisões 1, 2 e 6 de `design.md` e os
três primeiros requisitos da delta spec `daily-statistics-reporting`. Confirme
que o preflight e a ADR exigidos em `tasks.md` foram concluídos. Implemente
somente este slice com TDD e dados sintéticos. Não acesse produção nem execute
backfill.

## Objetivo

Entregar um serviço puro e testado que selecione âncora, censo de abertura e
censo de fechamento de uma data Bahia, distinguindo censos aceitos dos lotes
clínicos e explicando por que um dia não está completo.

## Requisitos verificáveis

- **R1:** abertura é o primeiro censo aceito concluído em `[00:00, 03:00)`;
  ele pode ter iniciado no dia anterior.
- **R2:** fechamento é o último censo aceito iniciado a partir de 20:00 e
  concluído antes da meia-noite; abertura e fechamento são distintos.
- **R3:** âncora é o último censo aceito anterior à abertura e sua ausência gera
  qualidade degradada sem inventar movimentos.
- **R4:** censo aceito exige sucesso, snapshots completos de procedência única e
  medição oficial exata; medição antiga ou mista é rejeitada.
- **R5:** `CensusExecutionBatch.finished_at` não participa da seleção.
- **R6:** limites usam explicitamente `America/Bahia` e retornam motivo
  estruturado para dia incompleto.

## Escopo e blast radius

```yaml
expected_files:
  - apps/statistics_reports/__init__.py
  - apps/statistics_reports/apps.py
  - apps/statistics_reports/selection.py
  - config/settings.py
  - tests/unit/test_daily_statistics_window.py
allowed_incidental_files: []
out_of_scope:
  - models e migrations da projeção
  - derivação de eventos
  - página, menu e XLSX
  - systemd, ativação ou backfill
  - correções manuais
```

Limite: cinco arquivos. Pare e reporte bloqueio se a seleção exigir alterar
modelos de domínio, regras de completude existentes ou `CensusExecutionBatch`.

## Matriz requisito -> arquivo -> teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| R1–R3 | `selection.py` | testes de abertura, fechamento e âncora |
| R4–R5 | `selection.py` | testes de procedência e batch tardio |
| R6 | `selection.py` | testes de meia-noite Bahia e motivo incompleto |

## Plano de testes

### RED

Crie primeiro `tests/unit/test_daily_statistics_window.py` e execute:

```bash
./scripts/test-in-container.sh unit \
  tests/unit/test_daily_statistics_window.py
```

Falha esperada: módulo/contrato de seleção inexistente ou seleção ainda incapaz
de cumprir os limites e a procedência exata.

### GREEN / verificação local

Implemente o mínimo e repita o comando RED. Depois execute:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

## Critérios de aceitação

- [ ] R1–R6 possuem cobertura sintética que falhou antes e passa depois.
- [ ] Nenhum relatório é persistido neste slice.
- [ ] Nenhum dado real, backfill ou regra clínica foi alterado.
- [ ] Relatório criado em `/tmp/sirhosp-slice-DSRS-S1-report.md`.
- [ ] `./scripts/markdown-lint.sh` passa para Markdown alterado.
