# Design: link-statistics-patients-to-admissions

## Contexto

Investigação confirmada (scouts read-only, 2026-09-29; revisão independente do
plano com veredito `BLOCK` absorvida neste documento):

- `daily_report.html` renderiza as listas como `<li>` com `<span>`s, sem
  nenhum `<a>` nominal.
- `DailyStatisticsPatient` e `DailyStatisticsEvent` persistem apenas `record`
  (prontuário string), `name`, `bed`, `specialty`; a origem `CensusSnapshot`
  também não possui FK para `Patient`. Não existe `patient_id` em nenhum ponto
  da cadeia de estatísticas.
- `/beds/` resolve prontuário → `Patient.pk` em tempo de leitura com
  `Patient.objects.filter(patient_source_key__in=prontuarios)` e renderiza
  `<a href="{% url 'patients:admission_list' patient.patient_id %}">`, com
  fallback `{% url 'patients:patient_list' %}?q={{ record }}` quando não
  resolve (`bed_status.html:738-758`).
- `Patient` garante unicidade por `(source_system, patient_source_key)`
  (constraint `uq_patient_src`) — **não** por prontuário global.
- A página de destino (`patients:admission_list`,
  `/patients/<int:patient_id>/admissions/`) exige apenas `@login_required`.
- **A exportação XLSX consome a mesma projeção**: `export.py` recebe
  `DailyReportProjection` e lê dos grupos apenas os campos fixos de pacientes
  e eventos (`export.py:125-150,259-278`).
- `EventRow` é dataclass frozen (`presentation.py:148-157`); as linhas de
  pacientes chegam ao template como instâncias do modelo
  `DailyStatisticsPatient` (`models.py:227-269`).

## D1 — Resolução em tempo de leitura, sem persistência

O link é preocupação de apresentação: a projeção do relatório resolve os
prontuários no momento do render. Revisões materializadas, `source_fingerprint`,
XLSX e logs permanecem exatamente como hoje; nada é re-materializado.

Alternativa rejeitada: persistir `patient_id` nas linhas materializadas.
Exigiria migration, mudaria a impressão digital das revisões, forçaria
re-materialização para datas antigas e não agrega nada à navegação.

## D2 — Política de resolução: único candidato, senão fallback

`build_daily_report_projection` resolve, em uma única query
(`patient_source_key__in`, lida como `values_list("patient_source_key", "id")`
e agrupada em memória por prontuário), todos os prontuários não vazios das
linhas de pacientes e de eventos de todos os grupos (incluindo
`Setor não identificado`); sem nenhum prontuário qualificado, a query é
pulada.
A unicidade real do banco é por `(source_system, patient_source_key)`;
portanto a política é fail-safe:

- prontuário com **exatamente um** candidato em todo o banco → resolve para
  aquele `pk`;
- prontuário com **mais de um** candidato (mesma chave em sistemas de origem
  distintos) → não resolve (tratado como não identificado; usa o fallback de
  busca) — nunca escolhe um paciente arbitrário entre fontes;
- prontuário vazio → não resolve. A coleta normaliza com
  `(record or "").strip()` e trata vazio-após-strip como vazio: a
  materialização persiste `record` cru nas linhas de pacientes, então o
  strip é defensivo nos dois lados do match.

A ingestão aceita sistemas de origem arbitrários e o extrator demográfico emite
metadados `aghu`; hoje o censo é majoritariamente `tasy`, mas a colisão
cruzando fontes é possível e a política acima a neutraliza por construção. A
decisão "menor `pk` vence" foi rejeitada: linkage silencioso entre fontes é
exatamente o tipo de erro que o relatório não pode introduzir.

Não existe índice isolado em `patient_source_key` (apenas o composto da
constraint); a query é única e limitada pelo número de prontuários distintos
da revisão, o que é aceitável por render sob `private, no-store`. Este change
não cria índice nem migration.

Alternativa rejeitada: montar o mapa na view, como `/beds/` faz. Aqui já existe
um módulo de apresentação dedicado; a view permanece fina (AGENTS.md).

## D3 — Shape de apresentação compatível com o exportador

Para expor `patient_id` sem tocar modelos:

- `EventRow` (frozen) ganha o campo `patient_id: int | None`, preenchido na
  construção das linhas com o valor resolvido.
- As linhas de pacientes deixam de ser instâncias do modelo na projeção e
  passam a ser a dataclass frozen `PatientRow` com exatamente os campos
  consumidos hoje (`bed`, `name`, `record`, `specialty`) mais `patient_id`.
- O exportador XLSX consome a mesma projeção e lê apenas os campos fixos
  existentes; `PatientRow` é attribute-compatível com esse uso, e o contrato
  "workbook continua escrevendo somente as colunas fixas de hoje, sem qualquer
  coluna ou valor derivado de `patient_id`" fica protegido por teste de
  regressão na suíte de exportação.

Dívida de anotação registrada e aceita: a anotação de `_patient_values` em
`export.py` continuará declarando `DailyStatisticsPatient` enquanto passará a
receber `PatientRow` em runtime; o consumo é exclusivamente por attribute
access via `getattr`, então o runtime permanece seguro, e a correção da
anotação fica para um change dedicado — este change mantém `export.py`
byte a byte igual.

## D4 — Template replica o padrão de `/beds/` nos dois ramos

O nome em cada linha passa a ser um `<a class="text-decoration-none">`:

- com `patient_id`: `{% url 'patients:admission_list' <patient_id> %}`;
- sem `patient_id` e com `record` não vazio:
  `{% url 'patients:patient_list' %}?q={{ record }}`;
- com `record` vazio: o nome permanece texto simples, sem link (busca vazia
  não agregaria nada).

A mudança nos ramos `section.patients` e `section.events` cobre
automaticamente as quatro listas por setor (`entries`, `exits`,
`unidentified`, `patients`) e as duas listas do grupo `Setor não identificado`.
Nenhum outro elemento da página muda. A asserção de ordenação natural existente
que procura `>{nome}</span>` passa a ser independente de tag, e o orçamento de
queries da projeção documentado em teste passa de três para quatro consultas
(a query de resolução), mantida a invariância por volume; revisões sem
nenhum prontuário nominal pulam a query e permanecem em três.

## D5 — Nenhuma permissão nova

O destino (`patients:admission_list`) exige apenas autenticação; todo usuário
de `/statistics/` já é autenticado. O `pk` do paciente já aparece em URLs do
`/beds/`, portanto o link não expõe identificador novo nem concede capacidade
nova. `view_daily_statistics` continua sendo o único gate da página.

## D6 — Custo e limites

- Uma query extra por render da página (resolução), sem N+1: o mapa é
  consultado uma vez e aplicado em memória; revisões sem nenhum prontuário
  nominal pulam a query e permanecem no orçamento anterior de consultas.
- `Cache-Control: private, no-store` permanece; links são por request.
- Sem alteração de ordenação, rótulos, badges ou estados vazios.

## Riscos e rollback

- Risco baixo: mudança confinada à camada de leitura da página e ao shape da
  projeção, com contrato do exportador protegido por regressão.
- Rollback = reverter o commit; revisões materializadas e XLSX nunca são
  tocados.

## Slice único

O change é entregue em um slice vertical (LSPA-S1): resolver + renderizar +
testar é um único comportamento observável, e a separação por camada criaria
slices horizontais artificiais.
