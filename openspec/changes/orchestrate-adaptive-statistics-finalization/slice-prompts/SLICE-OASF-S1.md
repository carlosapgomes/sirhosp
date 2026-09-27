# SLICE-OASF-S1 — Revisão degradada auditável

## Handoff de entrada (contexto zero)

Você está em `/projects/dev/sirhosp`, branch de implementação do change
`orchestrate-adaptive-statistics-finalization`. Leia:

1. `AGENTS.md`, especialmente TDD, Stop Rule e relatório obrigatório;
2. `openspec/changes/orchestrate-adaptive-statistics-finalization/design.md`,
   decisões D2 e D3;
3. o MODIFIED requirement em
   `specs/daily-statistics-reporting/spec.md` deste change;
4. `apps/statistics_reports/materialization.py` e o comando
   `materialize_daily_statistics`;
5. `tests/integration/test_daily_statistics_command.py`.

Não implemente orquestração, Compose ou preflight neste slice.

## Objetivo

Permitir que uma materialização explícita de uma única data receba os avisos
operacionais allowlisted `d1_recovery_incomplete` e
`d1_recovery_not_confirmed`, persista-os na revisão e os inclua na impressão
digital. Uma reexecução sem aviso deve remover a degradação por meio da revisão
reproduzível normal. `--finalize` não pode propagar esses avisos para várias
datas.

## Requisitos verificáveis

- **R1:** `--date D --quality-warning <code>` aceita individualmente
  `d1_recovery_incomplete` e `d1_recovery_not_confirmed`, materializa D e
  persiste cada código uma única vez em `quality_warnings_json`.
- **R2:** o código operacional é combinado, deduplicado e ordenado com os
  avisos derivados existentes e participa de `source_fingerprint`.
- **R3:** repetir com o mesmo conjunto é no-op; executar depois sem os avisos
  gera ou reutiliza a revisão correta sem os códigos e supersede a degradada
  quando a fingerprint muda.
- **R4:** qualquer texto fora da allowlist falha antes da materialização;
  `--finalize` combinado com `--quality-warning` também falha fechado.
- **R5:** stdout/stderr continuam contendo apenas data, IDs técnicos, status,
  contagens e códigos enumerados; nada nominal pode ser copiado.
- **R6:** não há migration, alteração de modelo ou mudança nos gates de abertura
  e fechamento.

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| R1–R3 | `apps/statistics_reports/materialization.py`, comando de materialização | testes novos em `test_daily_statistics_command.py` |
| R4 | comando de materialização | testes de argumento inválido e conflito de modos |
| R5 | comando e teste | captura de stdout/stderr com fixture nominal sintética |
| R6 | materializador | `git diff --name-only`, integração existente e `makemigrations --check --dry-run` no gate final |

## Escopo e blast radius

```yaml
expected_files:
  - apps/statistics_reports/materialization.py
  - apps/statistics_reports/management/commands/materialize_daily_statistics.py
  - tests/integration/test_daily_statistics_command.py
allowed_incidental_files: []
max_changed_files: 3
out_of_scope:
  - apps/census/orchestration.py
  - compose.hospital.yml
  - deploy/
  - templates e XLSX, que já exibem a lista genérica de avisos persistidos
  - models e migrations
```

Se um quarto arquivo for necessário, ou se a solução exigir migration, campo
novo, texto livre ou mudança em `--finalize`, pare e reporte o bloqueio.

## Plano TDD

### RED

Adicione testes com nomes inequívocos cobrindo R1–R5. Execute primeiro o arquivo
focado no runner de testes em container. É aceitável usar um projeto Compose
temporário para o RED focado; registre o comando exato e a falha comportamental,
não apenas um erro de infraestrutura.

Comando focado esperado:

```bash
POSTGRES_PORT=55433 docker compose -p sirhosp-oasf-s1 \
  -f compose.yml -f compose.test.yml up -d --wait db
POSTGRES_PORT=55433 docker compose -p sirhosp-oasf-s1 \
  -f compose.yml -f compose.test.yml run --rm test-runner \
  bash -lc "uv run --no-sync pytest -q tests/integration/test_daily_statistics_command.py -k 'quality_warning or degraded'"
POSTGRES_PORT=55433 docker compose -p sirhosp-oasf-s1 \
  -f compose.yml -f compose.test.yml down --remove-orphans
```

Falha esperada: parser não conhece `--quality-warning` e/ou o aviso não entra na
revisão/fingerprint. O RED não pode decorrer de fixture quebrada.

### GREEN / refactor

Implemente o mínimo:

- allowlist fechada dos dois códigos e argumento do comando para data explícita;
- parâmetro imutável opcional na cadeia de materialização;
- união determinística dos avisos antes da fingerprint e persistência;
- rejeição antecipada de valor desconhecido e de `--finalize` com aviso.

Reexecute exatamente o subconjunto RED até ficar verde. Refatore apenas nomes e
reuso estritamente necessários.

### Verificação local do slice

```bash
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate orchestrate-adaptive-statistics-finalization --strict
```

## Critérios de aceitação

- [ ] R1–R6 possuem evidência automatizada.
- [ ] RED e GREEN do mesmo subconjunto estão registrados.
- [ ] `--finalize` anterior permanece inalterado e verde.
- [ ] Diff restrito aos três arquivos permitidos.
- [ ] Nenhuma migration ou dependência nova.
- [ ] `/tmp/sirhosp-slice-OASF-S1-report.md` contém resumo, checklist, arquivos,
      antes/depois por arquivo, comandos/resultados, riscos e próximo passo.

## Contrato de handoff

O worker não altera `tasks.md`, não commita e não inicia OASF-S2. Ao encontrar
ambiguidade nos dois códigos ou na semântica de revisão, deve parar em vez de
inventar outro estado persistido. O reviewer deve verificar comportamento,
testes, escopo e ausência de PHI; P0/P1 bloqueiam, P2 é report-only.
