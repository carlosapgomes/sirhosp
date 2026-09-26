# SLICE-DSRS-S3 — Entradas e transferências detectadas

## Handoff de entrada

Você inicia com contexto zero após DSRS-S2 aceito. Leia `AGENTS.md`,
`PROJECT_CONTEXT.md`, `proposal.md`, as decisões 4–6 de `design.md`, os
requisitos de âncora, fotografias consecutivas, classificação de entradas,
tempo e ordenação da delta spec, e os relatórios S1/S2 em `/tmp`. Implemente
somente entradas e transferências com TDD e fixtures sintéticas.

## Objetivo

Comparar âncora e censos aceitos consecutivos para persistir internações,
transferências internas e entradas com origem não identificada, com um evento
lógico por transferência, origem versionada, intervalo de detecção e ordenação
natural.

## Requisitos verificáveis

- **R1:** paciente ausente→presente com origem externa gera internação.
- **R2:** emergência, centro cirúrgico, setor monitorado ou não monitorado geram
  transferência interna; origem desconhecida sem confirmação usa `Entrada no
  setor — origem não identificada`, enquanto transferência já confirmada sem
  origem usa `Transferência interna — origem não identificada`.
- **R3:** A→B gera um evento com origem/destino, apresentado depois como saída
  de A e entrada em B, sem duplicar o fato.
- **R4:** troca de leito no mesmo agrupamento não gera evento setorial.
- **R5:** identidade ausente/conflitante e mapeamento setorial ambíguo falham
  fechados e produzem qualidade explícita.
- **R6:** sem hora clínica, o evento preserva `detected_not_before` e
  `detected_at` sem sintetizar hora.
- **R7:** ordenação natural coloca leitos presentes antes de ausentes e usa nome
  e prontuário como desempate.

## Escopo e blast radius

```yaml
expected_files:
  - apps/statistics_reports/models.py
  - apps/statistics_reports/migrations/0002_statistics_events.py
  - apps/statistics_reports/origin_policy.py
  - apps/statistics_reports/events.py
  - apps/statistics_reports/materialization.py
  - tests/integration/test_daily_statistics_entries.py
allowed_incidental_files: []
out_of_scope:
  - óbitos, altas e desaparecimentos
  - página, menu, XLSX e export logs
  - comando diário e systemd
  - correções manuais e produção
```

Limite: seis arquivos. Pare se precisar usar `PatientMovement` como verdade
canônica, hardcodear valores reais de origem sem contrato ou alterar fontes.

## Matriz requisito -> arquivo -> teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| R1–R2 | `origin_policy.py`, `events.py` | origens externas/internas/desconhecidas |
| R3–R5 | `events.py`, `materialization.py` | deltas, evento único e ambiguidades |
| R6 | models/eventos | precisão clínica versus detecção |
| R7 | `events.py` ou helper local | casos `2`, `10`, `UTI02`, sem leito |

## Plano de testes

### RED

Adicione os testes primeiro e execute:

```bash
./scripts/test-in-container.sh integration \
  tests/integration/test_daily_statistics_entries.py
```

Falha esperada: ausência do ledger projetado, política de origem e derivação de
transições.

### GREEN / verificação local

Implemente somente R1–R7 e repita o RED. Depois:

```bash
./scripts/test-in-container.sh unit \
  tests/unit/test_daily_statistics_window.py
./scripts/test-in-container.sh integration \
  tests/integration/test_daily_statistics_materialization.py
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

## Critérios de aceitação

- [ ] R1–R7 cobertos por RED→GREEN.
- [ ] Um transfer gera um fato, não duas linhas independentes.
- [ ] Nenhuma origem desconhecida vira internação silenciosamente.
- [ ] Relatório criado em `/tmp/sirhosp-slice-DSRS-S3-report.md`.
- [ ] Migration, checks e Markdown alterado passam.
