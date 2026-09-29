# Design — `align-export-patient-annotation`

## Contexto

Fatos verificados no código (2026-09-29):

- `export.py:274` declara `def _patient_values(patient: DailyStatisticsPatient)`;
- desde LSPA-S1 as linhas de pacientes da projeção são `PatientRow`
  (`presentation.py:167-174`: `bed`, `name`, `record`, `specialty`,
  `patient_id` — frozen dataclass);
- o consumo é exclusivamente attribute access dos quatro campos fixos
  (`export.py:274-276`), e o despacho chega às linhas via
  `getattr(group, section.attribute)` (`export.py:222`), cujo resultado o
  mypy trata como `Any` — por isso a anotação desatualizada nunca foi
  confrontada pelo typecheck;
- `export.py` já importa de `presentation` (`EventRow`,
  `DailyReportProjection`, títulos), portanto não há barreira de import.

## D1 — Protocol estrutural de consumo, declarado no consumidor

O parâmetro de `_patient_values` passa a ser tipado como um `Protocol` com
exatamente os quatro campos que a função lê, na forma **read-only**:

```python
class PatientExportRow(Protocol):
    """Contract of the nominal fields the workbook reads from a patient row."""

    @property
    def bed(self) -> str: ...

    @property
    def name(self) -> str: ...

    @property
    def record(self) -> str: ...

    @property
    def specialty(self) -> str: ...
```

Ambos `DailyStatisticsPatient` e `PatientRow` satisfazem o protocolo
estruturalmente, sem alteração em qualquer um deles. Os membros são
`@property` (read-only) por necessidade estática: `PatientRow` é dataclass
frozen, cujos atributos o mypy trata como somente leitura — membros com
variáveis mutáveis (`bed: str`) a rejeitariam com "expected settable
variable, got read-only attribute" — e a forma read-only aceita os dois
shapes, além de descrever com precisão o consumo apenas-leitura da função.
O protocolo vive em `export.py` porque documenta o contrato de **consumo**
do exportador — o que ele lê —, não a forma de produção da projeção.

*(Emenda autorizada pelo parent em loop, 2026-09-29, a partir de diagnóstico
do worker com mypy 1.19.1: a forma original com variáveis mutáveis era
aceita apenas pelo modelo e rejeitava `PatientRow`.)*

Como o call site real alimenta o parâmetro via `getattr(group,
section.attribute)` (`Any` para o mypy), o typecheck oficial não discrimina
as duas formas sozinho; o contrato fica documentado e verificado pelo
protocolo em si, não pelo fluxo do call site.

Alternativa rejeitada: união `DailyStatisticsPatient | PatientRow`. Acopla o
exportador às formas concretas do produtor (exige importar as duas), repete a
dívida a cada nova shape de linha e não documenta o que efetivamente é
consumido.

O protocolo **não** é `@runtime_checkable`: é contrato exclusivamente
estático; nada em runtime deve consultá-lo.

## D2 — Zero mudança de runtime

Nenhum byte do comportamento muda: sem novos comandos, sem queries, sem
mudança de workbook (o contrato de regressão XLSX do change
`link-statistics-patients-to-admissions` continua verde e intocado), sem
migration. O diff é uma anotação e a definição do protocolo no mesmo arquivo.

## D3 — Validação proporcional: typecheck é o teste

Mudança somente de anotação não possui teste RED/GREEN de runtime possível
(sem comportamento novo para falhar). A evidência do slice é:

- `./scripts/test-in-container.sh typecheck` verde (o mypy é o executor
  natural do contrato novo);
- suíte focada existente da página e da exportação
  (`test_daily_statistics_page.py` + `test_daily_statistics_export.py`)
  permanece verde sem edição — prova de que a anotação não alterou runtime;
- `./scripts/test-in-container.sh lint`, `check` e
  `makemigrations --check --dry-run` limpos.

## Escopo e rollback

Um arquivo (`apps/statistics_reports/export.py`). Risco mínimo; rollback é
reverter o commit.
