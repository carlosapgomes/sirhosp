# Design — `rename-enf-2b-card-display-name`

## Contexto de investigação (evidências)

- Cadeia `/beds`: `apps/census/urls.py:11` → `bed_status_view`
  (`apps/census/views.py:109-206`) → `build_units_presentation`
  (`apps/census/occupancy.py:4279+`) → `census/bed_status.html:654`
  renderiza `{{ unit.title }}`. Ordenação: `sorted(units, key=lambda unit:
  unit.title)` (`occupancy.py:4195`, caminho v5; caminhos legados repetem o
  padrão em `:3369` e `:3642`).
- O título de unidade com um único grupo oficial é o `display_name` do grupo
  (`_component_title`, `occupancy.py:3189-3206`).
- Grupo `ENF-2B-CARD` (`sector_capacity_catalog_v5.json:267-281`):
  `display_name: "Cardioclinica / Enfermaria 2B Cardio"` (sem acento no
  primeiro termo), capacidade 15, membros `719`
  (`configured_source_name: "0 N - CARDIOCLINICA"`,
  `source_display_name: "Cardioclínica"`) e `2156`
  (`configured_source_name: "2 7 - 2B - CARDIO - HGRS"`,
  `source_display_name: "Enfermaria 2B Cardio"`).
- Contrato de rótulos: ADR-0006 e design do change arquivado
  `2026-08-26-make-occupancy-quality-actionable` —
  `configured_source_name` = nome bruto (auditoria/drift);
  `source_display_name` = rótulo humano por código; `display_name` do grupo =
  rótulo oficial usado na UI.
- Teste sintético existente `test_cardio_shared_group_two_sources_capacity_once`
  (`tests/unit/test_bed_status_view.py:~2334`) já usa catálogo com
  `display_name: "Enfermaria 2B Cardio"` e afirma
  `unit.title == "Enfermaria 2B Cardio"` — ou seja, a tubulação já suporta o
  estado-alvo sem mudança de código.

## Decisões

### D1 — Renomear via nova versão v6, nunca editando v5 in-place

Os JSONs do catálogo são versões históricas imutáveis (ADR-0003) e os testes
de identidade estrutural (`test_v4_structural_groups_match_v3_except_aliases`,
`test_v5_groups_are_structurally_identical_to_v4`) fixam que cada versão nova
declara explicitamente seu delta. Editar o v5 falsificaria o histórico e
quebraria essa cadeia. O v6 é um arquivo novo cujo único delta de grupos é o
`display_name` de `ENF-2B-CARD`.

### D2 — Conteúdo exato do v6

- Cópia integral do `sector_capacity_catalog_v5.json` com as alterações:
  1. `groups[ENF-2B-CARD].display_name` = `"Enfermaria 2B Cardio"`;
  2. `source_reference` novo, distinto do v5, ≤255 caracteres, sem dados de
     pacientes (mesmas proibições do teste `test_v5_changes_only_algorithm_context`).
- Mantidos: `schema_version: "3.0"`,
  `occupancy_algorithm_version: "occupancy-v5"` (o algoritmo não mudou — é
  desonesto declarar algoritmo novo), todos os demais grupos, memberships,
  aliases, capacidades e políticas byte-idênticos ao v5.

### D3 — Colisão `display_name` == alias do membro `2156` é permitida

O validador (`capacity_catalog.py`, `_validate_membership` e regra de
partição etária) exige alias não vazio, limites de tamanho e igualdade de
alias entre partições etárias do mesmo código — não existe regra contra
colisão entre `display_name` do grupo e `source_display_name` de membro. A
única asserção anti-colisão do projeto é uma propriedade de dados do código
`654` no teste do catálogo v4 (não afetada: v4 permanece intocado).

### D4 — Nenhuma mudança de código de produção

Título e ordenação emergem do `display_name` persistido da versão vigente.
Não há string do nome composto em templates, views ou services (busca no repo
encontra o nome composto apenas nos JSONs de catálogo, testes e artefatos
OpenSpec históricos). O pino de caracterização do slice S2 exercita a lógica
compartilhada de apresentação via helper sintético que grava
`algorithm_version: "occupancy-v4"` — a lógica de título/ordenação é idêntica
nos caminhos v4/v5 (`_component_title` + sort por título); a aplicabilidade
literal do v6 é comprovada pelos testes de contrato do S1 e pela verificação
operacional pós-publicação (tasks §5.2).

### D5 — Aliases por código permanecem intocados

`719 → Cardioclínica` e `2156 → Enfermaria 2B Cardio` continuam declarados no
v6 (contrato MOQA-S2 e testes `test_curated_aliases_gastro_3a_cardio_and_co`
/ `test_v5_curated_aliases_gastro_3a_cardio_and_co`). A linha de origem
`Cardioclínica` continua visível como proveniência secundária em `/beds`.

### D6 — Rollout: ativação explícita, futura, atômica e idempotente

O v6 é publicado apenas via `activate_sector_capacity_catalog` com
`--effective-from` estritamente futuro (America/Bahia), após o release
contendo o arquivo estar deployado e saudável. Build, migração e startup não
publicam catálogo. Nenhum dia local mistura v5 e v6. Publicação é
irreversível (sem unpublish); correção futura de rótulo = v7 com delta
próprio. Detalhes operacionais em `activation-runbook.md`.

### D7 — Alternativa rejeitada: alias de apresentação só no `/beds`

Um mapeamento de exibição por `stable_key` em `build_units_presentation`
divergiria do padrão ADR-0006 (rótulo oficial único no catálogo) e criaria
nomes diferentes para o mesmo grupo entre telas. Operador escolheu rename no
catálogo, valendo para todas as superfícies (2026-09-22).

### D8 — Efeito colateral aceito: rótulo muda em todas as telas

Dashboards de ocupação, sumários e findings que exibem o título do grupo
passarão a mostrar `Enfermaria 2B Cardio` a partir da vigência. Medições
anteriores preservam o rótulo antigo (imutabilidade), então relatórios
históricos não são reescritos.

## Impacto por camada

- **Dados versionados**: +1 arquivo JSON (v6). Sem migration, sem model.
- **Testes**: apenas adições em `tests/unit/test_sector_capacity_catalog.py`
  e `tests/unit/test_bed_status_view.py`.
- **Scraping/censo**: intacto — `CensusSnapshot.setor`/`setor_codigo` não
  mudam; o mapeamento código→grupo continua pelo `source_code`.
- **Operação**: um comando de ativação manual com data futura aprovada.
