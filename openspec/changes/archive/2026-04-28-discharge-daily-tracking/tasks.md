# Tasks: discharge-daily-tracking

## 1. Slice S1 — TIME_ZONE + Modelo `DailyDischargeCount`

**Arquivos**: `config/settings.py` (1 linha), `apps/discharges/models.py` (novo)

**TDD**: Teste de criação do modelo → implementação → migration.

- [ ] 1.1 Alterar `TIME_ZONE` de `"America/Sao_Paulo"` para `"America/Bahia"`
  em `config/settings.py`
- [ ] 1.2 Criar `apps/discharges/models.py` com modelo `DailyDischargeCount`
  (`date` DateField unique, `count` IntegerField default 0, timestamps)
- [ ] 1.3 Registrar modelo no admin se aplicável
- [ ] 1.4 Gerar migration: `uv run python manage.py makemigrations discharges`
- [ ] 1.5 Rodar `./scripts/test-in-container.sh check`, `unit` — confirmar verde

## 2. Slice S2 — Management command `refresh_daily_discharge_counts`

**Arquivo**: `apps/discharges/management/commands/refresh_daily_discharge_counts.py`
(novo)

**TDD**: Testes do comando → implementação.

- [ ] 2.1 Criar `tests/unit/test_daily_discharge_count.py` com testes:
  - Comando popula contagem a partir de `Admission.discharge_date`
  - Re-execução atualiza contagens existentes (upsert via `update_or_create`)
  - Comando com zero admissions não quebra
  - Agrupamento por dia respeita timezone `America/Bahia`
- [ ] 2.2 Criar management command `refresh_daily_discharge_counts`:
  - Agrupa `Admission.discharge_date` com `TruncDate` + `Count`
  - Upsert via `update_or_create` para cada `(date, count)`
  - Output informativo no stdout com total de dias processados
- [ ] 2.3 Rodar `./scripts/test-in-container.sh check`, `unit` — confirmar verde

## 3. Slice S3 — Hook do comando no `extract_discharges`

**Arquivo**: `apps/discharges/management/commands/extract_discharges.py`
(modificar, ~5 linhas)

**TDD**: Teste verificando que o comando é chamado após sucesso.

- [ ] 3.1 Adicionar teste em `tests/unit/test_daily_discharge_count.py`:
  - `refresh_daily_discharge_counts` é chamado quando extração sucede
  - NÃO é chamado quando extração falha
  - Usar `mock.patch` para verificar `call_command`
- [ ] 3.2 Adicionar `call_command("refresh_daily_discharge_counts")` ao final
  do `handle()` de `extract_discharges`, APÓS `run.status = "succeeded"`
  e ANTES do `sys.exit(0)` implícito
- [ ] 3.3 Rodar `./scripts/test-in-container.sh check`, `unit` — confirmar verde

## 4. Slice S4 — Dashboard: query + template + URL

**Arquivos**: `apps/services_portal/views.py` (modificar),
`dashboard.html` (modificar), `apps/services_portal/urls.py` (modificar),
`tests/unit/test_services_portal_dashboard.py` (modificar)

**TDD**: Atualizar testes existentes → alterar implementação.

- [ ] 4.1 Atualizar `test_services_portal_dashboard.py`:
  - `test_dashboard_shows_discharges_24h` → adaptar para "altas hoje" com
    `discharge_date__date=timezone.localdate()`
  - Teste: alta de ontem dentro de 24h NÃO conta mais
  - Teste: alta de hoje conta
  - Teste: card contém link para `/painel/altas/`
  - Renomear referências de `altas_24h` para `altas_hoje`
- [ ] 4.2 Alterar query no `dashboard()`:
  `altas_24h` → `altas_hoje` com `discharge_date__date=timezone.localdate()`
- [ ] 4.3 Atualizar context dict: `altas_24h` → `altas_hoje`
- [ ] 4.4 Atualizar template `dashboard.html`:
  - Label `Altas (24h)` → `Altas no dia`
  - Variável `stats.altas_24h` → `stats.altas_hoje`
  - Envolver card em `<a>` com `{% url 'services_portal:discharge_chart' %}`
  - Preservar classes visuais (`text-decoration-none`)
- [ ] 4.5 Adicionar rota `discharge_chart` em `services_portal/urls.py`
  (placeholder — view implementada no Slice S5)
- [ ] 4.6 Rodar `./scripts/test-in-container.sh check`, `unit` — confirmar verde

## 5. Slice S5 — Página de gráfico: view + template Chart.js

**Arquivos**: `apps/services_portal/views.py` (adicionar função),
`apps/services_portal/templates/services_portal/discharge_chart.html` (novo)

**TDD**: Testes da view → implementação da view + template.

- [ ] 5.1 Adicionar testes da view de gráfico em
  `tests/unit/test_services_portal_dashboard.py`:
  - View renderiza com dados de `DailyDischargeCount`
  - Período padrão 90 dias (`date__lt=today`; hoje não aparece)
  - Parâmetro `?dias=30` funciona
  - Parâmetro inválido (`?dias=abc`) cai para default 90
  - Página requer autenticação (redireciona anônimo para login)
  - Context contém `chart_data` com keys: labels, counts, ma3, ma10, ma30
  - MA-3 é `None` nos primeiros 2 dias, MA-10 `None` nos primeiros 9, etc.
- [ ] 5.2 Implementar `discharge_chart()` view:
  - Extrai `?dias=N` com default 90, fallback para default se inválido
  - Query `DailyDischargeCount.objects.filter(date__lt=today).order_by("date")[:dias]`
  - Helper `_moving_average(values, window)` → lista com `None` nos primeiros
    `window-1` elementos, valores arredondados nos demais
  - Context com `chart_data` JSON-serializado: labels (datas dd/mm), counts,
    ma3, ma10, ma30
- [ ] 5.3 Criar template `discharge_chart.html`:
  - Chart.js 4.4.0 via CDN jsdelivr
  - Bar chart (counts) + 3 line datasets (MA-3 azul, MA-10 laranja, MA-30
    vermelho) com `spanGaps: false` (linhas quebram nos `None`)
  - Seletor de período: links `?dias=30`, `?dias=60`, `?dias=90`,
    `?dias=180`, `?dias=365` com destaque visual no selecionado
  - Fallback HTML: mensagem "Nenhum dado disponível" quando `counts` vazio
  - Legenda identificando cada série
  - Título: "Altas por Dia"
  - Responsivo (Chart.js `responsive: true`)
- [ ] 5.4 Rodar `./scripts/test-in-container.sh check`, `unit` — confirmar verde

## 6. Slice S6 — Quality gate e validação final

- [ ] 6.1 Rodar `./scripts/test-in-container.sh quality-gate` e garantir
  tudo verde
- [ ] 6.2 Rodar `./scripts/markdown-lint.sh` nos `.md` alterados/criados
  (design.md, tasks.md, slice-prompts/*.md)
- [ ] 6.3 Rodar `./scripts/test-in-container.sh typecheck` — zero novos erros
- [ ] 6.4 Rodar `./scripts/markdown-format.sh` se necessário
- [ ] 6.5 Verificar visualmente (após deploy):
  - Dashboard mostra "Altas no dia" com valor
  - Card clicável → `/painel/altas/`
  - Gráfico renderiza barras + 3 linhas MA
  - Seletor de período funciona
  - Hoje não aparece no gráfico
