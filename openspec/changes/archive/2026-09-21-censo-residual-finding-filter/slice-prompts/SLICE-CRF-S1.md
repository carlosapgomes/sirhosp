# CRF-S1 — Filtro "Suspeita de paciente residual" em `/censo/` + export WYSIWYG

## Handoff para implementador LLM com contexto zero

Leia integralmente, na ordem:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. `openspec/changes/censo-residual-finding-filter/proposal.md`,
   `design.md` (decisões D1–D6) e `tasks.md`;
3. `openspec/specs/censo-current-list-export/spec.md` (base) e o delta
   `specs/censo-current-list-export/spec.md` do change;
4. `apps/services_portal/views.py` — `_build_censo_context` (~952–1171;
   filtros ~997–1013, anexo de findings ~1103–1117, ordenação ~1120–1131,
   retorno ~1159–1171), `censo` (~1173), `censo_export_xlsx` (~1187, chamada
   `include_findings=False` e docstring de query params) e o import block
   `apps.ingestion.patient_flow_findings` (~73–76);
5. `apps/services_portal/templates/services_portal/censo.html` — form de
   filtros (~39–92), badge desktop (~108–117), badge mobile (~159–166),
   TomSelect restrito a `#unidade`/`#especialidade` (~202–225);
6. `tests/integration/test_censo_patient_flow_findings.py` — helpers
   `make_patient` (~84), `make_census_row` (~92), `make_active_admission`
   (~134), `make_event` (~153), `make_movement` (~844);
   `test_filters_still_work_with_findings` (~707, padrão de teste de
   filtros), teste de query count (~788, padrão `CaptureQueriesContext`),
   teste de headers XLSX em `TestCensoContractsPreserved` (~742);
7. `apps/ingestion/patient_flow_findings.py` — SOMENTE LEITURA:
   `CODE_SUSPECTED_LEGACY_RESIDUAL`, `PatientFlowFinding.code` (contrato;
   este change não pode editar este arquivo).

## Protocolo obrigatório

BASE_REF + árvore limpa; baselines oficiais ANTES de editar
(`./scripts/test-in-container.sh unit` e `integration`; registre os valores
reais de passed do commit base); matriz requisito→arquivo→teste; RED real
(comando + motivo da falha registrado); GREEN mínimo; verificação local do
slice conforme a seção “GREEN / verificação local” — **sem** quality-gate
nem suíte completa, que são exclusivamente o gate final do change
(tasks.md §2); relatório evidencial. Qualquer falha de verificação local ⇒
INCOMPLETO sem marcar `tasks.md`/commit. Host-only pytest é diagnóstico,
não gate.

## Objetivo do slice

A página `/censo/` ganha um filtro "Situação" com a opção "Suspeita de
paciente residual": com `?finding=residual`, a lista (desktop e mobile) e o
total exibem somente pacientes cujo achado corrente é exatamente
`suspected_legacy_residual`, combinando com `q`, `unidade`,
`especialidade` e `ordenar`. O export XLSX com o mesmo param produz
exatamente as linhas da página filtrada (mesmas colunas de hoje, sem label
de achado); sem o param, página e export comportam-se como hoje (export sem
rodar o classificador).

## Requisitos verificáveis

- **R1 — View/filtro**: `_build_censo_context` lê `request.GET["finding"]`
  (strip); valor `residual` filtra `pacientes` EM PYTHON, após o anexo de
  `p["finding"]` e ANTES da ordenação, por
  `p.get("finding") and p["finding"].code == CODE_SUSPECTED_LEGACY_RESIDUAL`
  (import adicionado ao block existente ~73–76). Vazio/desconhecido ⇒ sem
  filtro. Contexto expõe `finding_filter` em AMBOS os retornos (inclui o
  early-return de snapshot vazio).
- **R2 — Export WYSIWYG (D3)**: achados são computados quando
  `include_findings or (finding == "residual")`; o export
  (`include_findings=False`) passa a aplicar o filtro quando o param está
  presente, sem adicionar coluna/label. Sem o param, o export não roda o
  classificador (comportamento/custo atuais). Docstring de
  `censo_export_xlsx` atualizada citando `finding`.
- **R3 — Template**: `select` "Situação" (`id`/`name` `finding`,
  `form-select` puro como `#ordenar`; TomSelect NÃO estendido) com opções
  "Todos os pacientes" (value "") e "Suspeita de paciente residual" (value
  `residual`), `selected` refletindo `finding_filter`; classes de coluna do
  form ajustadas para o grid desktop continuar somando 12 colunas e o
  mobile empilhando (`col-6`/`col-12` como nos demais).
- **R4 — Orçamento bounded**: nenhuma query nova por paciente; query count
  da página com filtro == sem filtro; teste de query count existente (~788)
  permanece verde sem edição.
- **R5 — Semântica exata**: pacientes `mirror_stale_admission` ou qualquer
  outro achado NÃO aparecem com o filtro ativo (prova por teste com coorte
  mista).

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| R1 | `apps/services_portal/views.py` | `test_residual_filter_returns_only_residual_patients`, `test_residual_filter_defaults_and_unknown_values` |
| R2 | `apps/services_portal/views.py` | `test_export_applies_residual_filter`, `test_export_without_finding_filter_unchanged` |
| R3 | `apps/services_portal/templates/services_portal/censo.html` | assert `selected`/option em `test_residual_filter_defaults_and_unknown_values` |
| R4 | `apps/services_portal/views.py` | `test_residual_filter_query_count_unchanged` (padrão ~788) |
| R5 | `apps/services_portal/views.py` | coorte mista em `test_residual_filter_returns_only_residual_patients` |
| R1+R2 | `apps/services_portal/views.py` | `test_residual_filter_without_matches_renders_empty_state_and_valid_export` |

Todos os testes em NOVA classe `TestCensoFindingFilter` (apenas adições) em
`tests/integration/test_censo_patient_flow_findings.py`, reusando os helpers
existentes. Fixtures sintéticas: residual = linha de censo + `Patient` +
admissão ativa ≥ 48h + sem evento nas últimas 48h + sem movimento;
mirror_stale = residual + `make_movement` dentro de 48h; saudável =
admissão < 48h (ou evento recente); coorte sem residual = apenas saudável
e mirror_stale (para o caso de filtro sem correspondência).

Comportamento conhecido (pinar, não corrigir): com filtros que resultam em
lista vazia, a página já exibe hoje o estado vazio genérico (“Nenhum
paciente internado no momento”) — comportamento pré-existente compartilhado
com `q`/`unidade`/`especialidade`; reescrever essa mensagem é fora de
escopo. O teste deve pinar: HTTP 200 + estado vazio atual na página e
workbook válido só com headers no export.

## Arquivos esperados e limite

Máximo de **3 arquivos**:

1. `apps/services_portal/views.py`;
2. `apps/services_portal/templates/services_portal/censo.html`;
3. `tests/integration/test_censo_patient_flow_findings.py` (apenas adições).

`allowed_incidental_files`: nenhum. Fora de escopo (proibido):
`apps/ingestion/patient_flow_findings.py`, `tests/unit/`
`test_services_portal_censo.py` (não deve precisar mudar), models,
migrations, URLs, `/beds`, admissões, JS/TomSelect, dependências. Precisando
de outro arquivo, pare e peça emenda.

## TDD obrigatório

### RED (falhando pelo motivo certo antes da implementação)

Comando focado (mesmo compose/runner dos scripts oficiais; diferença: sem
pre-clean de sessões de teste, espera robusta de db nem teardown — em
ambiente sujo ou flaky, use `./scripts/test-in-container.sh integration` e
registre o custo):

```bash
docker compose -p sirhosp-test -f compose.yml -f compose.test.yml up -d db
docker compose -p sirhosp-test -f compose.yml -f compose.test.yml run --rm \
  test-runner bash -lc "uv run --no-sync pytest -q -p no:cacheprovider \
  tests/integration/test_censo_patient_flow_findings.py -k TestCensoFindingFilter"
```

Falha esperada: os testes de COMPORTAMENTO (filtro na página, export
WYSIWYG, `selected`) falham por ausência do comportamento (página retorna
coorte completa com `?finding=residual`; export contém todas as linhas;
`selected` ausente), NÃO por erro de fixture/import. O guard de query count
(R4) pode já passar no RED — é proteção de regressão e deve continuar
verde no GREEN.

### GREEN / verificação local

1. Mesmo comando do RED — resultado esperado: exit code 0.
2. Arquivo completo afetado:
   `./scripts/test-in-container.sh integration` é o gate; para foco,
   rode o arquivo inteiro
   (`tests/integration/test_censo_patient_flow_findings.py`) no container —
   exit 0, incluindo os contratos preservados (~707, ~742, ~788).
3. Regressão próxima: `./scripts/test-in-container.sh unit` (cobertura de
   `test_services_portal_censo.py`) — exit 0.
4. Lint dos arquivos Python alterados — `apps/services_portal/views.py` E
   `tests/integration/test_censo_patient_flow_findings.py`:
   `uv run ruff check <arquivos>` e `uv run ruff format --check <arquivos>`
   — exit 0 (host serve para ruff; pytest host não é gate).

Não rode a suíte completa nem o quality-gate global dentro do slice; eles
pertencem ao gate final do change (tasks.md §2).

## Critérios de aceitação

- [ ] R1–R5 demonstrados pelos testes da matriz (GREEN, exit 0);
- [ ] RED real registrado (comando + motivo) antes da implementação;
- [ ] Diff ≤ 3 arquivos, sem toque no classificador/models/URLs;
- [ ] Export com filtro = linhas da página; colunas/headers inalterados;
- [ ] Sem o param: página e export idênticos ao comportamento atual;
- [ ] Relatório `/tmp/sirhosp-slice-CRF-S1-report.md` com RED/GREEN,
      snippets antes/depois por arquivo, comandos + exit codes, riscos e
      handoff para o verificador.

## Bloqueios conhecidos

- Se algum teste existente de contrato (~707/~742/~788) quebrar por causa da
  mudança, NÃO edite o teste para acomodar: registre o conflito e reporte
  INCOMPLETO (conflito de spec ⇒ escalonamento humano).
