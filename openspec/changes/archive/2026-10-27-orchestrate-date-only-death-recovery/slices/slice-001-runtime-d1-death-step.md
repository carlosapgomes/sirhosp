# SLICE-ODR-S1 — Passo de óbitos date-only no runtime D-1

## Objetivo

O modo D-1 do `run_exit_reconciliation_runtime` ganha, após a extração
canônica, um passo que reconcilia os `DeathRecord` date-only da data
recuperada pelo caminho online `reconcile_death_record` — fechando somente
matches únicos por data local, fail-closed por registro, com resumo
agregado e marker de sucesso.

## Contexto necessário

- `apps/ingestion/management/commands/run_exit_reconciliation_runtime.py`
  — modos d1/hourly/catchup, advisory lock por modo, ordem canônica dos
  extratores, postura "falha agregada não aborta".
- `apps/deaths/services.py` — `reconcile_death_record` (já aceita
  date-only desde rc.41: fecha em D 00:00 `America/Bahia` com marcador
  `death_exit.precision="date"`).
- `apps/census/orchestration.py` — chamada do modo d1 na janela
  silenciosa (ADR-0010) e markers OASF (`D1_RECOVERY_SUCCESS_MARKER`).
- `openspec/changes/orchestrate-date-only-death-recovery/design.md` —
  D1–D7.
- Fixtures: testes existentes do runtime e de óbitos como referência
  (sintéticos, zero PHI).

## Requisitos verificáveis

- R1: após a extração D-1, o passo processa cada `DeathRecord` com data
  local = D-1 via `reconcile_death_record`; match único fecha o episódio
  (portadora + marcador) e o evento carrega proveniência de runtime
  (carimbo leve em `details_json`, forma documentada na implementação).
- R2: desfechos não-fecháveis (ambíguo, patient/admission_not_found,
  already_reconciled informativo) → nenhuma escrita adicional; contados no
  resumo agregado.
- R3: exceção inesperada em um registro é logada e não interrompe os
  demais; falha total do passo não aborta o recovery nem o loop; marker
  `mode=d1-deaths result=success source=adaptive-orchestrator` emitido
  somente quando o passo conclui.
- R4: escopo estrito da data D-1 (D5) — nenhuma varredura de histórico.
- R5: `--mode hourly` e `--mode catchup` inalterados (regressão).
- R6: saída e logs agregados, sem identidade de paciente.

## Expected blast radius

- `apps/ingestion/management/commands/run_exit_reconciliation_runtime.py`;
- `apps/census/orchestration.py` (constante do marker);
- `tests/unit/` e/ou `tests/integration/` do runtime.

## Estratégia de teste/verification

TDD: unitários do passo (R1–R5) + integração do comando em modo d1 com
banco sintético efêmero (extração simulada + óbito da data). Gates:
`check`, `unit`, `integration`, `lint`, `typecheck`. Verification de
runtime (marker na primeira noite) fica na task 2.3, pós-deploy.

## Condições de bloqueio

- descoberta de dependência da hora portadora em qualquer consumo do
  runtime (clínico) → `BLOCKED_NEEDS_DECISION`;
- necessidade de novo modo/agendamento → escalar (contradiz D1).
