# SLICE-S2 — View + URL + template tabela + sidebar

## Handoff de entrada (contexto zero)

Você está retomando um projeto Django 5.x. O slice anterior (S1) criou o
serviço de domínio `apps/census/flow_service.py` com a função
`compute_hospital_flow(start, end, sector=None)`. Leia obrigatoriamente:

1. `AGENTS.md`.
2. `PROJECT_CONTEXT.md`.
3. `openspec/changes/hospital-flow-pressure-dashboard/proposal.md`.
4. `openspec/changes/hospital-flow-pressure-dashboard/design.md`.
5. `openspec/changes/hospital-flow-pressure-dashboard/specs/hospital-flow-visualization/spec.md`.
6. `apps/census/flow_service.py` (já implementado no S1).
7. `apps/census/views.py` (referência: `bed_status_view`).
8. `apps/census/urls.py`.
9. `templates/includes/sidebar.html`.
10. Este arquivo `slice-prompts/SLICE-S2.md`.

## Pré-condição de branch

```bash
git checkout feature/hospital-flow-pressure-dashboard
```

O slice S1 já deve estar concluído nesta branch.

## Decisões congeladas para este slice

- Rota: `census:hospital_flow` em `/census/fluxo/`.
- Janela default: 90 dias. Seletor GET `window` com valores 30/90/180.
- View **fina**: apenas valida entrada, chama o serviço, monta contexto.
  Toda lógica de negócio permanece no serviço.
- Template **tabela** ainda (sem gráfico — gráfico é S3).
- Entrada de menu "Fluxo Hospitalar" após "Leitos", com `active_menu`
  igual a `'fluxo'`.
- Autenticação obrigatória (`@login_required`).

## Objetivo do slice

Conectar o serviço S1 à web: view, URL, template (tabela) e entrada no
sidebar. Entrega um pontapé visual navegável, sem Chart.js ainda.

## Escopo permitido (somente)

- `apps/census/views.py` (edição — adicionar `hospital_flow_view`).
- `apps/census/urls.py` (edição — adicionar rota).
- `templates/census/hospital_flow.html` (novo).
- `templates/includes/sidebar.html` (edição — adicionar entrada de menu).
- `tests/unit/test_hospital_flow_view.py` (novo).

## Escopo proibido

- `apps/census/flow_service.py` (já pronto no S1 — não alterar).
- Qualquer Chart.js (é S3).
- Drill-down por setor (é S4).
- Painel de resíduo QC (é S5).
- Modelos/migrations.

## Limite de alteração

Máximo: **5 arquivos**.

## Requisitos funcionais do slice

1. `hospital_flow_view(request)`:
   - `@login_required`.
   - Lê `request.GET.get('window', '90')`; valida em `{30, 90, 180}`;
     fallback 90 se inválido.
   - Calcula `end = today`, `start = end - timedelta(days=window-1)`.
   - Chama `compute_hospital_flow(start, end)`.
   - Contexto: `flow_series` (lista de dicts do serviço), `window` (int),
     `window_options = [30, 90, 180]`, `page_title = 'Fluxo Hospitalar'`,
     `active_menu = 'fluxo'`.
2. Rota `path('fluxo/', views.hospital_flow_view, name='hospital_flow')`
   em `apps/census/urls.py`.
3. Template `hospital_flow.html`:
   - Estende `base_sidebar.html` (verificar nome correto do base).
   - Seletor de janela (links GET `?window=30|90|180`, destacando o
     ativo).
   - Tabela com colunas: Data | ADC | Snapshots | Admissões | Altas |
     Óbitos | Líquido. Linhas de `flow_series`. ADC vazio mostra "—".
   - Tratar série vazia com mensagem amigável.
4. Sidebar: entrada após "Leitos", ícone `bi-graph-up`, texto
   "Fluxo Hospitalar", `{% url 'census:hospital_flow' %}`, com classe
   `active` quando `active_menu == 'fluxo'`.

## TDD obrigatório

1. **RED**: `tests/unit/test_hospital_flow_view.py` cobrindo:
   - Usuário anônimo → redirect para login (status 302).
   - Usuário autenticado → 200, template usado é
     `census/hospital_flow.html`.
   - `window` default 90: contexto tem `window == 90` e
     `window_options == [30, 90, 180]`.
   - `?window=30`: contexto `window == 30`.
   - `?window=invalid`: fallback 90.
   - Contexto tem `flow_series` (lista, pode ser vazia).
   - Sintetizar alguns `CensusSnapshot`/`DailyAdmissionCount` e validar
     que `flow_series` reflete o serviço (não retestar a lógica do
     serviço, só a integração view→serviço).
   Rodar: deve falhar (view/rota não existem).
2. **GREEN**: implementar view, rota, template, sidebar até passar.
3. **REFACTOR**: extrair helpers se útil, sem ampliar escopo.

## Gates obrigatórios S2

Registrar comando + exit code + resultado no relatório:

1. `./scripts/test-in-container.sh check`
2. `./scripts/test-in-container.sh unit`
3. `./scripts/test-in-container.sh lint`

## Critérios de auto-avaliação

- [ ] A view é **fina** (sem lógica de negócio; delega ao serviço)?
- [ ] `@login_required` protege a rota?
- [ ] `window` inválido faz fallback para 90 (não 500)?
- [ ] O `active_menu` do sidebar funciona (entrada ativa na página)?
- [ ] Nenhum arquivo fora do escopo foi tocado (especialmente
      `flow_service.py`)?
- [ ] Tabela renderiza sem erro com série vazia?
- [ ] ADC ausente mostra "—" (não "None" nem erro)?
- [ ] Lint e type check sem erros novos?

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-HFPD-S2-report.md` com:

- resumo do slice;
- checklist de aceite;
- arquivos alterados (com before/after);
- comandos executados e resultados;
- riscos/pendências;
- próximo passo sugerido (S3).

Pare ao concluir. Não iniciar S3.
