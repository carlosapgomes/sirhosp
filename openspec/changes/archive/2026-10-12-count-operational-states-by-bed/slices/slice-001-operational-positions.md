# Slice 001 — Estados operacionais por leito (materialização + card)

## Objetivo

Alterar a contagem dos estados operacionais do sumário "situação real" de
`/beds/` de linha bruta para leito (posição física), com exclusão explícita
de divergentes, colapso de repetidos e separação de linhas sem leito,
persistida no reconciliation schema 4 e renderizada pelo card com fallback
para schema 3.

## Requisitos cobertos

Delta `specs/bed-status-capacity-view/spec.md` (requirement MODIFIED
`V5 page summarizes the real hospital situation`), cenários:

- Operational states are summarized per bed;
- Divergent beds are excluded and surfaced;
- Bedless operational lines stay out of the badges;
- Historical measurements keep their persisted semantics.

Os demais cenários do requirement (pacientes identificados, identificação
incompleta, privacidade) são de regressão.

## Referências necessárias

- `AGENTS.md` — políticas globais e quality gate.
- `openspec/changes/count-operational-states-by-bed/proposal.md` e
  `design.md` (decisões D1–D3).
- Código: `apps/census/occupancy.py` — `_calculate_v5`, `_OPERATIONAL_MARKERS`,
  `_v5_real_totals`, `_reconciliation_v5_json`,
  `_V5_RECONCILIATION_ALLOWLIST`, `_normalize_positions` /
  `_classify_key_rows` (chave física a reutilizar, com a projeção de
  estado efetivo v5 do design D2 — a assinatura `_row_signature` crua
  não normaliza marcadores; ver também `_operational_status` e
  `_identified_patient_identity`).
- Template: `apps/census/templates/census/bed_status.html` (seção
  "situação real").
- Testes existentes de referência:
  `tests/unit/test_occupancy_measurement.py` (classe de testes v5),
  `tests/unit/test_bed_status_view.py` (`test_v5_real_situation_*`).

## Acceptance criteria

1. Um leito com N linhas concordantes no mesmo estado efetivo conta
   exatamente 1 no badge desse estado; as N−1 repetições viram
   `operational_duplicate_extra_rows`. Variantes de marcador do mesmo
   estado (`DESOCUPADO` e `VAZIO`) concordam — não são divergência.
2. Um leito com estados efetivos divergentes (inclusive ocupado com
   identidade + marcador operacional) não incrementa nenhum badge e
   incrementa `operational_conflict_positions` (leitos) e
   `operational_conflict_rows` (linhas operacionais envolvidas).
3. Linhas operacionais sem leito não incrementam badge; incrementam
   `operational_rows_without_bed`.
4. O reconciliation gravado tem `schema_version` 4, contém
   `operational_positions_by_status`, os contadores de exceção
   (`operational_duplicate_extra_rows`, `operational_conflict_positions`,
   `operational_conflict_rows`, `operational_rows_without_bed`) e preserva
   `operational_rows_by_status`; a allowlist fecha com o conjunto exato
   de chaves.
5. Fechamento aritmético por linhas (demonstrado em teste com, no mínimo,
   leito repetido, leito divergente em dois estados, leito ocupado +
   marcador, variantes do mesmo estado e linha sem leito):

   ```text
   soma(operational_positions_by_status)
     + operational_duplicate_extra_rows
     + operational_conflict_rows
     + operational_rows_without_bed
     == soma(operational_rows_by_status)
   ```

6. Measurements schema 3 renderizam exatamente como antes (badges por
   linha), sem recomputação e sem híbrido de esquemas em
   `_v5_real_totals`.
7. O card exibe linha condicional `N leitos com estados divergentes
   (não contados)`, omitida quando zero; nada nominal é renderizado.
8. `DailyOccupancySummary` e demais superfícies não são alteradas
   (verificação de consumidores na tarefa 2.1 é pré-condição).

## Expected blast radius

- `apps/census/occupancy.py` (cálculo, reconciliation, apresentação do
  card);
- `apps/census/templates/census/bed_status.html` (seção do card);
- `tests/unit/test_occupancy_measurement.py`,
  `tests/unit/test_bed_status_view.py`.

Sem models, migrations, urls ou views novas neste slice.

## Estratégia de teste/verification

- TDD unitário na materialização (cenários 1–6) e na view/template
  (cenários 6–7), com fixtures sintéticas.
- Regressão: suíte de occupancy + bed_status_view existente.
- Verification de produto fica para o slice 002 (superfície completa).

## Comandos obrigatórios

```bash
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh quality-gate
./scripts/markdown-lint.sh   # para todo .md alterado
```

## Condições de bloqueio

- Consumidor de `operational_rows_by_status` além dos já mapeados (card,
  ponte de reconciliação do template `bed_status.html` — preservada pela
  gravação simultânea da chave antiga — e a página de detalhe planejada
  no slice 002).
- Necessidade de alterar semântica de paciente, taxa oficial ou pontes
  v1–v4 para fechar a aritmética.
- Qualquer exigência de regravar measurements existentes.
