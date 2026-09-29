# SLICE-AEPA-S1 — Anotação do exportador alinhada a `PatientRow`

## Handoff de entrada (contexto zero)

Você está em `/projects/dev/sirhosp`. Leia:

1. `AGENTS.md`, especialmente Quality Gate, Stop Rule e relatório obrigatório;
2. `openspec/changes/align-export-patient-annotation/proposal.md` e
   `design.md` (decisões D1–D3);
3. `apps/statistics_reports/export.py` — especialmente `_patient_values`
   (linha ~274), o despacho por `getattr` em `_write_group` (~linha 222) e os
   imports de `presentation`;
4. `apps/statistics_reports/presentation.py` — a dataclass frozen
   `PatientRow` (~linhas 167-174);
5. `apps/statistics_reports/models.py` — `DailyStatisticsPatient`
   (campos `bed`, `name`, `record`, `specialty` como `CharField`);
6. `tests/integration/test_daily_statistics_export.py` e
   `tests/integration/test_daily_statistics_page.py` — apenas leitura;
   **nenhum teste é editado neste slice**.

Contexto: desde o change `link-statistics-patients-to-admissions`
(arquivado), `_patient_values` recebe em runtime `PatientRow` mas anota
`DailyStatisticsPatient`. O consumo é attribute access dos quatro campos
fixos; o mypy não acusa porque o despacho via `getattr` devolve `Any`. Este
slice quita a dívida de anotação registrada na decisão D3 daquele change.

## Objetivo

Corrigir a anotação para descrever o contrato real de consumo, sem qualquer
mudança de runtime.

## Requisitos verificáveis

- **R1:** `apps/statistics_reports/export.py` define
  `class PatientExportRow(Protocol)` com exatamente os quatro campos
  consumidos na forma **read-only** (`@property` `bed`, `name`, `record`,
  `specialty`, todos `-> str`); **sem** `@runtime_checkable`; a anotação do
  parâmetro de `_patient_values` passa a ser `PatientExportRow`.
  *(Emenda autorizada pelo parent em loop, 2026-09-29: a forma com variáveis
  mutáveis (`bed: str` etc.) é rejeitada pelo mypy contra a dataclass frozen
  `PatientRow` — "expected settable variable, got read-only attribute" —
  logo não descreveria o produtor real; membros `@property` aceitam os dois
  shapes e refletem o consumo apenas-leitura da função.)*
- **R2:** `DailyStatisticsPatient` (modelo) e `PatientRow` (dataclass)
  satisfazem o protocolo estruturalmente, sem alteração em qualquer um deles
  (nenhum import novo de modelo/dataclass é necessário; o protocolo é
  estrutural).
- **R3:** nenhuma outra mudança no arquivo: corpo de `_patient_values`
  idêntico, workbook idêntico, sem novos imports além de
  `typing.Protocol` (se ainda não importado).
- **R4:** nenhum teste é adicionado ou editado; nenhum outro arquivo muda;
  `makemigrations --check --dry-run` permanece limpo.

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) | Teste/check |
| --- | --- | --- |
| R1, R2, R3 | `apps/statistics_reports/export.py` | `./scripts/test-in-container.sh typecheck` (mypy valida o protocolo estrutural contra os dois shapes) + revisão do diff |
| R4 | — | `git diff --stat` (1 arquivo), suíte focada verde sem edição, `makemigrations --check --dry-run` |

## Escopo e expected blast radius

```yaml
expected_files:
  - apps/statistics_reports/export.py
allowed_incidental_files: []
max_changed_files: 1
out_of_scope:
  - tests/** (nenhum teste muda: mudança somente de anotação não tem teste
    de runtime possível — D3 do design)
  - apps/statistics_reports/presentation.py
  - apps/statistics_reports/models.py e migrations
  - qualquer arquivo de spec
```

Se qualquer mudança além da anotação e do protocolo parecer necessária,
pare e reporte o bloqueio.

## Plano de implementação

Mudança somente de anotação: TDD red→green não se aplica (não há
comportamento novo). A evidência é o conjunto de validações abaixo, todas
devem passar sem editar nenhum teste.

1. Em `export.py`: adicione `Protocol` aos imports de `typing` (o arquivo usa
   `from __future__ import annotations`); declare `PatientExportRow`
   imediatamente antes de `_patient_values` com docstring de uma linha
   ("Contract of the nominal fields the workbook reads from a patient row"),
   membros read-only `@property` conforme R1 (emendado); troque a anotação do
   parâmetro para `PatientExportRow` e remova o import agora órfão de
   `DailyStatisticsPatient` (emenda autorizada em loop: o import só existia
   para a anotação antiga; sem a remoção, `ruff check` reprova com F401).
2. Nada mais.

## Verificação do slice

```bash
SIRHOSP_TEST_DB_PORT=55633 uv run pytest tests/integration/test_daily_statistics_page.py tests/integration/test_daily_statistics_export.py -q
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
SIRHOSP_TEST_DB_PORT=55633 uv run python manage.py makemigrations --check --dry-run
openspec validate align-export-patient-annotation --strict
```

- A suíte de integração completa (`./scripts/test-in-container.sh
  integration`) pertence ao gate final do change, não ao slice.
- Diagnóstico host opcional antes dos oficiais:
  `uv run ruff check apps/statistics_reports/export.py` e
  `uv run ruff format --check apps/statistics_reports/export.py`.

## Critérios de aceitação

- [ ] R1: protocolo com os quatro campos, sem `runtime_checkable`, anotando
      `_patient_values`
- [ ] R2: mypy aceita modelo e `PatientRow` contra o protocolo (typecheck
      verde)
- [ ] R3: diff do arquivo limitado a imports de `typing`, protocolo e
      anotação (corpo de `_patient_values` intocado)
- [ ] R4: exatamente 1 arquivo no diff; suíte focada verde sem edição;
      `makemigrations --check` limpo
- [ ] `/tmp/sirhosp-slice-AEPA-S1-report.md` gerado com diff antes/depois e
      resultados dos comandos

## Contrato de handoff

Slice autocontido: um worker com contexto fresco lê o handoff, aplica a
anotação e roda a verificação. O worker não atualiza `tasks.md`, não faz
commit/push e escala bloqueios em vez de ampliar o escopo.
