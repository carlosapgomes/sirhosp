# SLICE-S3 — Visualização Chart.js (barras divergentes + linha ADC)

## Handoff de entrada (contexto zero)

Você está retomando um projeto Django 5.x. O slice S1 criou o serviço
`compute_hospital_flow`; o S2 criou view/URL/template-tabela/sidebar. Agora
você troca a tabela por um **gráfico Chart.js**. Leia obrigatoriamente:

1. `AGENTS.md`.
2. `PROJECT_CONTEXT.md`.
3. `openspec/changes/hospital-flow-pressure-dashboard/design.md` (seção
   D6 — visualização).
4. `openspec/changes/hospital-flow-pressure-dashboard/specs/hospital-flow-visualization/spec.md`.
5. `apps/census/views.py` (`hospital_flow_view`).
6. `apps/services_portal/templates/services_portal/daily_event_chart.html`
   (referência de padrão Chart.js do projeto — CDN 4.4.0, `json_script`,
   `safeJSON`, verificação `typeof Chart === 'undefined'`).
7. `templates/census/hospital_flow.html` (do S2).
8. Este arquivo `slice-prompts/SLICE-S3.md`.

## Pré-condição de branch

```bash
git checkout feature/hospital-flow-pressure-dashboard
```

S1 e S2 já concluídos nesta branch.

## Decisões congeladas para este slice

- Chart.js **4.4.0 via CDN** (mesmo padrão do projeto):
  `https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js`.
- Tipo: **bar** com dois datasets divergentes + um dataset **line** em eixo
  Y secundário (ADC).
- ADC null (dia sem snapshot) renderizado como **gap** na linha
  (`spanGaps: false`, ponto null).
- Cores: admissões em azul, altas+óbitos em vermelho/laranja, ADC em
  preto/escuro.
- Dados serializados via `json_script` + `safeJSON` (padrão do projeto).

## Objetivo do slice

Substituir/aumentar a tabela do S2 por um gráfico de pressão hospitalar
que mostra, num só quadro: inflow (barras ↑), outflow (barras ↓) e estoque
(linha ADC em eixo secundário).

## Escopo permitido (somente)

- `apps/census/views.py` (edição — preparar contexto JSON serializável:
  `chart_data` com labels, admissions, discharges_deaths, adc; datas como
  ISO strings).
- `templates/census/hospital_flow.html` (edição — adicionar canvas +
  bloco `{% block extra_js %}` com Chart.js; manter seletor de janela).
- `tests/unit/test_hospital_flow_view.py` (edição — ajustar/criar teste
  que valida `chart_data` serializável: labels, arrays de mesmo
  comprimento, adc com `None` onde não há snapshot).

## Escopo proibido

- `apps/census/flow_service.py` (não alterar).
- Sidebar (já feito no S2).
- Drill-down por setor (é S4).
- Painel de resíduo QC (é S5).
- Qualquer outra view/template.

## Limite de alteração

Máximo: **3 arquivos**.

## Requisitos funcionais do slice

1. Contexto da view adiciona `chart_data`. Estrutura:

   ```python
   chart_data = {
       "labels": [d.isoformat() for d in datas],
       "admissions": [row["admissions"] for row in flow_series],
       "discharges_deaths": [row["discharges"] + row["deaths"]
                             for row in flow_series],
       "adc": [row["adc"] for row in flow_series],  # pode ter None
   }
   ```

   (Serializável; datas em ISO; `adc` mantém `None`.)
2. Template: canvas `<canvas id="flowChart"></canvas>` + bloco
   `{% block extra_js %}` seguindo o padrão de `daily_event_chart.html`:
   - `<script src="...chart.js@4.4.0..."></script>`.
   - `{{ chart_data|json_script:"flow-chart-data" }}`.
   - `safeJSON('flow-chart-data', {...})`.
   - Verificação `if (typeof Chart === 'undefined') { console.error(...) }`.
3. Configuração do Chart.js:
   - `type: 'bar'`.
   - Dataset 1: `admissions` (eixo y principal, positivo).
   - Dataset 2: `discharges_deaths` multiplicado por -1 (negativo,
     divergente).
   - Dataset 3: `adc` como `type: 'line'`, `yAxisID: 'y1'` (secundário),
     `spanGaps: false`, `data` com `null` onde ADC é `None`.
   - `scales.y` (barras) e `scales.y1` (linha ADC, posição `right`).
   - Tooltips legíveis.
4. A tabela do S2 pode permanecer abaixo do gráfico (detalhe) ou ser
   removida — decida pelo mais limpo (DRY); se mantiver, legenda "Dados".

## TDD obrigatório

1. **RED**: ajustar testes da view para afirmar que `chart_data` está no
   contexto e é serializável via `json.dumps` (sem exceção), e que os
   arrays `labels`, `admissions`, `discharges_deaths`, `adc` têm o mesmo
   comprimento. Criar um caso com dia sem snapshot e validar
   `adc[i] is None`. Rodar: deve falhar.
2. **GREEN**: implementar contexto + template até passar.
3. **REFACTOR**: sem ampliar escopo.

## Gates obrigatórios S3

1. `./scripts/test-in-container.sh check`
2. `./scripts/test-in-container.sh unit`
3. `./scripts/test-in-container.sh lint`

## Critérios de auto-avaliação

- [ ] Chart.js carrega do mesmo CDN usado no projeto (4.4.0)?
- [ ] ADC null gera **gap** na linha (não zero, não projeção)?
- [ ] Barras são divergentes (admissões ↑, altas+óbitos ↓)?
- [ ] ADC em eixo Y secundário (direita)?
- [ ] `json_script` + `safeJSON` seguem o padrão de
      `daily_event_chart.html`?
- [ ] Há verificação `typeof Chart === 'undefined'` com log de erro?
- [ ] `chart_data` é serializável (`json.dumps` não lança)?
- [ ] Arrays de dados têm todos o mesmo comprimento?
- [ ] Nenhum arquivo fora do escopo foi tocado?
- [ ] Lint e type check sem erros novos?

## Saída obrigatória

Gerar `/tmp/sirhosp-slice-HFPD-S3-report.md` com:

- resumo do slice;
- checklist de aceite;
- arquivos alterados (before/after);
- comandos e resultados;
- riscos/pendências;
- próximo passo (S4).

Pare ao concluir. Não iniciar S4.
