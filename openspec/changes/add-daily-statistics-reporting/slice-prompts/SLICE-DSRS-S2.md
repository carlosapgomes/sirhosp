# SLICE-DSRS-S2 — Fotografia final materializada

## Handoff de entrada

Você inicia com contexto zero no repositório SIRHOSP após DSRS-S1 aceito. Leia
`AGENTS.md`, `PROJECT_CONTEXT.md`, `proposal.md`, as decisões 2, 3 e 7 de
`design.md`, os requisitos `A fotografia final preserva o contexto histórico
oficial` e `Relatórios diários são materializados e versionados`, e o relatório
`/tmp/sirhosp-slice-DSRS-S1-report.md`. Implemente somente este slice com TDD.
Não crie eventos clínicos, página, exportação ou backfill.

## Objetivo

Materializar atomicamente uma revisão diária contendo cabeçalho, agrupamentos
oficiais, métricas persistidas e pacientes do censo de fechamento, com
idempotência e uma única revisão corrente.

Decisão humana registrada durante a execução: expor em
`apps/census/occupancy.py` uma primitiva pública mínima que reutilize a
atribuição oficial existente de cada linha censitária ao agrupamento histórico,
inclusive a partição v5/v6 do código 654. Não duplicar essa regra no módulo de
relatórios.

## Requisitos verificáveis

- **R1:** schema preserva data Bahia, revisão, status, runs âncora/abertura/
  fechamento, medição, catálogo, algoritmo, fingerprint e qualidade.
- **R2:** cada setor usa chave/nome histórico e copia ou referencia somente
  métricas da medição exata; não recalcula capacidade, lotação, saldo ou
  excedente.
- **R3:** pacientes representam exclusivamente o censo de fechamento e mantêm
  procedência, leito, nome, prontuário e especialidade necessários ao relatório.
- **R4:** repetição com o mesmo fingerprint não duplica relatório, setor ou
  paciente.
- **R5:** publicação é atômica e existe no máximo uma revisão pronta corrente
  por data.
- **R6:** datas anteriores à ativação não são materializadas.

## Escopo e blast radius

```yaml
expected_files:
  - apps/census/occupancy.py
  - apps/statistics_reports/models.py
  - apps/statistics_reports/migrations/0001_initial.py
  - apps/statistics_reports/materialization.py
  - tests/integration/test_daily_statistics_materialization.py
allowed_incidental_files:
  - apps/statistics_reports/migrations/__init__.py
out_of_scope:
  - eventos de entrada ou saída
  - permissions UI, menu, views ou templates
  - XLSX e log de exportação
  - management commands e systemd
  - correções manuais e backfill histórico
```

Limite: seis arquivos contando o `__init__.py` incidental. A alteração em
`apps/census/occupancy.py` deve apenas expor/reutilizar a atribuição oficial já
existente e permanecer coberta pelo teste de integração deste slice. Pare se
for necessário modificar `CensusSnapshot`, medições de ocupação ou fontes
clínicas.

## Matriz requisito -> arquivo -> teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| R1, R5 | `models.py`, migration | constraints e publicação transacional |
| R2–R3 | `occupancy.py`, `materialization.py` | atribuição oficial, medição exata e roster do fechamento |
| R4 | ambos | rebuild idempotente sem duplicação |
| R6 | `materialization.py` | data pré-ativação recusada |

## Plano de testes

### RED

Crie os testes de integração antes dos modelos e execute:

```bash
./scripts/test-in-container.sh integration \
  tests/integration/test_daily_statistics_materialization.py
```

Falha esperada: tabelas/serviço inexistentes e ausência dos invariantes da
fotografia final.

### GREEN / verificação local

Implemente o mínimo, gere migration determinística e repita o RED. Depois:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

Inspecione a migration para confirmar constraints/índices e ausência de dados.

## Critérios de aceitação

- [ ] R1–R6 cobertos por testes RED→GREEN.
- [ ] A fotografia vem do fechamento, não do estado atual.
- [ ] Nenhuma fórmula oficial é duplicada.
- [ ] Relatório criado em `/tmp/sirhosp-slice-DSRS-S2-report.md`.
- [ ] Migration, checks e Markdown alterado passam.
