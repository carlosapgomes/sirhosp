# Design: improve-beds-v5-page-ux

## Contexto

Produção roda `v0.1.0-rc.11` com `occupancy-v5` vigente desde 2026-08-26
(catálogo 5, hash `c84af977…`). O primeiro censo natural produziu 607/666 =
91,14%, ponte `650 = 8 duplicadas + 607 standard + 35 unrated`, saldo 79,
excedente 20, 17 pacientes sem leito, estados operacionais
`empty 75 · reserved 114 · maintenance 4 · isolation 1`, 3A `21/32` e `25/16`.
A auditoria do CIPOO-S6 aprovou a semântica e registrou dois problemas de
apresentação: métricas escondidas no corpo dos cards e ~140 queries na
renderização autenticada.

A página v5 é renderizada por `build_units_presentation` em
`apps/census/occupancy.py` (branch `algorithm_version == "occupancy-v5"`), que
monta `_V5UnitRow` (título, `official_rows`, `sources`, `patients`,
`operational_rows`, `incomplete_rows`, casos de leito compartilhado) a partir
de valores persistidos; o template `bed_status.html` apenas apresenta. Toda
mudança deste change respeita esse contrato: nada de lógica de negócio no
template, nada de recálculo na view, nada de persistência nova.

## Objetivos

- Leitura rápida da situação real do hospital em nível agregado.
- Métricas oficiais visíveis sem expandir os cards.
- Redução de ruído (badges redundantes por paciente, contagem de códigos no
  cabeçalho, ponte ocupando o topo).
- Custo de queries proporcional ao tamanho da página, não ao catálogo.

## Não objetivos

- Mudar cálculo, catálogo, medições, resumos diários ou migrations.
- Tocar nas branches históricas v1–v4 da página (inclusive as pontes v3/v4,
  que permanecem onde estão).
- Redesenho visual além de badges Bootstrap existentes.

## Decisões

### D1 — Resumo da situação real após o resumo oficial

Nova seção `Situação real do hospital` (id `real-situation-heading`)
renderizada somente na branch v5, entre `official-heading` e `units-heading`.
Conteúdo exclusivamente de `measurement.physical_reconciliation_json`:

- total de pacientes identificados = `standard_identified_patients +
  unrated_identified_patients + linked_pending_identified_patients +
  unmapped_identified_patients`, com subtítulo `N na taxa oficial ·
  N fora da taxa` (fora = total − standard);
- contagens dos quatro estados operacionais canônicos
  (`empty`, `reserved`, `maintenance`, `isolation`) a partir de
  `operational_rows_by_status`;
- `identificação incompleta (não contada): N` somente quando
  `incomplete_identity_rows > 0`.

Cálculo em dataclass efêmera `_V5RealTotals` construída em
`build_units_presentation` (branch v5) e exposta como
`physical.v5_real`; guard para reconciliação ausente simplesmente oculta a
seção. Nenhuma soma acontece no template além da exibição de valores
pré-computados.

### D2 — Ponte v5 ao fim e recolhida

A seção `Como os pacientes foram contados` (ids `patient-bridge-heading` e
conteúdo atuais) passa a ser renderizada **após** a seção da lista de setores,
dentro de container `collapse` sem classe `show`, com gatilho
`data-bs-toggle="collapse"` e `aria-expanded="false"`, no mesmo padrão visual
dos cards de setor. O conteúdo agregado permanece idêntico. As pontes v3/v4 e
todas as branches históricas não mudam.

### D3 — Métricas por grupo no cabeçalho do card

`_V5UnitRow` ganha `header_metrics: list[_V5HeaderMetric]`, derivada dos
valores já persistidos em `official_rows` (`occupied_count`,
`official_capacity`, `occupancy_percentage`, `official_availability`,
`exceeded_by`, `calculation_status`) — sem nenhuma nova contagem:

- grupo calculável dentro da capacidade: `[N pacientes] [Cap. X] [Y%]
  [Saldo Z]`;
- grupo acima da capacidade: `[N pacientes] [Cap. X] [Y%] [Acima da
  capacidade · excedente W]`, mantendo o fundo vermelho existente;
- grupo unrated: `[N pacientes] [fora da taxa oficial]`, sem capacidade,
  taxa ou saldo;
- grupo com cálculo pendente: `[N pacientes] [cálculo pendente]`;
- grupo standard sem capacidade cadastrada: `[N pacientes] [Capacidade não
  cadastrada]`;
- unidade sem `official_rows` (unmapped): `[N pacientes]` + badge existente
  `sem mapeamento no catálogo`.

`0 pacientes` é sempre explícito (o badge não depende de `{% if %}`).
Formatação numérica idêntica à dos badges do corpo (`|floatformat:2`,
`pluralize`).

### D4 — 3A por partição, sem total combinado

Quando a unidade tem mais de um `official_row` (caso 3A: `OBST-3A-ADULTO` e
`OBST-3A-INFANTIL`), cada `header_metric` recebe rótulo curto derivado
deterministicamente do `display_name` persistido: o sufixo após o travessão
(`Enfermaria 3A – Adulto` → `Adulto`); sem travessão ou com um único grupo, o
rótulo é vazio/`display_name`. Formato por partição: `[Adulto: 21/32 ·
65,63% · saldo 11]`. A proibição de indicador combinado `3A total 48`
(ADR-0007) permanece; nenhum campo novo é persistido.

### D5 — Menos ruído no cabeçalho e nos pacientes

- O badge `N códigos de origem` sai do cabeçalho v5; aliases e códigos
  permanecem no corpo do card e o cabeçalho v4 permanece como está.
- Os badges por paciente `contado na taxa oficial` / `fora da taxa oficial`
  são removidos: a política de contagem já é comunicada pelo cabeçalho da
  unidade (D3) e pelos cards oficiais. Exceções factuais permanecem por
  paciente: `Prontuário informado em mais de um setor oficial neste censo`,
  nota de nome variante, `sem leito informado` e leitos compartilhados.
- Código morto resultante (`counted_policy`, `counted_label` em
  `_V5PatientItem`, `_v5_counted_policy`, `_V5_COUNTED_LABELS`) é removido
  somente se `rg` provar ausência de outros usos.

### D6 — Fim do N+1 com orçamento de queries

A auditoria S6 mediu ~140 queries para 42 unidades/43 grupos. O padrão vem de
`_catalog_components` e `_v5_units` iterando `catalog.groups.all()` e
`definition.memberships.all()` sem prefetch, sobre a medição carregada por
`resolve_exact_measurement` (que já faz `select_related("catalog")` e
`prefetch_related("groups")`). Correção: `prefetch_related` de
`catalog__groups__memberships` no caminho exact-run usado por `/beds`, no
ponto mais estreito e correto (`resolve_exact_measurement`, a menos que a
implementação prove ponto melhor). Teste de orçamento: renderizar `/beds`
autenticado com catálogo de 4 grupos e depois com catálogo de 12 grupos
(censos sintéticos independentes, o segundo mais recente) e exigir que a
diferença de queries seja ≤ 8 — o padrão N+1 produziria crescimento linear
(~16). Sem mudança comportamental; todos os testes S1/S2 permanecem verdes.

### D7 — RC12 somente UI, deploy padrão

`v0.1.0-rc.12` contém apenas apresentação (S1–S3): sem migrations (verificado
por `git log v0.1.0-rc.11..HEAD -- 'apps/*/migrations'` vazio), sem catálogo
novo, sem comando de ativação — `occupancy-v5` já é vigente. Deploy segue o
runbook existente: preflight, drenagem da fila, backup protegido com SHA-256,
pull por tag exata, `config --quiet`, `up -d`, health 200, `/beds` anônimo
302, dez `persistent_worker`, verificação por agregados (presença de
`Situação real do hospital` e de `Cap.` nos cabeçalhos, sem PHI no relatório).
Rollback = redeploy da RC11: sem mudança de schema, dados v5 imutáveis são
independentes da UI.

### D8 — Privacidade e autorização inalteradas

Todo o novo conteúdo da página é agregado (contagens persistidas) ou efêmero
em memória. Nomes/prontuários/leitos continuam restritos ao HTML autenticado
exact-run; anônimo continua 302; relatórios e testes continuam sintéticos,
sem PHI. Nenhum dado nominal entra em `_V5RealTotals` ou
`_V5HeaderMetric`.

## Riscos e mitigações

- **Regressão v1–v4**: branches históricas intocadas; testes de regressão
  existentes são pré-requisito dos slices; inspeções `rg` confirmam que
  mudanças ficam no branch v5.
- **Duplicidade de labels no cabeçalho e no corpo**: aceita por decisão — o
  corpo permanece como detalhamento; o cabeçalho usa os mesmos valores
  persistidos, nunca recalculados.
- **Orçamento de queries frágil em CI**: teste compara crescimento entre
  cenários, não total absoluto; folga de 8 queries absorve variações de
  ambiente.
- **Deploy de UI em produção com v5 já ativo**: RC12 não toca schema nem
  catálogo; rollback trivial; validação pós-deploy somente por agregados.

## Plano de testes

- S1: posição das seções por ordem dos ids no HTML; valores do resumo real a
  partir de reconciliação sintética (soma fecha; estados; incompleta omitida
  quando zero); ponte após a lista, `collapse` sem `show`,
  `aria-expanded="false"`; conteúdo da ponte inalterado; regressão v1–v4.
- S2: cabeçalhos por unidade (setor comum, acima da capacidade, unrated,
  pendente, sem capacidade cadastrada, unmapped, `0 pacientes`, 3A por
  partição sem total combinado); ausência de badge de códigos no cabeçalho
  v5; ausência de badges por paciente; exceções mantidas; corpo preservado.
- S3: orçamento de queries (4 vs 12 grupos, diferença ≤ 8); total medido
  registrado no relatório (antes/depois); zero mudança de comportamento.
- S4: teste documental do runbook RC12 (escopo somente UI, sem migration, sem
  ativação, rollback); gates completos; evidências de release/deploy por
  agregados.

## Estrutura de slices

| Slice | Entrega vertical | Arquivos (máx.) |
| --- | --- | --- |
| IBPU-S1 | Resumo real + ponte ao fim recolhida | 3 |
| IBPU-S2 | Métricas nos cabeçalhos + limpeza de badges | 3 |
| IBPU-S3 | Prefetch + orçamento de queries | 3 |
| IBPU-S4 | RC12 + deploy de produção | 3 |

Cada slice é implementado por LLM com contexto zero, com protocolo
DeepSeek4-Flash, TDD RED→GREEN→REFACTOR, gates oficiais em container,
inspeções `rg`, condições automáticas de INCOMPLETO e relatório verificável
em `/tmp`.
