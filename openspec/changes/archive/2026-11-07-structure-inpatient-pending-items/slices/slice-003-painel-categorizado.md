# S3 — Acompanhamento institucional categorizado

## Identity e objetivo

- ID: `STRUCT-PEND-S3`.
- Change: `structure-inpatient-pending-items`.
- Tasks: [grupo 3](../tasks.md#3-s3--acompanhamento-institucional).
- Dependência: S2 aceito; contrato proposto, execução depende de aprovação.
- Objetivo: acompanhar detalhes estruturados nas duas visões do dashboard,
  com histórico e filtro por categoria consistentes.

## Read first

- `AGENTS.md`, `PROJECT_CONTEXT.md` e `openspec/config.yaml` na raiz.
- [Proposal](../proposal.md), [catálogo](../catalog.md),
  [design D5–D6 e D9](../design.md).
- [Delta do portal](../specs/pending-items-portal/spec.md), PP-03/04/06.
- Specs atuais `openspec/specs/pending-items-portal/spec.md`, especialmente
  PP-02/05/07/09, e [contrato S2](slice-002-cadastro-estruturado.md).
- `apps/pending_items/{queries,views_aggregate,views_export}.py` e templates
  `aggregate.html`, `_aggregate_history_table.html` e formulários de agregado.
- `tests/unit/test_pending_items_queries.py`;
  `tests/integration/test_pending_items_portal.py` e
  `tests/integration/test_pending_items_browser.py`.

## Requirements e evidência planejada

| ID  | Comportamento e fonte                                                     | Evidência                                                                                           |
| --- | ------------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------- |
| R1  | Categoria/tipo/detalhes nas duas visões, PP-03                            | HTTP e browser com mesma fixture de todos os perfis                                                 |
| R2  | Ausência, Não e não aplicável distintos, PP-03 e PI-09                    | Casos RNM e revisões anteriores no histórico recolhível                                             |
| R3  | Filtro categoria combinável, PP-04                                        | Queries e HTTP: interseção, paginação, combinação incompatível                                      |
| R4  | Painel reflete escrita já entregue por S2, sem perder filtros/modo, PP-06 | Browser: alterar só detalhe e conferir resumo/histórico; regressão de conflito/perda de grupo/saída |
| R5  | Recorte e métricas anteriores preservados, PP-02/05/07/09                 | Regressão de ambiguidade, primeira unidade, indicadores e cache                                     |

## Expected blast radius

`queries.py`, `views_aggregate.py`, templates de agregado/histórico/resumos
compartilhados e testes dessas superfícies. `views_export.py` somente se
necessário para preservar paridade do recorte ao introduzir filtro categoria;
o novo esquema XLSX é S4.

S2 é dono da validação, gravação e formulários estruturados. Este slice é dono
da apresentação institucional e de seu refresh após escrita, sem duplicar a
implementação do modal. Não mudar migrations, regras de escrita, FSM, saídas,
autorização ou indicadores globais. Se ajuste mínimo for necessário, justificar
no relatório; qualquer redesign exige escalada.

## Failing-before plan

Adicionar e executar antes da implementação:

- teste de query no qual categoria restringe tipos de nomes repetidos;
- HTTP que encontra data e complementos RNM nas duas visões;
- jornada de browser em que mudança só de detalhe aparece no painel filtrado
  e no histórico sem perder o modo/filtros.

Esperar falha por ausência de filtro/apresentação antes de GREEN. Não usar
comparações de HTML interno como única evidência do fluxo real.

## Implementation constraints

Seguir `AGENTS.md`, mantendo a menor mudança correta. Reutilizar a apresentação
e escrita de S2. Aplicar categoria antes de agrupar/paginar e não ignorar
combinações incompatíveis. Não interpretar Agendada como status, nem nomes de
tipos como prioridade. Não acrescentar novos gráficos ou filtros por todos os
campos complementares nesta change.

## Validation

### Focused validation

Executar os caminhos oficiais `unit` e `integration` de
`./scripts/test-in-container.sh`, cobrindo consultas, portal e browser;
executar checks estáticos pertinentes conforme `AGENTS.md`. Verificar também
que a exportação antiga já respeita o novo filtro, antes do novo esquema de S4.

### Project-required gates

Seguir os gates estáticos, Markdown e protocolo de revisão de `AGENTS.md`.

### Runtime / verification

Com dataset sintético no live_server, abrir as duas visões em desktop e a
390px. Filtrar CHD/RNM e Imagem/RNM, abrir histórico, editar agendamento via
modal e finalizar um item. Conferir filtros preservados, remoção da finalizada
do recorte Ativas, desconhecido distinto de Não e ausência de overflow global.
Antes de S4, o XLSX ainda não tem IDs da pendência/internação: comparar a
seleção usando marcadores sintéticos exclusivos nas observações das fixtures,
sem acrescentar colunas antecipadamente. Cobrir categoria válida, categoria
e tipo incompatíveis, resultado com mais de uma página e IDs inválidos.
Métricas permanecem hospitalares mesmo quando os filtros ficam vazios.

Confirmar que saída real exclui o episódio do agregado, indicadores e XLSX,
mas mantém o histórico contextual; não fabricar internação aberta para essa
jornada end-to-end.

## Acceptance criteria

- [ ] R1: ambas as visões mostram os detalhes corretos dos quatro perfis.
- [ ] R2: RNM desconhecida e versão antiga não recebem valores presumidos.
- [ ] R3: categoria combina com os filtros existentes sem ampliar o recorte.
- [ ] R4: edição/confirmação/conflito preservam contexto e dados tentados.
- [ ] R5: indicadores, primeira unidade, autorização e cache não regridem.
- [ ] Gates focados e relatório demonstram o estado final deste slice.

## Escalation conditions

Parar com `BLOCKED_NEEDS_DECISION` se for necessário modificar a classificação
aprovada, inferir informação clínica, alterar definição de métricas/recorte,
redesenhar escrita/FSM, ampliar escopo materialmente ou se infraestrutura
impedir verification confiável. Registrar problema e evidências.

## Evidence report e handoff

Produzir `/tmp/sirhosp-slice-STRUCT-PEND-S3-report.md` conforme `AGENTS.md`, com
R1–R5 -> evidência, arquivos, RED/GREEN, comandos, verification, desvios, levers
e pendências reais.

Quando autorizado, implementar somente este slice a partir das referências,
sem depender da conversa. Não atualizar tasks, criar commit, push, merge,
archive ou iniciar outro slice. Retornar `READY_FOR_REVIEW` com `REPORT_PATH` ou
`BLOCKED_NEEDS_DECISION` com evidências.
