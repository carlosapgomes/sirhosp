# SLICE-PF-1: Backend — view de fragmento + template parcial + testes

> **Handoff para executor com ZERO contexto adicional.**
> Leia até o fim antes de começar.

---

## 1. Contexto do Projeto

**SIRHOSP** — Sistema Interno de Relatórios Hospitalares. Extrai dados clínicos
do sistema fonte hospitalar via web scraping (Playwright), persiste em
PostgreSQL paralelo, oferece portal Django.

**Stack**: Python 3.12, Django 5.x, PostgreSQL, `uv`, pytest, Bootstrap 5,
HTMX (lib Python `django-htmx` já em INSTALLED_APPS + middleware).

---

## 2. Estado atual do projeto (arquivos relevantes para este slice)

### 2.1 Modelo IngestionRunStageMetric (JÁ EXISTE e é populado pelo worker)

Em `apps/ingestion/models.py`:

```python
class IngestionRunStageMetric(models.Model):
    STAGE_STATUS_CHOICES = [
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
        ("skipped", "Skipped"),
    ]

    run = models.ForeignKey(
        IngestionRun,
        on_delete=models.CASCADE,
        related_name="stage_metrics",
    )
    stage_name = models.CharField(max_length=50)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=STAGE_STATUS_CHOICES, default="succeeded")
    details_json = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["started_at"]
        indexes = [
            models.Index(fields=["run", "stage_name"]),
            models.Index(fields=["stage_name", "status"]),
        ]
```

O worker (`process_ingestion_runs.py`) persiste estágios para runs de todos os
intents:

| Intent | Estágios registrados |
| ------ | ------------------- |
| `full_admission_sync` / genérico | `admissions_capture`, `gap_planning`, `evolution_extraction`, `ingestion_persistence` |
| `admissions_only` | `admissions_capture` |
| `demographics_only` | `demographics_extraction`, `demographics_persistence` |

### 2.2 View run_status atual

Em `apps/ingestion/views.py` (função `run_status`):

```python
@login_required
def run_status(request: HttpRequest, run_id: int) -> HttpResponse:
    try:
        run = IngestionRun.objects.get(pk=run_id)
    except IngestionRun.DoesNotExist as err:
        raise Http404 from err

    params = run.parameters_json or {}
    intent = params.get("intent", "") or run.intent
    # ... monta context com run, status_label, status_class,
    #     patient_record, start_date, end_date, etc.
    # NÃO inclui stage_metrics no contexto atualmente

    return render(request, "ingestion/run_status.html", context)
```

### 2.3 URLs atuais

Em `apps/ingestion/urls.py`:

```python
app_name = "ingestion"

urlpatterns = [
    path("ingestao/criar/", views.create_run, name="create_run"),
    path("ingestao/sincronizar-internacoes/", views.create_admissions_only, name="create_admissions_only"),
    path("ingestao/status/<int:run_id>/", views.run_status, name="run_status"),
]
```

### 2.4 Template run_status.html atual (partes relevantes)

```html
{% extends "base_sidebar.html" %}

{% block extra_head %}
{% if run.status == 'queued' or run.status == 'running' %}
  <meta http-equiv="refresh" content="5">
{% endif %}
{% endblock %}

{% block content %}
<!-- breadcrumb, título, card de estado, alertas de status -->
<!-- ... -->
{% endblock %}
```

**Não há seção de progresso por estágio. Não há uso de HTMX.**

### 2.5 Estrutura de diretórios de templates

```text
apps/ingestion/templates/ingestion/
├── create_run.html
├── create_admissions_only.html
└── run_status.html
```

---

## 3. Objetivo do Slice

Criar a infraestrutura backend para feedback de progresso:

1. **Template parcial** `_run_progress.html` que renderiza lista de estágios
2. **Nova view** `run_status_fragment` que retorna o HTML parcial
3. **Nova URL** para o fragmento
4. **View `run_status` atualizada** para incluir `stage_metrics` no contexto
5. **Testes unitários** para a view de fragmento e para o contexto da view principal

---

## 4. O que EXATAMENTE criar/modificar

### 4.1 NOVO: Template parcial `_run_progress.html`

Criar em `apps/ingestion/templates/ingestion/_run_progress.html`.

Este template recebe as variáveis de contexto:

- `run`: instância de `IngestionRun`
- `stage_metrics`: QuerySet de `IngestionRunStageMetric` (já ordenado por `started_at`)

Lógica de renderização:

```text
Para cada estágio em stage_metrics:
  - Se status == "succeeded" → badge verde "✅ Concluído" + duração (finished_at - started_at)
  - Se status == "failed" → badge vermelho "❌ Falhou" + duração + details_json.error_message se existir
  - Se status == "skipped" → badge cinza "⏭️ Pulado"
  - Se é o último da lista e run.status == "running" → spinner "🔄 Em andamento..."

Para runs com stage_metrics vazio mas status == "running":
  - Mostrar "🔄 Inicializando..."

Para runs com stage_metrics vazio e status terminal:
  - Não mostrar nada (seção oculta)
```

Duração formatada como "Xm Ys" ou "Xs" (usar template filter `|floatformat` ou
calcular no template com `|timeuntil` adaptado).

Estrutura HTML: usar Bootstrap 5 cards/badges alinhados com o estilo existente
(ver `run_status.html` para referência de classes CSS usadas):

- Cores: `var(--bs-primary)`, `var(--sirhosp-sidebar-bg)`, badges do Bootstrap
- Classes: `card`, `card-body`, `badge`, `d-flex`, `small`, `text-muted`

**Template de referência (pseudocódigo):**

```html
<div id="run-progress" class="card border-0 shadow-sm mb-3">
  <div class="card-body">
    <h5 class="card-title h6 fw-semibold mb-3" style="color: var(--sirhosp-sidebar-bg);">
      Progresso
    </h5>
    {% if stage_metrics %}
      {% for stage in stage_metrics %}
        <div class="d-flex align-items-center gap-2 mb-2">
          {# Ícone e nome do estágio #}
          <div class="flex-grow-1">
            <span class="small fw-medium">{{ stage.stage_name }}</span>
          </div>
          {# Badge de status #}
          {% if stage.status == 'succeeded' %}
            <span class="badge bg-success small">Concluído</span>
            <small class="text-muted">{{ duração }}</small>
          {% elif stage.status == 'failed' %}
            <span class="badge bg-danger small">Falhou</span>
          {% elif stage.status == 'skipped' %}
            <span class="badge bg-secondary small">Pulado</span>
          {% endif %}
        </div>
      {% endfor %}
      {# Indicador de estágio em andamento #}
      {% if run.status == 'running' %}
        <div class="d-flex align-items-center gap-2 mt-2">
          <div class="spinner-border spinner-border-sm" role="status"></div>
          <small class="text-muted">Processando próximo estágio...</small>
        </div>
      {% endif %}
    {% elif run.status == 'running' %}
      <div class="d-flex align-items-center gap-2">
        <div class="spinner-border spinner-border-sm" role="status"></div>
        <small class="text-muted">Inicializando extração...</small>
      </div>
    {% endif %}
  </div>
</div>
```

**Labels amigáveis para stage_name (mapear no template):**

| stage_name | Label |
| ---------- | ----- |
| `admissions_capture` | Captura de internações |
| `gap_planning` | Planejamento de gaps |
| `evolution_extraction` | Extração de evoluções |
| `ingestion_persistence` | Persistência dos dados |
| `demographics_extraction` | Extração de dados demográficos |
| `demographics_persistence` | Persistência de dados demográficos |

### 4.2 MODIFICAR: `apps/ingestion/views.py`

#### A) Adicionar view `run_status_fragment`

Após a view `run_status` existente, adicionar:

```python
@login_required
def run_status_fragment(request: HttpRequest, run_id: int) -> HttpResponse:
    """Return HTML fragment with stage progress for HTMX polling.

    Returns only the progress section (_run_progress.html partial)
    so HTMX can swap it without reloading the full page.
    """
    try:
        run = IngestionRun.objects.get(pk=run_id)
    except IngestionRun.DoesNotExist as err:
        raise Http404 from err

    stage_metrics = run.stage_metrics.all()

    return render(request, "ingestion/_run_progress.html", {
        "run": run,
        "stage_metrics": stage_metrics,
    })
```

#### B) Atualizar view `run_status` — adicionar `stage_metrics` ao contexto

Na view `run_status`, **antes** da linha `context = {`, adicionar:

```python
    stage_metrics = run.stage_metrics.all()
```

E dentro do dicionário `context`, adicionar:

```python
        "stage_metrics": stage_metrics,
```

**IMPORTANTE**: Não remover nada do contexto existente. Apenas adicionar.

### 4.3 MODIFICAR: `apps/ingestion/urls.py`

Adicionar nova rota **antes** da rota `run_status` existente (rotas mais
específicas devem vir antes):

```python
    path(
        "ingestao/status/<int:run_id>/progresso/",
        views.run_status_fragment,
        name="run_status_fragment",
    ),
```

O `urlpatterns` final deve ficar:

```python
urlpatterns = [
    path("ingestao/criar/", views.create_run, name="create_run"),
    path(
        "ingestao/sincronizar-internacoes/",
        views.create_admissions_only,
        name="create_admissions_only",
    ),
    path(
        "ingestao/status/<int:run_id>/progresso/",
        views.run_status_fragment,
        name="run_status_fragment",
    ),
    path("ingestao/status/<int:run_id>/", views.run_status, name="run_status"),
]
```

---

## 5. Testes: `tests/unit/test_run_status_progress.py`

Criar arquivo NOVO com os testes abaixo.

```python
from __future__ import annotations

import pytest
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.ingestion.models import IngestionRun, IngestionRunStageMetric


@pytest.mark.django_db
class TestRunStatusFragmentView:
    """Tests for the run_status_fragment endpoint."""

    def _login(self, client):
        from django.contrib.auth.models import User
        user = User.objects.create_user(
            username="testuser_pf1", password="testpass123"
        )
        client.force_login(user)

    def _create_run_with_stages(self):
        """Helper: create a running run with stage metrics."""
        run = IngestionRun.objects.create(
            status="running",
            intent="full_admission_sync",
            parameters_json={
                "patient_record": "12345",
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
                "intent": "full_admission_sync",
            },
        )
        now = timezone.now()
        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name="admissions_capture",
            started_at=now,
            finished_at=now,
            status="succeeded",
        )
        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name="gap_planning",
            started_at=now,
            finished_at=now,
            status="succeeded",
        )
        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name="evolution_extraction",
            started_at=now,
            finished_at=None,
            status="succeeded",
        )
        return run

    def test_fragment_returns_stages_for_running_run(self):
        """Fragment endpoint returns stage names and statuses."""
        run = self._create_run_with_stages()
        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status_fragment", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")

        # Check that stage info is present
        assert "admissions_capture" in content.lower() or \
               "Captura" in content or \
               "internações" in content.lower()
        # Check Bootstrap structure
        assert "run-progress" in content

    def test_fragment_returns_200_for_run_without_stages(self):
        """Fragment should still render (with appropriate message) for
        runs with no stage metrics yet."""
        run = IngestionRun.objects.create(
            status="running",
            parameters_json={"patient_record": "99999"},
        )
        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status_fragment", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")

        # Should have the progress container
        assert "run-progress" in content

    def test_fragment_404_for_nonexistent_run(self):
        """Nonexistent run_id returns 404."""
        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status_fragment", args=[99999])
        response = client.get(url)

        assert response.status_code == 404

    def test_fragment_requires_authentication(self):
        """Anonymous access redirects to login."""
        run = IngestionRun.objects.create(
            status="running",
            parameters_json={"patient_record": "12345"},
        )
        client = Client()

        url = reverse("ingestion:run_status_fragment", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 302
        assert "/login/" in response.url

    def test_fragment_for_failed_run_shows_failed_stage(self):
        """Fragment shows failed stage with error details."""
        run = IngestionRun.objects.create(
            status="failed",
            parameters_json={"patient_record": "12345"},
        )
        now = timezone.now()
        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name="admissions_capture",
            started_at=now,
            finished_at=now,
            status="succeeded",
        )
        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name="gap_planning",
            started_at=now,
            finished_at=now,
            status="succeeded",
        )
        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name="evolution_extraction",
            started_at=now,
            finished_at=now,
            status="failed",
            details_json={"error_type": "TimeoutError",
                          "error_message": "Timeout after 120s"},
        )
        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status_fragment", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")

        # Should show all stages including the failed one
        assert "admissions_capture" in content.lower() or "Captura" in content
        assert "evolution_extraction" in content.lower() or "Extração" in content or "Evolu" in content


@pytest.mark.django_db
class TestRunStatusViewIncludesStages:
    """Tests for the main run_status view including stage metrics."""

    def _login(self, client):
        from django.contrib.auth.models import User
        user = User.objects.create_user(
            username="testuser_pf2", password="testpass123"
        )
        client.force_login(user)

    def test_run_status_context_includes_stage_metrics(self):
        """run_status view includes stage_metrics in template context."""
        run = IngestionRun.objects.create(
            status="running",
            parameters_json={
                "patient_record": "12345",
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
            },
        )
        now = timezone.now()
        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name="admissions_capture",
            started_at=now,
            finished_at=now,
            status="succeeded",
        )
        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        # Check that the progress section is included in the main page
        content = response.content.decode("utf-8")
        assert "run-progress" in content
```

---

## 6. Quality Gate

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
```

---

## 7. Relatório

Gerar `/tmp/sirhosp-slice-PF-1-report.md` com:

- Resumo do slice (1 parágrafo)
- Checklist de aceite (todos os checkboxes do tasks.md para PF-1)
- Lista de arquivos alterados (com paths absolutos)
- **Fragmentos de código ANTES/DEPOIS** por arquivo alterado
- Comandos executados e resultados (stdout resumido)
- Riscos, pendências e próximo passo sugerido (PF-2)

---

## 8. Anti-padrões PROIBIDOS

- ❌ Não modificar o modelo `IngestionRunStageMetric` nem `IngestionRun`
- ❌ Não modificar o worker (`process_ingestion_runs.py`)
- ❌ Não modificar `run_status.html` (será feito no Slice PF-2)
- ❌ Não modificar `base.html` (será feito no Slice PF-2)
- ❌ Não remover campos existentes do contexto de `run_status`
- ❌ Não usar `print()` — usar logging se necessário
- ❌ Não quebrar os testes existentes em `test_ingestion_http.py`
