# SLICE-S4 — Drill-down por setor

## Handoff de entrada (contexto zero)

Você está retomando um projeto Django 5.x. S1 (serviço), S2 (view/url/
template-tabela/sidebar) e S3 (gráfico Chart.js) estão prontos. Agora você
adiciona **drill-down por setor**: um filtro que recalcula o painel para um
setor específico. Leia obrigatoriamente:

1. `AGENTS.md`.
2. `PROJECT_CONTEXT.md`.
3. `openspec/changes/hospital-flow-pressure-dashboard/design.md` (D7).
4. `openspec/changes/hospital-flow-pressure-dashboard/specs/hospital-flow-visualization/spec.md`.
5. `apps/census/flow_service.py` (função `compute_hospital_flow` — já
   aceita `sector`).
6. `apps/census/views.py` (`hospital_flow_view`).
7. `templates/census/hospital_flow.html`.
8. Este arquivo `slice-prompts/SLICE-S4.md`.

## Pré-condição de branch

```bash
git checkout feature/hospital-flow-pressure-dashboard
```

S1, S2 e S3 já concluídos.

## Decisões congeladas para este slice

- O serviço S1 **já aceita** `sector=None|str`. Este slice apenas **usa**
  esse parâmetro na web.
- Filtro via GET `?sector=<nome>` (ou vazio = hospital-total).
- Seletor: **dropdown alfabético** com todos os setores que aparecem em
  algum `CensusSnapshot` do período. Opção "Hospital (todos)" no topo.
- Submissão: GET simples (form method GET) — HTMX é opcional; prefira o
  mais simples (YAGNI). Mantenha o parâmetro `window` ao mudar de setor.
- Quando setor selecionado: legenda no template esclarece que o **estoque
  é filtrado pelo setor, mas o fluxo permanece hospital-total** (as fontes
  dedicadas não têm setor — decisão D7 do design).

## Objetivo do slice

Permitir ao gestor localizar onde a pressão se concentra, filtrando o
estoque por setor, sem exibir 82 séries simultâneas.

## Escopo permitido (somente)

- `apps/census/views.py` (edição — ler `sector` do GET, validar, passar
  ao serviço, montar lista de setores para o dropdown).
- `apps/census/flow_service.py` (edição **mínima**, somente se faltar um
  helper para listar setores disponíveis no período — ex. função
  `list_sectors(start, end)`; não alterar o contrato de
  `compute_hospital_flow`).
- `templates/census/hospital_flow.html` (edição — adicionar formulário de
  setor + legenda de escopo).
- `tests/unit/test_hospital_flow_view.py` (edição — testar filtro).

## Escopo proibido

- Alterar o contrato de `compute_hospital_flow` (assinatura já está certa).
- Painel de resíduo QC (é S5).
- Small-multiples / heatmap (não-goal).
- Agregação por especialidade (não-goal).

## Limite de alteração

Máximo: **4 arquivos**.

## Requisitos funcionais do slice

1. View lê `request.GET.get('sector', '')`; string vazia = hospital-total
   (`sector=None`). Não valida contra lista fixa (setores podem mudar);
   apenas repassa ao serviço.
2. Contexto adiciona:
   - `selected_sector` (str ou '').
   - `sectors` (lista de nomes distintos de
     `CensusSnapshot.setor` no período, ordenada).
3. Template: `<form method="get">` com `<select name="sector">` +
   `<input type="hidden" name="window" value="{{ window }}">` +
   botão submit. Opção default "Hospital (todos)" value="".
4. Legenda condicional: se `selected_sector`, mostrar aviso curto:
   "Estoque filtrado por setor; fluxo (admissões/altas/óbitos) é
   hospital-total."
5. Manter `chart_data` e tabela funcionando com o filtro aplicado.

## TDD obrigatório

1. **RED**: testes cobrindo:
   - Sem `sector`: `selected_sector == ''`, `compute_hospital_flow`
     chamado com `sector=None`.
   - Com `?sector=X`: `selected_sector == 'X'`, serviço chamado com
     `sector='X'`.
   - Contexto tem `sectors` (lista não vazia quando há snapshots).
   - Sintetizar snapshots em 2 setores e validar que `sectors` contém
     ambos.
   Rodar: deve falhar.
2. **GREEN**: implementar até passar.
3. **REFACTOR**: sem ampliar escopo.

## Gates obrigatórios S4

1. `./scripts/test-in-container.sh check`
2. `./scripts/test-in-container.sh unit`
3. `./scripts/test-in-container.sh lint`

## Critérios de auto-avaliação

- [ ] Hospital-total continua funcionando (default)?
- [ ] O dropdown preserva o `window` selecionado ao trocar de setor?
- [ ] A legenda de escopo aparece só quando há setor selecionado?
- [ ] O contrato de `compute_hospital_flow` não foi alterado?
- [ ] `sectors` vem ordenado e sem duplicatas?
- [ ] Nenhum arquivo fora do escopo foi tocado?
- [ ] Lint e type check sem erros novos?

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-HFPD-S4-report.md` com:

- resumo, checklist, arquivos (before/after), comandos/resultado,
  riscos/pendências, próximo passo (S5).

Pare ao concluir. Não iniciar S5.
