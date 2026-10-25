# RCD-S1 — Catálogo v6 (rename ENF-2B-CARD) + testes de contrato

## Handoff para implementador LLM com contexto zero

Leia integralmente, na ordem:

1. `AGENTS.md` e `PROJECT_CONTEXT.md`;
2. `openspec/changes/rename-enf-2b-card-display-name/proposal.md` e
   `design.md` (decisões D1–D8);
3. `openspec/changes/rename-enf-2b-card-display-name/specs/versioned-sector-capacity-catalog/spec.md`
   (delta) e, para base, os requisitos v4/v5 em
   `openspec/specs/versioned-sector-capacity-catalog/spec.md`;
4. `apps/census/data/sector_capacity_catalog_v5.json` — bloco do grupo
   `ENF-2B-CARD` (~linhas 267-281): `display_name` (:268), capacidade (:269),
   membro `719` com `source_display_name: "Cardioclínica"` (:275), membro
   `2156` com `source_display_name: "Enfermaria 2B Cardio"` (:280);
   cabeçalho do documento (`schema_version`, `source_reference`,
   `occupancy_algorithm_version`);
5. `tests/unit/test_sector_capacity_catalog.py` — padrões a espelhar:
   constantes de path (~:36-68, `V5_CATALOG`), `EXPECTED_DISPLAY_NAMES`
   (:123, cobre SOMENTE o catálogo initial — não mexer), helpers
   `_v4_document`/`_v5_document` (~:232-237), `test_v5_document_declares_new_schema_and_v5`
   (:2069), `test_v5_document_totals_and_alias_coverage` (:2074),
   `test_v5_groups_are_structurally_identical_to_v4` (:2088),
   `test_v5_hash_is_own_and_distinct_from_v4` (:2108),
   `test_v5_curated_aliases_gastro_3a_cardio_and_co` (:2163),
   `test_dry_run_reports_v5_totals_and_full_alias_coverage` (:2194),
   `test_future_activation_persists_v5_atomically` (:2268) e
   `test_v5_activation_is_idempotent_for_same_document_and_date` (:2290);
6. `apps/census/capacity_catalog.py` — SOMENTE LEITURA: `validate_catalog_document`,
   regras de alias em `_validate_membership` (~:615-676) e
   `SCHEMAS_REQUIRING_ALGORITHM` (~:459). Este change NÃO edita este arquivo.

## Protocolo obrigatório

BASE_REF + árvore limpa; baseline oficial ANTES de editar
(`./scripts/test-in-container.sh unit`; registre o passed real do commit
base); matriz requisito→arquivo→teste; RED real (comando + motivo da falha
registrado); GREEN mínimo; verificação local do slice conforme seção GREEN —
**sem** quality-gate global nem suíte completa, que pertencem ao gate final
do change (tasks.md §4). Host-only pytest é diagnóstico, não gate. Qualquer
falha de verificação local ⇒ INCOMPLETO, sem marcar `tasks.md`/commit.

## Objetivo do slice

O repositório passa a conter o catálogo v6 completo e validável:
`sector_capacity_catalog_v6.json` idêntico ao v5 exceto
`ENF-2B-CARD.display_name = "Enfermaria 2B Cardio"` (+ `source_reference`
próprio), com testes de contrato próprios provando o delta único, totais/
aliases preservados, hash próprio e ativação futura atômica/idempotente.

## Requisitos verificáveis

- **R1 — Documento v6**: arquivo
  `apps/census/data/sector_capacity_catalog_v6.json` com
  `schema_version: "3.0"`, `occupancy_algorithm_version: "occupancy-v5"` e
  `groups` idênticos aos do v5 exceto `ENF-2B-CARD.display_name` =
  `"Enfermaria 2B Cardio"` (v5 preserva
  `"Cardioclinica / Enfermaria 2B Cardio"`). `source_reference` distinto do
  v5, ≤255 caracteres, sem dados sensíveis (mesmas proibições de
  `test_v5_changes_only_algorithm_context`: sem "prontuário", "nome de
  paciente", SHA-256 de paciente).
- **R2 — Totais preservados**: `validate_catalog_document` do v6 reporta 43
  grupos, 48 memberships, 47 códigos, 39 standard, 4 unrated, 666/666,
  aliases 48/48 — idêntico ao v5.
- **R3 — Alias curated intactos**: `719 → "Cardioclínica"` e
  `2156 → "Enfermaria 2B Cardio"` no v6 (iguais ao v5).
- **R4 — Hash próprio e histórico intacto**: SHA-256 do v6 ≠ SHA-256 do v5;
  `git diff` não toca `initial_sector_capacity_catalog.json`,
  `corrected_sector_capacity_catalog.json`, `sector_capacity_catalog_v3.json`,
  `_v4.json` nem `_v5.json`.
- **R5 — Ativação futura atômica e idempotente** (db): publicação do v6 para
  data estritamente futura cria uma versão completa atomicamente; repetição
  exata é no-op idempotente (espelhos de :2268 e :2290).
- **R6 — Dry-run**: espelho de :2194 para o v6 — totais/cobertura reportados,
  nenhuma linha persistida. A cobertura de aliases 48/48 é asserida via
  `ActivationResult.aliased_membership_count`/`validate_catalog_document`
  (o comando NÃO imprime essa métrica no stdout — ver
  `activate_sector_capacity_catalog.py:63-77`).

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) esperado(s)                                                                           | Teste/check                                                                                                                                           |
| --------- | ------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| R1        | `apps/census/data/sector_capacity_catalog_v6.json`, `tests/unit/test_sector_capacity_catalog.py` | `test_v6_document_declares_schema_and_algorithm_context`, `test_v6_changes_only_source_reference_context`, `test_v6_renames_only_cardio_display_name` |
| R2        | `tests/unit/test_sector_capacity_catalog.py`                                                     | `test_v6_document_totals_and_alias_coverage_match_v5`                                                                                                 |
| R3        | `tests/unit/test_sector_capacity_catalog.py`                                                     | `test_v6_curated_cardio_aliases_unchanged`                                                                                                            |
| R4        | `apps/census/data/sector_capacity_catalog_v6.json`                                               | `test_v6_hash_is_own_and_distinct_from_v5` + `git diff --stat` (check)                                                                                |
| R5        | `tests/unit/test_sector_capacity_catalog.py`                                                     | `test_future_activation_persists_v6_atomically`, `test_v6_activation_is_idempotent_for_same_document_and_date`                                        |
| R6        | `tests/unit/test_sector_capacity_catalog.py`                                                     | `test_dry_run_reports_v6_totals_and_full_alias_coverage`                                                                                              |

Padrão de escrita: constantes `V6_CATALOG` (ao lado de `V5_CATALOG`) e helper
`_v6_document()` (ao lado de `_v5_document()`); testes novos ao lado dos
equivalentes v5, na mesma classe/estilo local. Nenhum teste existente é
editado.

Conteúdo mínimo dos testes novos:

- `test_v6_document_declares_schema_and_algorithm_context`:
  `schema_version == "3.0"`; `occupancy_algorithm_version == "occupancy-v5"`.
- `test_v6_changes_only_source_reference_context` (espelho de
  `test_v5_changes_only_algorithm_context`, :2092-2106):
  `set(v6) == set(v5)`; `schema_version` igual;
  `occupancy_algorithm_version` IGUAL (`"occupancy-v5"` em ambos — o
  algoritmo não muda); `source_reference` distinto do v5, `len` ≤ 255 e sem
  os marcadores proibidos ("prontuário", "nome de paciente",
  "sha-256 de paciente").
- `test_v6_renames_only_cardio_display_name`: partindo de `_v5_document()`,
  trocar apenas o `display_name` de `ENF-2B-CARD` reproduz exatamente os
  `groups` do v6 (delta único, prova bidirecional); e v5 mantém o nome
  composto.
- `test_v6_document_totals_and_alias_coverage_match_v5`: métricas do
  `validate_catalog_document(_v6_document())` iguais às do v5 (43/48/47, 39
  standard, 4 unrated, 666/666, aliases 48/48).
- `test_v6_curated_cardio_aliases_unchanged`: `aliases["719"] ==
"Cardioclínica"`; `aliases["2156"] == "Enfermaria 2B Cardio"`.
- `test_v6_hash_is_own_and_distinct_from_v5`: len 64 e diferente do sha256 do
  arquivo v5 (siga o padrão local de `HISTORICAL_JSON_SHA256` se aplicável).
- `test_future_activation_persists_v6_atomically` /
  `test_v6_activation_is_idempotent_for_same_document_and_date` /
  `test_dry_run_reports_v6_totals_and_full_alias_coverage`: espelhos diretos
  dos testes v5 (:2268, :2290, :2194) trocando o documento.

## Arquivos esperados e limite

Máximo de **2 arquivos**:

1. `apps/census/data/sector_capacity_catalog_v6.json` (novo);
2. `tests/unit/test_sector_capacity_catalog.py` (apenas adições).

`allowed_incidental_files`: nenhum. Fora de escopo (proibido):
catálogos históricos (`initial`, `corrected`, `v3`, `v4`, `v5`), QUALQUER
arquivo em `apps/` que não seja o JSON novo (em especial
`apps/census/capacity_catalog.py`, models, views), `EXPECTED_DISPLAY_NAMES`,
testes existentes, dependências. Precisando de outro arquivo, pare e peça
emenda.

## TDD obrigatório

### RED (falhando pelo motivo certo antes da implementação)

Adicione SOMENTE o código de teste (constantes, helpers e testes da matriz).
O JSON v6 NÃO existe ainda. Comando focado (mesmo compose/runner dos scripts
oficiais; em ambiente sujo/flaky, use `./scripts/test-in-container.sh unit` e
registre o custo):

```bash
docker compose -p sirhosp-test -f compose.yml -f compose.test.yml up -d db
docker compose -p sirhosp-test -f compose.yml -f compose.test.yml run --rm \
  test-runner bash -lc "uv run --no-sync pytest -q -p no:cacheprovider \
  tests/unit/test_sector_capacity_catalog.py -k v6"
```

Falha esperada: `FileNotFoundError` ao ler
`apps/census/data/sector_capacity_catalog_v6.json` (constante/helper novos
apontam para arquivo inexistente) — NÃO por erros de import/sintaxe nem por
falhas em testes v3/v4/v5 existentes. O subconjunto `-k v6` inclui os testes
db-backed (R5/R6), que exigem o db do compose acima.

### GREEN / verificação local

1. Criar o JSON v6 conforme D2 (cópia byte-fiel do v5 com só o delta
   declarado — compare com `diff` após gerar; NÃO reformatar o v5).
2. Mesmo comando do RED — resultado esperado: exit 0.
3. Regressão próxima: arquivo completo
   `tests/unit/test_sector_capacity_catalog.py` no container — exit 0 (prova
   que contratos v3/v4/v5 e `EXPECTED_DISPLAY_NAMES` continuam válidos com o
   v6 presente).
4. Lint do arquivo Python alterado:
   `uv run ruff check tests/unit/test_sector_capacity_catalog.py` — exit 0;
   `uv run ruff format --check` — exit 0 OU, quando houver drift pré-existente
   do BASE_REF, prova de **zero drift incremental** (mesmos hunks do commit
   base, nenhum hunk tocando as adições; precedente Emenda B do change
   arquivado `2026-09-21-censo-residual-finding-filter`, ver Emenda A em
   `tasks.md` deste change).
5. Check R4: `git diff --stat` sem nenhum catálogo histórico.

Não rode a suíte completa nem o quality-gate global dentro do slice; eles
pertencem ao gate final do change (tasks.md §4).

## Critérios de aceitação

- [ ] R1–R6 demonstrados pelos testes da matriz (GREEN, exit 0);
- [ ] RED real registrado (comando + motivo: FileNotFoundError do v6);
- [ ] Diff ≤ 2 arquivos; catálogos históricos byte-preserved;
- [ ] `source_reference` do v6 distinto, ≤255 chars, sem dados sensíveis;
- [ ] SHA-256 do v6 registrado no relatório;
- [ ] Relatório `/tmp/sirhosp-slice-RCD-S1-report.md` com RED/GREEN, snippets
      antes/depois (bloco ENF-2B-CARD v5 → v6), comandos + exit codes, riscos
      e handoff para o verificador.

## Bloqueios conhecidos

- Se qualquer teste EXISTENTE quebrar com o v6 presente, NÃO edite o teste:
  registre e reporte INCOMPLETO (conflito de contrato ⇒ escalonamento humano).
- Se o validador rejeitar a colisão `display_name` == alias do membro `2156`
  (D3 diz que não rejeita), NÃO contorne: reporte INCOMPLETO com a mensagem
  exata do validador.
