# SLICE-S4: Dashboard — query, template e URL

## Handoff / Contexto de Entrada

**Change**: `discharge-daily-tracking` — rastreamento diário de altas.

**Slice S3 concluído**:

- `extract_discharges` agora chama `refresh_daily_discharge_counts` ao final
  de execuções bem-sucedidas
- `DailyDischargeCount` é populado com contagens diárias de altas

**Estado atual do dashboard** (`apps/services_portal/views.py:39-41`):

```python
altas_24h = Admission.objects.filter(
    discharge_date__gte=timezone.now() - timedelta(hours=24),
).count()
```

**Template atual** (`dashboard.html`):

```html
<div class="sirhosp-stat-value">{{ stats.altas_24h }}</div>
<div class="sirhosp-stat-label">Altas (24h)</div>
```

**O que você vai construir neste slice**:

1. Alterar query do dashboard: sliding window de 24h → contagem do dia corrente
2. Atualizar template: label e variável, card clicável
3. Adicionar rota `/painel/altas/` no `urls.py` (placeholder para S5)

**Próximo slice (S5)**: Implementar a view e template do gráfico.

## Arquivos que você vai tocar (limite: 4)

| Arquivo | Ação |
| --- | --- |
| `apps/services_portal/views.py` | **Modificar** — query + context |
| `apps/services_portal/templates/services_portal/dashboard.html` | **Modificar** — label + link |
| `apps/services_portal/urls.py` | **Modificar** — nova rota placeholder |
| `tests/unit/test_services_portal_dashboard.py` | **Modificar** — adaptar testes |

**NÃO toque** em: models.py, management commands, outros apps, outros templates.

## TDD Workflow (RED → GREEN → REFACTOR)

### RED: Atualize os testes primeiro

No arquivo `tests/unit/test_services_portal_dashboard.py`:

**1. Substitua** `test_dashboard_shows_discharges_24h` por:

```python
    def test_dashboard_shows_discharges_today(self, admin_client):
        """Dashboard counts admissions discharged TODAY only, not last 24h."""
        patient = Patient.objects.create(
            patient_source_key="P1", source_system="tasy", name="A",
        )
        now = timezone.now()
        today = timezone.localdate()

        # Discharged today at 10:00
        today_morning = timezone.make_aware(
            datetime(today.year, today.month, today.day, 10, 0, 0))
        Admission.objects.create(
            patient=patient, source_admission_key="ADM1", source_system="tasy",
            admission_date=now - timedelta(days=5),
            discharge_date=today_morning,
        )
        # Discharged yesterday at 23:00 (within last 24h but NOT today)
        yesterday = today - timedelta(days=1)
        yesterday_night = timezone.make_aware(
            datetime(yesterday.year, yesterday.month, yesterday.day, 23, 0, 0))
        Admission.objects.create(
            patient=patient, source_admission_key="ADM2", source_system="tasy",
            admission_date=now - timedelta(days=10),
            discharge_date=yesterday_night,
        )
        # Not discharged yet
        Admission.objects.create(
            patient=patient, source_admission_key="ADM3", source_system="tasy",
            admission_date=now - timedelta(days=2),
        )

        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        assert response.status_code == 200
        assert response.context["stats"]["altas_hoje"] == 1  # only today
```

**2. Adicione** teste de link no card:

```python
    def test_dashboard_discharge_card_links_to_chart(self, admin_client):
        """The discharge stat card is clickable and links to /painel/altas/."""
        url = reverse("services_portal:dashboard")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        chart_url = reverse("services_portal:discharge_chart")
        assert chart_url in content
        # Card is wrapped in <a> tag
        assert '<a href="' in content
```

**3. Atualize** `test_dashboard_empty_db_shows_zeros`:

- `ctx["stats"]["altas_24h"]` → `ctx["stats"]["altas_hoje"]`

Rode e confirme que **falham**:

```bash
uv run pytest tests/unit/test_services_portal_dashboard.py -q
```

### GREEN: Implementação

**1. `apps/services_portal/views.py`** — função `dashboard()`:

Altere:

```python
# ANTES
altas_24h = Admission.objects.filter(
    discharge_date__gte=timezone.now() - timedelta(hours=24),
).count()

# DEPOIS
altas_hoje = Admission.objects.filter(
    discharge_date__date=timezone.localdate(),
).count()
```

No context dict:

```python
# ANTES
"stats": {
    "internados": internados,
    "cadastrados": cadastrados,
    "altas_24h": altas_24h,
},

# DEPOIS
"stats": {
    "internados": internados,
    "cadastrados": cadastrados,
    "altas_hoje": altas_hoje,
},
```

**2. `dashboard.html`** — card de altas:

```html
<!-- ANTES -->
  <!-- Altas (24h) -->
  <div class="col-12 col-md-6 col-lg-4">
    <div class="sirhosp-stat-card d-flex align-items-center gap-3">
      <div class="sirhosp-stat-icon" style="background: #FEF3C7;">
        <i class="bi bi-box-arrow-right" style="color: #D97706; font-size: 1.25rem;"></i>
      </div>
      <div>
        <div class="sirhosp-stat-value">{{ stats.altas_24h }}</div>
        <div class="sirhosp-stat-label">Altas (24h)</div>
      </div>
    </div>
  </div>

<!-- DEPOIS -->
  <!-- Altas no dia -->
  <div class="col-12 col-md-6 col-lg-4">
    <a href="{% url 'services_portal:discharge_chart' %}" class="text-decoration-none">
      <div class="sirhosp-stat-card d-flex align-items-center gap-3">
        <div class="sirhosp-stat-icon" style="background: #FEF3C7;">
          <i class="bi bi-box-arrow-right" style="color: #D97706; font-size: 1.25rem;"></i>
        </div>
        <div>
          <div class="sirhosp-stat-value" style="color: inherit;">{{ stats.altas_hoje }}</div>
          <div class="sirhosp-stat-label" style="color: inherit;">Altas no dia</div>
        </div>
      </div>
    </a>
  </div>
```

**3. `apps/services_portal/urls.py`** — adicione a rota:

```python
urlpatterns = [
    path("painel/", views.dashboard, name="dashboard"),
    path("censo/", views.censo, name="censo"),
    path("monitor/", views.monitor_risco, name="monitor_risco"),
    path("metrica-ingestao/", views.ingestion_metrics, name="ingestion_metrics"),
    path("painel/altas/", views.discharge_chart, name="discharge_chart"),  # NOVO
]
```

Confirme **verde**:

```bash
uv run pytest tests/unit/test_services_portal_dashboard.py -q
```

### REFACTOR

- Verifique que as classes CSS do card com `<a>` preservam a aparência visual
- O `timezone.localdate()` usa `America/Bahia` (configurado no S1)
- Confirme que a rota `discharge_chart` está com nome consistente
- Remova imports não utilizados que possam ter ficado (ex: `timedelta` pode
  ainda ser usado em outras queries do dashboard — verifique antes de remover)

## Critérios de Sucesso (Auto-Avaliação Obrigatória)

- [ ] Query do dashboard alterada: `discharge_date__date=timezone.localdate()`
- [ ] Context dict usa `altas_hoje` (não `altas_24h`)
- [ ] Template: label "Altas no dia", variável `stats.altas_hoje`
- [ ] Card envolvido em `<a>` com `{% url 'services_portal:discharge_chart' %}`
- [ ] Rota `discharge_chart` adicionada em `urls.py`
- [ ] Testes passando:
  - Conta apenas altas de hoje (ignora ontem dentro de 24h)
  - Card contém link para `/painel/altas/`
  - DB vazio mostra zero
- [ ] `./scripts/test-in-container.sh check` sem erro
- [ ] `./scripts/test-in-container.sh unit` passando

## Anti-Alucinação / Stop Rules

1. **NÃO implemente** a view `discharge_chart` — apenas a rota placeholder.
   A view será feita no Slice S5. O Django vai reclamar que a view não existe?
   Sim — para evitar isso, adicione um placeholder TEMPORÁRIO na view:

   ```python
   def discharge_chart(request):
       from django.http import HttpResponse
       return HttpResponse("Chart page — coming in S5", status=501)
   ```

   Ou deixe a rota comentada e o subagent do S5 a descomenta.
   **Faça o que for mais limpo e testável.**
2. **NÃO altere** outros cards do dashboard (internados, cadastrados,
   ingestion metrics).
3. **NÃO modifique** `Admission` ou `Patient`.
4. **Limite**: 4 arquivos. Se precisar de mais → PARE.
5. Se o link quebrar a aparência visual do card → documente no relatório,
   mas não passe horas ajustando CSS.
6. Se não souber resolver em 25 minutos → PARE, documente, entregue relatório.

## Relatório Obrigatório

Gere `/tmp/sirhosp-slice-S4-report.md`:

```markdown
# Slice S4 Report: Dashboard query + template + URL

## Resumo
...

## Checklist de Aceite
- [ ] Query alterada para altas_hoje
- [ ] Context dict atualizado
- [ ] Template com label "Altas no dia" e link
- [ ] Rota discharge_chart adicionada
- [ ] Testes passando
- [ ] check + unit verdes

## Arquivos Alterados
- apps/services_portal/views.py
- apps/services_portal/templates/services_portal/dashboard.html
- apps/services_portal/urls.py
- tests/unit/test_services_portal_dashboard.py

## Fragmentos Antes/Depois
(Colar antes/depois de CADA arquivo alterado — trechos relevantes)

## Comandos Executados
(Colar outputs)

## Riscos e Pendências
...

## Próximo Slice
S5: Página de gráfico: view + template Chart.js
```

**Após gerar o relatório, PARE.**
