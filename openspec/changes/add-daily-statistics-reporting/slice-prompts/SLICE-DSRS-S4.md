# SLICE-DSRS-S4 — Saídas, precedência e revisões automáticas

## Handoff de entrada

Você inicia com contexto zero após DSRS-S3 aceito. Leia `AGENTS.md`,
`PROJECT_CONTEXT.md`, `proposal.md`, as decisões 3, 5–7 e 9 de `design.md`, os
requisitos de precedência, horários, atribuição setorial e revisão automática,
e os relatórios S1–S3 em `/tmp`. Implemente somente saídas e revisão automática.
Correção manual é explicitamente proibida.

## Objetivo

Classificar desaparecimentos observados como óbito, alta, transferência ou
`Saída do setor — destino não identificado`; manter hora clínica e detecção
distintas; inferir setor somente com procedência; e publicar nova revisão
atômica quando evidência tardia mudar o resultado.

## Requisitos verificáveis

- **R1:** precedência é óbito > `saida_em` > transferência > saída não
  classificada, sem dupla contagem do episódio.
- **R2:** óbito date-only entra com hora nula e detecção separada; nenhuma hora
  é sintetizada.
- **R3:** alta usa saída efetiva, não `alta_em` isolada.
- **R4:** setor ausente na evidência usa apenas a última posição unívoca anterior
  e registra atribuição inferida; caso contrário fica desconhecido.
- **R5:** transferência confirmada sem destino conhecido usa `Transferência
  interna — destino não identificado`; desaparecimento sem evidência de
  transferência usa `Saída do setor — destino não identificado`, nunca alta.
- **R6:** mesma fonte/fingerprint é idempotente; evidência tardia diferente gera
  nova revisão corrente e preserva a anterior como superseded.
- **R7:** fotografia final permanece a do mesmo fechamento durante revisão de
  evidência; nenhum modelo clínico é alterado.
- **R8:** nenhuma rota, permissão ou operação de correção manual é criada.

## Escopo e blast radius

```yaml
expected_files:
  - apps/statistics_reports/events.py
  - apps/statistics_reports/materialization.py
  - apps/statistics_reports/models.py
  - tests/integration/test_daily_statistics_exits.py
allowed_incidental_files:
  - apps/statistics_reports/migrations/0003_event_revision_constraints.py
out_of_scope:
  - edição manual, adjustment model ou approval flow
  - página, menu e XLSX
  - management command, timer e produção
  - alterações em admissions, discharges, deaths ou patients
```

Limite: cinco arquivos com migration incidental. Pare se a precedência exigir
mutar fonte clínica ou se identidade cruzada permanecer ambígua.

## Matriz requisito -> arquivo -> teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| R1–R5 | `events.py` | matriz de saídas e procedência setorial |
| R6–R7 | `materialization.py`, models | fingerprint e publicação de nova revisão |
| R8 | diff/`rg` focado | ausência de adjustment/edit endpoints |

## Plano de testes

### RED

Crie primeiro os cenários sintéticos e execute:

```bash
./scripts/test-in-container.sh integration \
  tests/integration/test_daily_statistics_exits.py
```

Falha esperada: saídas com destino ainda não identificado e demais saídas ainda
não são classificadas/revisionadas pelo serviço.

### GREEN / verificação local

Implemente o mínimo, repita o RED e execute:

```bash
./scripts/test-in-container.sh integration \
  tests/integration/test_daily_statistics_entries.py \
  tests/integration/test_daily_statistics_materialization.py
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
rg -n "adjust|manual.*correct|correção manual" apps/statistics_reports
```

O `rg` pode encontrar comentários de proibição, mas não modelo/endpoint de
ajuste.

## Critérios de aceitação

- [ ] R1–R7 cobertos por RED→GREEN e R8 inspecionado.
- [ ] Evento date-only mantém hora nula.
- [ ] Fontes clínicas e fotografia final permanecem inalteradas.
- [ ] Relatório criado em `/tmp/sirhosp-slice-DSRS-S4-report.md`.
- [ ] Checks e Markdown alterado passam.
