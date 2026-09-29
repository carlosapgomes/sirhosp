# Proposal — `align-export-patient-annotation`

## Why

Desde o slice LSPA-S1 do change `link-statistics-patients-to-admissions`
(arquivado em 2026-09-29), as linhas de pacientes da projeção do relatório
diário são instâncias da dataclass frozen `PatientRow`
(`apps/statistics_reports/presentation.py`), mas a anotação de
`_patient_values` em `apps/statistics_reports/export.py` continua declarando
o modelo `DailyStatisticsPatient`. A dívida foi registrada na decisão D3 do
design daquele change com quitação prometida em change dedicado: o runtime é
seguro (consumo exclusivamente por attribute access via `getattr`, que o mypy
lê como `Any`), mas a anotação desatualizada mente sobre o contrato real e
convida a suposições inseguras de tipo em manutenções futuras.

## What Changes

- A anotação do parâmetro de `_patient_values` em
  `apps/statistics_reports/export.py` passa a ser um `Protocol` estrutural
  com exatamente os quatro campos consumidos (`bed`, `name`, `record`,
  `specialty`), satisfeito tanto pelo modelo `DailyStatisticsPatient` quanto
  pela dataclass `PatientRow`.
- Mudança **somente de anotação/tipagem**: nenhum comando novo, nenhum
  comportamento de runtime, nenhum output de workbook diferente, nenhuma
  migration, nenhuma dependência nova.

## Capabilities

Nenhuma capability é criada ou modificada: a correção é interna de tipagem
estática, sem qualquer mudança de comportamento em nível de requisito. O
arquivamento deve usar `--skip-specs`.
