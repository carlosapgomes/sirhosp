# SLICE-OIDR-S1 — Passo intraday throttled no loop do orquestrador

## Objetivo

O `run_loop` em `apps/census/orchestration.py` passa a disparar
`call_command("run_exit_reconciliation_runtime", "--mode", "hourly")`
in-process, no bloco elegível, **depois do passo D-1 (quando ambos
disparam) e antes de `run_single_cycle`**, no máximo **uma vez por hora
local `America/Bahia`** por execução do processo. Falha nunca bloqueia o
ciclo. Padrão idêntico ao passo D-1 existente (ADR-0010) — leia o bloco
`Quiet-window D-1` no arquivo antes de editar.

## Contexto necessário

- `apps/census/orchestration.py` — `run_loop` (o passo D-1 e `now_fn`
  já existem; reutilize `BAHIA_TZ`, `_now_fn` e o estilo de try/except).
- `tests/unit/test_orchestrator_quiet_window_d1.py` — padrão de mocks
  (`_run_loop` com `now_sequence`, patches de
  `apps.census.orchestration.call_command` e `run_single_cycle`).
- `openspec/changes/orchestrate-intraday-discharge-recovery/design.md`
  (decisões D1–D5).

## Requisitos verificáveis

- R1: iteração elegível com hora local Bahia ≠ `last_hourly_run_hour`
  executa o hourly ANTES de `run_single_cycle` (e DEPOIS do passo D-1,
  quando o D-1 também disparar); início e fim do passo são logados em
  nível info com hora local e duração (assert com `caplog`, padrão do
  teste `test_success_emits_aggregate_start_and_finish_logs` do D-1).
- R2: mesma hora local → não executa de novo; hora seguinte → executa
  (throttle por hora, não por dia).
- R3: exceção (`RuntimeError` e `SystemExit`) no hourly é capturada com
  log agregado `intraday hourly recovery failed: <Tipo>`; ciclo executa;
  loop não aborta.
- R4: iteração bloqueada (`eligible=False`) jamais executa o passo.
- R5: flag `last_hourly_run_hour` em memória atualizada **antes** da
  tentativa (uma tentativa por hora mesmo em falha).
- R6: nenhum outro comportamento do loop muda (D-1, cooldown, backoff,
  stale recovery, `should_stop`).

## Matriz requisito -> arquivo -> teste/check

| Requisito                   | Arquivo(s)                                                                        | Teste/check                                                                                                                         |
| --------------------------- | --------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------- |
| R1, R2                      | `apps/census/orchestration.py`, `tests/unit/test_orchestrator_intraday_hourly.py` | `test_new_hour_runs_hourly_before_cycle` (inclui caplog de início/fim/duração), `test_same_hour_skips`, `test_next_hour_runs_again` |
| R3                          | idem                                                                              | `test_failure_does_not_block_cycle`, `test_system_exit_isolated`                                                                    |
| R4                          | idem                                                                              | `test_blocked_loop_never_runs_hourly`                                                                                               |
| R1 (ordem D-1→hourly→ciclo) | idem                                                                              | `test_d1_runs_before_hourly_in_same_iteration`                                                                                      |
| R5                          | idem                                                                              | `test_failure_still_consumes_the_hour`                                                                                              |
| R6                          | `apps/census/orchestration.py`                                                    | suite existente de `run_loop` (testes D-1) continua verde                                                                           |

## Escopo e expected blast radius

```yaml
expected_files:
  - apps/census/orchestration.py
  - tests/unit/test_orchestrator_intraday_hourly.py
allowed_incidental_files: []
out_of_scope:
  - runtime S11, scheduler, units systemd, specs, tasks.md
  - qualquer mudança no passo D-1 além da posição relativa
```

Escalamento: se precisar de qualquer arquivo fora da lista, PARE e
reporte bloqueio.

## RED

- comando:
  `docker compose -f compose.test.yml run --rm test-runner bash -c "cd /app && uv run --no-sync pytest -q tests/unit/test_orchestrator_intraday_hourly.py"`
  (equivalente host-only aceitável para iteração:
  `uv run pytest -q tests/unit/test_orchestrator_intraday_hourly.py`)
- falha esperada: os testes de disparo falham porque `call_command` com
  `--mode hourly` nunca é invocado pelo loop atual (assert de chamada
  falha), provando que o comportamento não existe.

## GREEN / verificação local

- mesmo comando do RED — exit 0 com todos os testes do arquivo.
- regressão local:
  `uv run pytest -q tests/unit/test_orchestrator_quiet_window_d1.py` —
  exit 0 (passo D-1 intacto, incluindo ordem D-1→hourly).
- lint parcial: `uv run ruff check apps/census/orchestration.py
tests/unit/test_orchestrator_intraday_hourly.py`.

## Gates do slice (após GREEN)

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
uv run openspec validate orchestrate-intraday-discharge-recovery --strict
```

## Critérios de aceitação

- [ ] R1..R6 com testes verdes no arquivo novo
- [ ] Suíte D-1 existente verde (R6)
- [ ] Gates do slice verdes
- [ ] Nenhum arquivo fora do blast radius

## Entrega

Relatório em `/tmp/sirhosp-slice-OIDR-S1-report.md` com snippets
antes/depois, contagens de teste antes/depois, comandos e resultados,
riscos residuais. Sem dados sensíveis. Não commitar; não tocar `tasks.md`.
