# SLICE-LSPA-S1 — Linhas nominais clicáveis

## Handoff de entrada (contexto zero)

Você está em `/projects/dev/sirhosp`, branch de implementação do change
`link-statistics-patients-to-admissions`. Leia:

1. `AGENTS.md`, especialmente TDD, Stop Rule e relatório obrigatório;
2. `openspec/changes/link-statistics-patients-to-admissions/design.md`,
   decisões D1–D6;
3. o ADDED requirement em
   `specs/daily-statistics-reporting/spec.md` deste change;
4. `apps/statistics_reports/presentation.py` (especialmente
   `build_daily_report_projection`, a dataclass frozen `EventRow` e como as
   linhas de pacientes chegam aos grupos);
5. `apps/statistics_reports/export.py` (consome a MESMA projeção; lê apenas
   campos fixos de pacientes/eventos);
6. `apps/statistics_reports/templates/statistics_reports/daily_report.html`
   (ramos `section.patients` e `section.events`);
7. o padrão a replicar: `apps/census/templates/census/bed_status.html`
   linhas 738-758 (link `patients:admission_list` com fallback
   `patients:patient_list?q=<record>`);
8. `tests/integration/test_daily_statistics_page.py` e
   `tests/integration/test_daily_statistics_export.py` (helpers de
   materialização sintética já existentes).

Não implemente mudanças em materialização, permissões, models ou migrations
neste slice.

## Objetivo

Cada linha nominal das listas do relatório diário (entradas, saídas, eventos
com origem ou destino não identificado, pacientes do fechamento — incluindo as
listas do grupo `Setor não identificado`) torna-se clicável: quando o
prontuário corresponde a exatamente um paciente, o nome abre
`/patients/<pk>/admissions/`; quando não corresponde ou corresponde a mais de
um candidato, abre a busca `/patients/?q=<prontuario>`; sem prontuário,
permanece texto simples. A resolução ocorre em tempo de leitura na projeção,
nada é persistido e o XLSX não muda.

## Requisitos verificáveis

- **R1:** `build_daily_report_projection` expõe `patient_id: int | None` em
  cada linha projetada — `PatientRow` (nova dataclass frozen com `bed`,
  `name`, `record`, `specialty`, `patient_id`) para pacientes e campo novo
  `patient_id` em `EventRow` — resolvido com uma única query
  (`patient_source_key__in`) cobrindo todos os prontuários não vazios da
  revisão, coletados com `(record or "").strip()` e lida com
  `values_list("patient_source_key", "id")`, agrupando `prontuário → pks`
  em memória (os dois campos são necessários para detectar ambiguidade).
- **R2:** política de candidato único: prontuário com exatamente um candidato
  resolve; com mais de um candidato (crie os dois com `source_system`
  distintos, pois a constraint impede duplicata no mesmo sistema) NÃO resolve
  e não escolhe arbitrariamente; sem candidato não resolve; prontuário vazio
  ou vazio-após-strip não participa da query e não resolve.
- **R3:** no template, nos ramos `section.patients` e `section.events`, o nome
  é `<a class="text-decoration-none">` apontando para
  `{% url 'patients:admission_list' <patient_id> %}` quando resolvido, para
  `{% url 'patients:patient_list' %}?q={{ record }}` quando não resolvido com
  prontuário não vazio, e permanece texto simples quando o prontuário é vazio.
  As variáveis por ramo: `patient.patient_id`/`patient.record` no ramo de
  pacientes; `row.patient_id`/`row.event.record` no ramo de eventos.
- **R4:** linhas do grupo `Setor não identificado` recebem a mesma navegação.
- **R5:** o XLSX permanece idêntico: mesmas seções, colunas e valores; nenhuma
  coluna ou valor derivado de `patient_id` aparece no workbook; a revisão
  materializada, `source_fingerprint`, ordenação, rótulos, badges, estados
  vazios, permissões e `Cache-Control: private, no-store` permanecem
  inalterados; nenhum identificador resolvido é persistido.
- **R6:** as asserções existentes afetadas são atualizadas
  intencionalmente: a ordenação natural passa a ser independente de tag; o
  orçamento de queries da projeção passa de 3 para 4 consultas, mantida a
  invariância por volume (`len(big) == len(small)`) — o valor 4 vale para
  revisões com linhas nominais, caso das fixtures dos testes; sem nenhum
  prontuário qualificado a query é pulada e a projeção permanece em 3.
- **R7:** sem migration e sem alteração de modelo
  (`makemigrations --check --dry-run` limpo no gate final do change).

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| R1, R2 | `apps/statistics_reports/presentation.py` | testes novos em `tests/integration/test_daily_statistics_page.py` sobre `build_daily_report_projection` (único candidato, sem candidato, ambíguo entre fontes, prontuário vazio) |
| R3, R4 | `apps/statistics_reports/templates/statistics_reports/daily_report.html` | testes novos de render com `Client`: href `/patients/<pk>/admissions/`, fallback `/patients/?q=`, sem link com prontuário vazio, setor não identificado coberto |
| R5 | projeção (leitura) | teste novo em `tests/integration/test_daily_statistics_export.py`: workbook com seções/colunas/valores inalterados e sem coluna ou valor derivado da resolução, com resolução ativa na projeção |
| R6 | `tests/integration/test_daily_statistics_page.py` | atualização explícita das asserções de ordenação (`>{name}</span>` → busca independente de tag) e do orçamento de queries (3 → 4) |
| R7 | — | `uv run python manage.py makemigrations --check --dry-run` no gate final |

## Escopo e expected blast radius

```yaml
expected_files:
  - apps/statistics_reports/presentation.py
  - apps/statistics_reports/templates/statistics_reports/daily_report.html
  - tests/integration/test_daily_statistics_page.py
  - tests/integration/test_daily_statistics_export.py
allowed_incidental_files: []
max_changed_files: 4
out_of_scope:
  - apps/statistics_reports/export.py (o exportador permanece byte a byte
    igual; PatientRow é attribute-compatível com os campos que ele lê — se
    qualquer mudança nele parecer necessária, pare e reporte o bloqueio).
    Dívida de anotação conhecida e aceita: `_patient_values` continuará
    tipando `DailyStatisticsPatient` e passará a receber `PatientRow` em
    runtime — o consumo é por attribute access via `getattr` e permanece
    seguro; a anotação será corrigida em change dedicado, não neste slice
  - apps/statistics_reports/materialization.py e comando de materialização
  - apps/statistics_reports/models.py e migrations
  - apps/patients/ e apps/census/ (apenas leitura de referência)
  - views.py (a view permanece fina; resolução vive na apresentação)
```

Se for necessário tocar um quinto arquivo, persistir identidade resolvida,
criar índice/migration/permissão ou alterar o exportador, pare e reporte o
bloqueio em vez de ampliar o slice.

## Plano TDD

### RED

Adicione testes com nomes inequivocamente ligados a R1–R5 no final de
`tests/integration/test_daily_statistics_page.py` e
`tests/integration/test_daily_statistics_export.py` (reaproveite os helpers de
materialização sintética já importados). Cubra no mínimo:

- projeção de revisão com paciente resolvido: linha de paciente (`PatientRow`)
  e linha de evento carregam `patient_id` igual ao `pk` sintético;
- prontuário sem paciente correspondente: `patient_id is None`;
- dois pacientes sintéticos com o mesmo `patient_source_key` em
  `source_system` distintos: `patient_id is None` para aquela linha e o
  fallback de busca no render;
- prontuário vazio ou com apenas espaços: `patient_id is None`, não participa
  da query de resolução e o render fica sem `<a>` no nome;
- render autenticado com `view_daily_statistics`: página contém
  `href="/patients/<pk>/admissions/"` para o resolvido, `href="/patients/?q=`
  para o não resolvido, e o link aparece também na seção
  `Setor não identificado`;
- exportação com resolução ativa: workbook mantém seções, colunas e valores;
  nenhuma célula contém `patient_id` resolvido;
- atualize as duas asserções existentes citadas em R6 (elas fazem parte do
  RED planejado do slice, não de regressão acidental).

Comando focado (diagnóstico host, porta dedicada):

```bash
SIRHOSP_TEST_DB_PORT=55633 uv run pytest tests/integration/test_daily_statistics_page.py tests/integration/test_daily_statistics_export.py -q
```

- Falha esperada: os testes novos falham por `patient_id` inexistente nas
  linhas projetadas (`AttributeError`/falha de atributo em dataclass) e/ou
  ausência dos hrefs no HTML e da proteção XLSX — evidência de que o
  comportamento não existe. Registre o resumo da falha.

### GREEN

Implemente o mínimo para R1–R4 (R5–R6 ficam verdes pela construção):

1. em `presentation.py`: colete os `record` das linhas de pacientes e eventos
   de todos os grupos, normalizados com `(record or "").strip()` e ignorando
   vazios; se algum prontuário restar, resolva com uma única query
   `Patient.objects.filter(patient_source_key__in=...).values_list("patient_source_key", "id")`,
   agrupando em memória como `prontuário → lista de pks` — só prontuário com
   exatamente um candidato recebe `pk`; sem nenhum prontuário qualificado,
   use mapa vazio e não faça a query; construa `PatientRow` frozen por
   paciente e passe `patient_id` na construção de cada `EventRow` (sem query
   por linha, sem mutação de instâncias de modelo);
2. no template: envolva o nome nos dois ramos conforme R3, sem alterar
   nenhum outro elemento.
3. na docstring de `build_daily_report_projection` (mesmo arquivo do passo
   1), corrija a enumeração de consultas: hoje diz "four bulk queries --
   sectors, events, patients and the report itself" e passa a descrever as
   quatro reais (setores, eventos, pacientes e o mapa de resolução), sem
   citar o report, que chega por parâmetro e não é query da função.

O mesmo comando focado deve terminar com exit code 0 e os testes novos
passando.

### Verificação do slice (após GREEN)

Execute e registre os resultados:

```bash
SIRHOSP_TEST_DB_PORT=55633 uv run pytest tests/integration/test_daily_statistics_page.py tests/integration/test_daily_statistics_export.py -q
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/test-in-container.sh integration
openspec validate link-statistics-patients-to-admissions --strict
```

- Diagnósticos host opcionais e baratos antes dos oficiais:
  `uv run ruff check apps/statistics_reports tests/integration/test_daily_statistics_page.py tests/integration/test_daily_statistics_export.py`
  e `uv run ruff format --check ...` — a validação oficial de lint/typecheck
  é a containerizada (AGENTS.md seção 2).
- `./scripts/test-in-container.sh integration` é a regressão proporcional do
  slice (suíte de integração completa) — não rode o quality-gate completo
  aqui; ele pertence ao gate final do change.
- Não é necessário rodar a suíte unit completa: nenhuma unidade fora de
  `statistics_reports` é afetada.

## Critérios de aceitação

- [ ] R1: `patient_id` presente por linha com uma única query de resolução
- [ ] R2: política de candidato único coberta por teste (incluída ambiguidade
      entre `source_system` distintos)
- [ ] R3: três estados de render (internações, busca, texto simples) cobertos
- [ ] R4: `Setor não identificado` coberto por teste
- [ ] R5: regressão XLSX verde: colunas/valores inalterados, sem derivados da
      resolução; fingerprint e `Cache-Control` inalterados
- [ ] R6: asserções de ordenação e de orçamento de queries atualizadas
      explicitamente (não como efeito colateral)
- [ ] R7: nenhum arquivo de model/migration no diff
- [ ] RED e GREEN registrados com comando e resultado no relatório
- [ ] `/tmp/sirhosp-slice-LSPA-S1-report.md` gerado com snippets antes/depois

## Contrato de handoff

Este slice é autocontido: um worker com contexto fresco lê o handoff de
entrada, implementa R1–R4 por TDD e executa a verificação local. O worker não
atualiza `tasks.md`, não faz commit/push e escala bloqueios em vez de ampliar
o escopo.
