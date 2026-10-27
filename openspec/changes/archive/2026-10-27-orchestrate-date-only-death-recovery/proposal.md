# Proposal: orchestrate-date-only-death-recovery

## Why

A change `reconcile-date-only-deaths` (rc.41) tornou possível reconciliar
óbitos com apenas data — mas o processamento ficou **manual** (comando de
backfill delimitado, com autorização de operador). O fonte nunca fornece
hora de óbito (~3–4/dia), e o runtime D-1 **já extrai** esses registros
todas as noites (ordem canônica `discharges, admissions, deaths,
official_census`) sem nunca reconciliá-los.

Efeito observado em produção: episódios de pacientes falecidos permanecem
**abertos** no censo até um lote manual rodar — dos 57 regularizados em
2026-10-25, 4 eram de setembro/outubro corrente. Cada dia sem processamento
acrescenta um "internado fantasma".

## What Changes

- O runtime `run_exit_reconciliation_runtime --mode d1` ganha, após a
  extração D-1, um **passo de reconciliação de óbitos date-only da data
  recuperada**: para cada `DeathRecord` da data local D-1, aplica o caminho
  online (`reconcile_death_record`) — que só fecha em **match único** por
  contenção de data local (`America/Bahia`), com marcador de precisão
  date-only e procedência de runtime.
- Fail-closed por registro: ambíguo/não-resolvido permanece pendente (sem
  crash, sem lote, sem intervenção); resumo agregado no log.
- Novo marker de sucesso no log do orquestrador (padrão OASF:
  `mode=d1-deaths result=success source=adaptive-orchestrator`), emitido
  apenas após o passo concluir.
- Volume diário (~3–4) limitado pela própria data — sem caps de backfill.
- O comando de backfill `reconcile_admission_history` permanece para
  massa histórica e reprocessamentos, com autorização explícita de
  operador.

### Fora de escopo

- **Qualquer mudança nos valores de óbitos exibidos**: `/painel/`
  (indicador `obitos`) e `/obitos` leem `DailyDeathCount` (agregação da
  extração diária) — a reconciliação não altera esses números, nunca
  alterou, e não passará a alterar;
- indicadores de altas (óbitos seguem excluídos) e taxonomia de saídas;
- reconciliação de óbitos em `--mode hourly` (óbitos chegam via extração
  D-1; intraday não traz ganho clínico);
- a massa histórica não-reconciliada (720 registros: 511 informativos +
  209 revisão manual — decisões separadas).

## Capabilities

### New Capabilities

Nenhuma.

### Modified Capabilities

- `production-exit-reconciliation-runtime` — o modo D-1 passa a fechar
  episódios por morte na janela noturna, com marcador de log e
  fail-closed por registro.

## Impact

- Código: `apps/ingestion/management/commands/run_exit_reconciliation_runtime.py`
  (passo D-1), `apps/census/orchestration.py` (constante do marker);
  reuso integral de `reconcile_death_record` (sem lógica nova de
  matching).
- Sem migrations, sem dependências, sem mudança de compose/units.
- Ativação: junto ao deploy da release que a incluir (sem operação
  separada); a primeira noite de observação valida o marker e os
  fechamentos.
