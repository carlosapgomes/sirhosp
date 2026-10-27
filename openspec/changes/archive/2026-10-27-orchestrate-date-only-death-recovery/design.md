# Design: orchestrate-date-only-death-recovery

Referências: `proposal.md`; ADR-0010 (janela silenciosa D-1); specs
`production-exit-reconciliation-runtime` e `admission-exit-reconciliation`
(date-only já especificado); ADR-0012 (markers como evidência canônica de
runtime).

## D1: passo dentro do modo D-1, após a extração

O passo roda **após** a extração canônica D-1 concluir (inclui os
`DeathRecord` da data), **antes** do retorno do comando — mesma execução,
mesma trava advisory-lock de modo. Sem novo modo, sem novo agendamento,
sem unit novo: a janela 01:00–05:00 (ADR-0010) e o padrão "no máximo uma
execução por data local" já existem e cobrem o passo.

## D2: fail-closed por registro, nunca por lote

Cada `DeathRecord` da data D-1 é processado individualmente pelo caminho
online `reconcile_death_record`. Desfechos:

- `reconciled` (match único): episódio fechado em D 00:00 local
  (portadora) com marcador date-only — idêntico ao comportamento
  aprovado na rc.41;
- `already_reconciled`/`pending`/`ambiguous`/`patient_not_found`/
  `admission_not_found`: **sem escrita adicional**; apenas contabilizado
  no resumo agregado do log.

Nenhum desfecho individual derruba o passo: exceção inesperada em um
registro é registrada e o passo continua (o runtime D-1 já tem essa
postura para as altas).

## D3: procedência de runtime no evento

Eventos criados pelo passo carregam a mesma proveniência do caminho
online (audit append-only). Para distinguir origem de runtime sem novo
schema: `details_json` recebe carimbo leve (ex.: `runtime: {"mode":
"d1"}`) no mesmo espírito do linkage `backfill` — forma exata segue o
layout existente na implementação, documentada no slice.

## D4: marker de sucesso no log (padrão OASF)

`mode=d1-deaths result=success source=adaptive-orchestrator` emitido
apenas após o passo concluir (com contagens reconciled/informativos/
pendentes). O preflight da ativação estatística não lê esse marker —
aditivo, sem risco de regressão; observabilidade passa a ter evidência
canônica noturna.

## D5: escopo estrito de data

O passo consulta apenas `DeathRecord` cuja **data local = D-1** (a data
que a extração acabou de trazer). Histórico anterior permanece
responsabilidade do comando delimitado de backfill (decisão de operador);
o runtime nunca varre massa antiga.

## D6: o que NÃO muda (explícito)

- Valores de óbitos em `/painel/` e `/obitos` (`DailyDeathCount`,
  extração) — inalterados por construção;
- indicadores de altas (óbitos excluídos);
- comando `reconcile_admission_history` (massa histórica);
- `--mode hourly` e `catchup` (sem passo de óbitos).

## D7: testes (behavior, not implementation)

- Passo fecha episódio com match único da data D-1 (marcador +
  portadora + proveniência runtime);
- ambíguo/não-resolvido: sem escrita, contabilizado, passo conclui com
  marker;
- exceção em um registro não aborta os demais;
- sem `DeathRecord` na data: passo conclui (marker, zero escritas);
- marker não emitido quando o passo falha inteiro;
- regressão: modo hourly inalterado; altas D-1 inalteradas.
