# SLICE-ODER-S1 — Passo D-1 no loop do orquestrador adaptativo

## Handoff de entrada (contexto zero)

Você está no repositório `sirhosp` (Django 5, monólito modular; Python 3.12
com `uv`). Leia primeiro: `AGENTS.md` (seções 2, 5, 6), o
`openspec/changes/orchestrate-d1-exit-recovery/design.md` (decisões D1–D5) e
a ADR-0010 em `docs/adr/` (motivação). Ferramentas de validação:
`./scripts/test-in-container.sh {check,unit,lint,typecheck}` (obrigatório;
host-only é diagnóstico).

Este slice implementa o ADDED requirement
`openspec/changes/orchestrate-d1-exit-recovery/specs/adaptive-census-orchestration/spec.md`
e o MODIFIED requirement
`openspec/changes/orchestrate-d1-exit-recovery/specs/production-exit-reconciliation-runtime/spec.md`.

## Objetivo

O `run_loop` em `apps/census/orchestration.py` passa a executar, uma vez por
data local Bahia e apenas na janela `[01:00, 05:00)`:

```python
from django.core.management import call_command
call_command("run_exit_reconciliation_runtime", "--mode", "d1")
```

**Ponto exato**: dentro do laço `while not should_stop():`, imediatamente
ANTES da chamada de `run_single_cycle` (após o ponto em que
`decision.eligible` já é verdadeiro — o passo só existe no ramo elegível).
Critérios de disparo (todos obrigatórios): `decision.eligible` verdadeiro;
hora local `America/Bahia` em `[01:00, 05:00)`; `last_d1_run_date != data
local Bahia corrente`.

## Regras de implementação

1. **Constantes no módulo** (sem configuração nova): por exemplo
   `D1_QUIET_START_HOUR = 1`, `D1_QUIET_END_HOUR = 5`,
   `BAHIA_TZ = ZoneInfo("America/Bahia")` (literal; nunca fuso herdado).
2. **Flag em memória**: variável local do `run_loop`
   (`last_d1_run_date: date | None = None`), atualizada para a data local
   corrente logo após a tentativa — sucesso ou falha (uma tentativa por
   dia; sem retry intra-dia).
3. **Falha nunca bloqueia**: o `call_command` roda envolvido em
   `try/except Exception`; em falha logar linha agregada com nível `error`
   no formato `quiet-window D-1 recovery failed: <ExceptionType>` (sem
   dados sensíveis) e seguir para o ciclo normal.
4. **Logs de início/fim**: nível `info`, agregados: início com data local
   Bahia; fim com duração em segundos. Nada além de datas/durações/status.
5. **Relógio injetável para testes**: hoje o loop recebe `sleep_fn`;
   adicione `now_fn: Callable[[], datetime] | None = None` (default
   `timezone.now`) usado exclusivamente para avaliar janela e data local —
   mesma técnica de injeção já usada no arquivo. Não mude a assinatura dos
   demais parâmetros nem comportamentos existentes.
6. `compute_orchestrator_state`, `run_single_cycle`, stale recovery e
   cooldown permanecem intocados. O runtime S11
   (`run_exit_reconciliation_runtime`) e o scheduler NÃO devem ser
   alterados. Zero migrations, zero modelos novos.

## Plano de teste (TDD estrito — RED antes da implementação)

Arquivo: `tests/unit/test_orchestrator_quiet_window_d1.py` (novo). Use
`unittest.mock.patch` para `compute_orchestrator_state`,
`run_single_cycle`, `call_command` (alvo do patch:
`apps.census.orchestration.call_command` — importe `call_command` no módulo
para o patch ser raso) e `now_fn` real injetado (sem patch de módulo para o
relógio). `should_stop` customizado para rodar uma ou duas iterações e
sair; `sleep_fn` no-op. `decision` pode ser um `OrchestratorDecision`
elegível real (leia a dataclass) ou `SimpleNamespace(eligible=True, ...)`
se suficiente.

1. `test_eligible_quiet_window_runs_d1_before_cycle`: `now_fn` = 02:30
   Bahia; assegura ordem de chamadas (`call_command` antes de
   `run_single_cycle`) — use `Mock.attach_class`/`side_effect` registrando
   ordem em lista compartilhada; verifica `call_command` chamado com
   `("run_exit_reconciliation_runtime", "--mode", "d1")`.
2. `test_outside_quiet_window_skips_d1`: 00:59, 05:00 e 14:00 Bahia —
   `call_command` nunca chamado; ciclo executa.
3. `test_once_per_local_date`: duas iterações elegíveis no mesmo dia
   (00:30→01:10 ou simplesmente duas iterações com `now_fn` fixo 02:00) —
   `call_command` exatamente uma vez.
4. `test_d1_failure_does_not_block_cycle`: `call_command` levanta
   `RuntimeError`; ciclo (`run_single_cycle`) ainda chamado; nenhuma
   exceção escapa do `run_loop`.
5. `test_blocked_loop_never_runs_d1`: `eligible=False` às 02:30 —
   `call_command` não chamado.
6. `test_boundary_midnight_bahia_from_utc`: `now_fn` em UTC cuja conversão
   Bahia é exatamente 01:00 (executa) e exatamente 05:00 (não executa) —
   prova que a janela usa Bahia literal, não fuso do host.

## Limites do slice

- **Arquivos permitidos**: `apps/census/orchestration.py`,
  `tests/unit/test_orchestrator_quiet_window_d1.py`. Nenhum outro arquivo.
  Se precisar de mais, PARE e reporte bloqueio (escalada via
  `contact_supervisor`).
- Não commita; não mexa em `tasks.md` (o controller faz).
- Não altere specs (já escritas) — apenas valide-as.

## Comandos de validação (obrigatórios, nesta ordem)

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
uv run openspec validate orchestrate-d1-exit-recovery --strict --json
```

## Entrega

1. Snippets antes/depois de `apps/census/orchestration.py`.
2. Resultado dos gates (contagens de testes antes/depois).
3. Relatório em `/tmp/sirhosp-slice-ODER-S1-report.md` (estrutura das
   seções 10 do AGENTS.md; sem dados sensíveis).
