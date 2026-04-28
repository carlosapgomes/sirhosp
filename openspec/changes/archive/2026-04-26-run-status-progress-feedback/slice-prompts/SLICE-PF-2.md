# SLICE-PF-2: Frontend — HTMX polling + integração no template

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

### 2.1 O que o Slice PF-1 entregou

O Slice PF-1 (já concluído) criou:

1. **Template parcial** `apps/ingestion/templates/ingestion/_run_progress.html`
   que renderiza lista de estágios com badges e durações.
2. **View `run_status_fragment`** em `apps/ingestion/views.py` que retorna
   apenas o HTML do partial.
3. **URL** `ingestao/status/<int:run_id>/progresso/` em `apps/ingestion/urls.py`
   com nome `"run_status_fragment"`.
4. **Contexto `stage_metrics`** adicionado na view `run_status`.

### 2.2 Template run_status.html atual (ANTES das mudanças)

```html
{% extends "base_sidebar.html" %} {% block title %}Status #{{ run.pk }} —
SIRHOSP{% endblock %} {% block extra_head %} {% if run.status == 'queued' or
run.status == 'running' %}
<meta http-equiv="refresh" content="5" />
{% endif %} {% endblock %} {% block content %}
<nav aria-label="breadcrumb" class="mb-3">
  <!-- breadcrumb ... -->
</nav>

<h2 class="h5 fw-bold mb-3" style="color: var(--sirhosp-sidebar-bg);">
  Status ... #{{ run.pk }}
</h2>

<!-- Status card (estado, tipo, registro, período, início, término) -->
<div class="card border-0 shadow-sm mb-3">
  <!-- ... -->
</div>

<!-- Results (só aparece em succeeded/failed) -->
{% if run.status == 'succeeded' or run.status == 'failed' %}
<!-- contadores ... -->
{% endif %}

<!-- Alerts (queued/running/succeeded/failed/no_admissions) -->
<!-- ... -->

<!-- Gap windows -->
<!-- ... -->

<div class="mt-3">
  <!-- botão voltar/nova extração -->
</div>
{% endblock %}
```

### 2.3 Template base.html atual

```html
{% load static %}
<!DOCTYPE html>
<html lang="pt-BR">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{% block title %}SIRHOSP{% endblock %}</title>
    <link
      href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.5/dist/css/bootstrap.min.css"
      rel="stylesheet"
    />
    <!-- ... outros CSS ... -->
    {% block extra_head %}{% endblock %}
  </head>
  <body>
    {% block body %}{% endblock %}
    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.5/dist/js/bootstrap.bundle.min.js"></script>
    {% block extra_js %}{% endblock %}
  </body>
</html>
```

**NÃO há tag `<script>` para HTMX atualmente.**

### 2.4 Biblioteca HTMX

- `django-htmx` Python package JÁ está em `INSTALLED_APPS` e `MIDDLEWARE`
  no `config/settings.py`.
- A lib JavaScript do HTMX **NÃO** está carregada nos templates (não há
  `<script src="...htmx...">` em lugar nenhum).
- Vamos usar HTMX 2.0.4 via CDN unpkg.

---

## 3. Objetivo do Slice

Integrar HTMX no frontend para substituir o meta-refresh por polling parcial
com feedback de progresso:

1. **Carregar lib HTMX** no `base.html`
2. **Modificar `run_status.html`**: substituir `<meta refresh>` por HTMX
   polling que atualiza apenas a seção de progresso
3. **Incluir `_run_progress.html`** na página principal para renderização
   inicial
4. **Atualizar testes de integração** para validar o novo comportamento

---

## 4. O que EXATAMENTE criar/modificar

### 4.1 MODIFICAR: `templates/base.html`

Adicionar a tag `<script>` do HTMX **antes** do `{% block extra_js %}`.

Localização exata: após o `<script>` do Bootstrap e antes de
`{% block extra_js %}`.

```html
<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.5/dist/js/bootstrap.bundle.min.js"></script>
<script
  src="https://unpkg.com/htmx.org@2.0.4"
  integrity="sha384-HGVzbSkoAGq0eaeB7Tjjs0BzRWtvUZy6VU1hQ3UPh5fS4wFvpIkJ5hWLlOahwRr"
  crossorigin="anonymous"
></script>
{% block extra_js %}{% endblock %}
```

**IMPORTANTE**: Usar `integrity` e `crossorigin` para segurança. A hash acima
é fictícia — para produção, usar a hash real do unpkg ou omitir os atributos.

### 4.2 MODIFICAR: `apps/ingestion/templates/ingestion/run_status.html`

Três mudanças necessárias:

#### A) Remover `<meta http-equiv="refresh">`

Remover TODO o bloco `{% block extra_head %}` que contém o meta-refresh:

**ANTES:**

```html
{% block extra_head %} {% if run.status == 'queued' or run.status == 'running'
%}
<meta http-equiv="refresh" content="5" />
{% endif %} {% endblock %}
```

**DEPOIS:**

```html
{% block extra_head %}{% endblock %}
```

#### B) Adicionar seção de progresso com HTMX polling

Inserir o include + HTMX polling **entre o card de estado e a seção de resultados**.

Localização: logo após o `</div>` do card de estado (`<!-- Status card -->`)
e antes de `<!-- Results -->`.

```html
<!-- Progress section with HTMX polling -->
{% if run.status == 'queued' or run.status == 'running' %}
<div
  hx-get="{% url 'ingestion:run_status_fragment' run.pk %}"
  hx-trigger="every 3s"
  hx-swap="innerHTML"
>
  {% include "ingestion/_run_progress.html" %}
</div>
{% else %} {% include "ingestion/_run_progress.html" %} {% endif %}
```

**Explicação da lógica:**

- Se `queued` ou `running`: o div tem `hx-get` + `hx-trigger="every 3s"` →
  HTMX faz polling a cada 3 segundos, substituindo o innerHTML do div
- O `{% include %}` dentro garante que o conteúdo inicial aparece
  imediatamente (antes do primeiro polling)
- Se estado terminal (`succeeded`/`failed`): renderiza o partial **sem**
  atributos HTMX → sem polling
- O HTMX naturalmente para de fazer polling quando o elemento é
  substituído por conteúdo sem `hx-trigger` (a resposta do fragmento NÃO
  inclui `hx-get`/`hx-trigger`, então o ciclo para)

#### C) Garantir que o partial também aparece em estado terminal

A seção `{% else %}` acima garante que o progresso final (todos os estágios
concluídos) aparece após o término, sem polling.

### 4.3 Template `_run_progress.html` (criado no PF-1)

**NÃO modificar neste slice.** Apenas usar via `{% include %}`. O Slice PF-1
já criou este arquivo com a lógica de renderização de estágios.

### 4.4 Exemplo visual do resultado esperado

```text
┌─────────────────────────────────────────────┐
│  Progresso                                  │
│                                             │
│  ✅ Captura de internações      12s         │
│  ✅ Planejamento de gaps        <1s         │
│  🔄 Extração de evoluções                  │
│  ⏳ Persistência dos dados                  │
│                                             │
│  [spinner] Processando próximo estágio...   │
└─────────────────────────────────────────────┘
```

---

## 5. Testes: atualizar `tests/integration/test_ingestion_http.py`

**NÃO criar arquivo novo.** Adicionar uma nova classe de teste ao arquivo
existente `tests/integration/test_ingestion_http.py`.

Adicionar ao final do arquivo (antes da última linha):

```python
@pytest.mark.django_db
class TestRunStatusProgressFeedback:
    """Integration tests for run status progress feedback (PF-2)."""

    def _login(self, client):
        from django.contrib.auth.models import User
        user = User.objects.create_user(
            username="testuser_pf_int", password="testpass123"
        )
        client.force_login(user)

    def test_run_status_includes_progress_section(self):
        """Main run_status page includes the progress partial."""
        run = IngestionRun.objects.create(
            status="running",
            parameters_json={
                "patient_record": "12345",
                "start_date": "2026-04-01",
                "end_date": "2026-04-19",
            },
        )
        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")
        # Progress section should be present
        assert "run-progress" in content

    def test_run_status_uses_htmx_not_meta_refresh(self):
        """Running runs should use HTMX polling, not meta-refresh."""
        run = IngestionRun.objects.create(
            status="running",
            parameters_json={"patient_record": "12345"},
        )
        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)

        assert response.status_code == 200
        content = response.content.decode("utf-8")

        # Should NOT have meta-refresh
        assert 'http-equiv="refresh"' not in content
        # Should have HTMX polling attributes
        assert "hx-get" in content
        assert "hx-trigger" in content or "every 3s" in content

    def test_run_status_hx_get_points_to_fragment_url(self):
        """HTMX hx-get should point to the fragment endpoint."""
        run = IngestionRun.objects.create(
            status="running",
            parameters_json={"patient_record": "12345"},
        )
        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)

        content = response.content.decode("utf-8")
        fragment_url = reverse("ingestion:run_status_fragment", args=[run.pk])
        assert fragment_url in content

    def test_terminal_state_no_htmx_polling(self):
        """Succeeded/failed runs should NOT have HTMX polling active."""
        for status in ["succeeded", "failed"]:
            run = IngestionRun.objects.create(
                status=status,
                parameters_json={"patient_record": "12345"},
            )
            client = Client()
            self._login(client)

            url = reverse("ingestion:run_status", args=[run.pk])
            response = client.get(url)

            content = response.content.decode("utf-8")
            # Should NOT have HTMX polling on the progress section
            # (the progress partial is included but without hx-trigger)
            assert "hx-trigger" not in content or \
                   "every 3s" not in content

    def test_queued_run_has_htmx_polling(self):
        """Queued runs should also use HTMX polling."""
        run = IngestionRun.objects.create(
            status="queued",
            parameters_json={"patient_record": "12345"},
        )
        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)

        content = response.content.decode("utf-8")
        assert "hx-get" in content
        assert 'http-equiv="refresh"' not in content

    def test_htmx_script_loaded_in_page(self):
        """Any page extending base.html should load HTMX script."""
        run = IngestionRun.objects.create(
            status="succeeded",
            parameters_json={"patient_record": "12345"},
        )
        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)

        content = response.content.decode("utf-8")
        # HTMX JS library should be loaded
        assert "htmx.org" in content

    def test_progress_section_present_on_failed_run(self):
        """Failed runs should still show progress section with stage info."""
        run = IngestionRun.objects.create(
            status="failed",
            error_message="Test failure",
            parameters_json={"patient_record": "12345"},
        )
        from django.utils import timezone
        from apps.ingestion.models import IngestionRunStageMetric

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
            status="failed",
            details_json={"error_type": "ValueError",
                          "error_message": "Bad input"},
        )

        client = Client()
        self._login(client)

        url = reverse("ingestion:run_status", args=[run.pk])
        response = client.get(url)

        content = response.content.decode("utf-8")
        assert "run-progress" in content
        # Failed stage should be visible
        assert "Falhou" in content or "failed" in content.lower() or \
               "gap_planning" in content.lower()
```

---

## 6. Quality Gate

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
```

---

## 7. Relatório

Gerar `/tmp/sirhosp-slice-PF-2-report.md` com:

- Resumo do slice (1 parágrafo)
- Checklist de aceite (todos os checkboxes do tasks.md para PF-2)
- Lista de arquivos alterados (com paths absolutos)
- **Fragmentos de código ANTES/DEPOIS** por arquivo alterado
- Comandos executados e resultados (stdout resumido)
- Riscos, pendências e próximo passo sugerido (PF-3)

---

## 8. Anti-padrões PROIBIDOS

- ❌ Não modificar `_run_progress.html` (criado no PF-1)
- ❌ Não modificar `views.py` ou `urls.py` (criado no PF-1)
- ❌ Não adicionar JavaScript inline ou customizado — usar apenas atributos HTMX
- ❌ Não remover `{% block extra_js %}` do `base.html`
- ❌ Não usar `hx-target` em vez de `hx-swap` no próprio elemento
- ❌ Não quebrar os testes existentes em `test_ingestion_http.py`
- ❌ Não usar `print()` nos templates
