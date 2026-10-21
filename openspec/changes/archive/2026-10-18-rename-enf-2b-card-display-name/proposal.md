# Proposal — `rename-enf-2b-card-display-name`

## Problema

Na página `/beds`, a unidade correspondente ao grupo de capacidade
`ENF-2B-CARD` é exibida com o `display_name` composto
`Cardioclinica / Enfermaria 2B Cardio`. Esse grupo agrega dois códigos
oficiais do cadastro de setores: `719` (`0 N - CARDIOCLINICA`, alias limpo
`Cardioclínica`) e `2156` (`2 7 - 2B - CARDIO - HGRS`, alias limpo
`Enfermaria 2B Cardio`). Como a listagem de unidades é ordenada
alfabeticamente pelo título (`apps/census/occupancy.py:4195`, caminho v5),
o nome
composto — que começa por "Cardioclinica" — afasta a unidade das demais
enfermarias do segundo andar (`Enfermaria 2A…`, `Enfermaria 2B Neuroclínica`,
`Enfermaria 2C…`), dificultando sua localização visual pela equipe.

O nome composto não é um setor do cadastro `Ward`: é o `display_name` do
grupo declarado no catálogo versionado de capacidade
(`apps/census/data/sector_capacity_catalog_v5.json:268`, persistido em
`CapacityGroupDefinition.display_name`). Renomear o grupo, portanto, é uma
mudança de dado versionado do catálogo — não de código.

## Objetivo

Renomear o `display_name` do grupo `ENF-2B-CARD` para `Enfermaria 2B Cardio`
por meio de uma **nova versão do catálogo (v6)**, preservando aliases por
código, capacidades, políticas, memberships e o contexto de algoritmo
(`occupancy-v5`). Após a publicação para data efetiva estritamente futura
(comando atômico já existente), todas as telas que exibem o título do grupo —
incluindo `/beds` — passam a mostrar o nome novo, posicionando a unidade junto
das outras enfermarias do segundo andar na ordenação alfabética.

## Valor operacional

- Equipe de enfermagem e gestão localiza a enfermaria 2B Cardio rapidamente
  na listagem alfabética de `/beds`.
- Nome único e consistente em todas as superfícies que usam o título oficial
  do grupo (sem divergência de rótulo entre telas).
- Histórico preservado: medições e materializações anteriores mantêm o
  rótulo da época (imutabilidade, ADR-0003).

## Escopo incluído

- Novo arquivo `apps/census/data/sector_capacity_catalog_v6.json` — cópia do
  v5 com único delta de grupos: `display_name` de `ENF-2B-CARD` =
  `Enfermaria 2B Cardio`; `source_reference` próprio (≤255 caracteres, sem
  dados sensíveis); `schema_version: 3.0` e
  `occupancy_algorithm_version: occupancy-v5` mantidos.
- Testes de contrato v6 em `tests/unit/test_sector_capacity_catalog.py`
  (apenas adições, espelhando o padrão dos testes v5).
- Teste de caracterização de título + ordenação em
  `tests/unit/test_bed_status_view.py` (apenas adições).
- Deltas de spec: `versioned-sector-capacity-catalog` (requisito v6) e
  `bed-status-capacity-view` (título do grupo pela versão vigente).
- Runbook de publicação (`activation-runbook.md` do change) e prova local de
  `--dry-run` em container.

## Escopo excluído (não-objetivos)

- Editar catálogos históricos (`initial`, `corrected`, `v3`, `v4`, `v5`) ou
  quaisquer testes existentes (incluindo identidades estruturais
  v3↔v4↔v5 e `EXPECTED_DISPLAY_NAMES`, que cobre apenas o catálogo initial).
- Alterar aliases limpos por código (`719 → Cardioclínica`;
  `2156 → Enfermaria 2B Cardio`), capacidades, políticas, memberships,
  seletores etários ou `occupancy_algorithm_version`.
- Qualquer mudança em código de produção (views, services, templates,
  models, migrations, dependências) — o título e a ordenação já emergem do
  `display_name` persistido.
- Execução da publicação em produção: é ação operacional do operador,
  pós-deploy, conforme runbook (tasks §5).
- Renomear o grupo de forma divergente entre telas (alias de apresentação
  local) — rejeitado em favor da consistência do catálogo (design D7).

## Riscos

- **Baixo** no código: nenhum arquivo de produção é alterado; o diff é um
  JSON novo + testes.
- Risco 1: o novo `display_name` colide com o alias limpo do membro `2156`.
  Verificado que o validador (`capacity_catalog.py`, `_validate_membership`)
  não proíbe essa colisão (design D3).
- Risco 2: superfícies além de `/beds` (dashboards de ocupação, sumários)
  mudarão de rótulo juntas após a vigência — aceito explicitamente pelo
  operador (2026-09-22).
- Risco 3: publicação incorreta é irreversível (catálogo imutável,
  ADR-0003). Mitigação: `--dry-run` obrigatório + conferência de hash +
  runbook com idempotência.

## Critérios de sucesso

- v6 valida com totais/aliases idênticos aos do v5 (43 grupos, 48
  memberships, 47 códigos, 39 standard, 4 unrated, 666/666, aliases 48/48)
  e único delta `ENF-2B-CARD.display_name = "Enfermaria 2B Cardio"`;
  arquivos históricos byte-preserved e testes existentes verdes.
- Com catálogo vigente contendo o rename, `/beds` exibe a unidade
  `Enfermaria 2B Cardio` posicionada junto das demais unidades
  `Enfermaria 2…` na ordenação por título (pino de caracterização verde).
- Após publicação na data acordada, o primeiro dia local integral usa v6;
  medições de dias anteriores preservam o rótulo antigo, sem backfill.
- Quality gate oficial verde; `openspec validate --strict` e markdown lint
  sem erros.
