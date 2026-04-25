<!-- markdownlint-disable MD013 MD033 MD040 MD036 -->
# SLICE-S6: Página de leitos + merge_patients + admin action

> **Handoff para executor com ZERO contexto adicional.**
> Leia até o fim antes de começar.

---

## 1. Contexto do Projeto

**SIRHOSP** — Sistema Interno de Relatórios Hospitalares. Django monolítico, PostgreSQL, Bootstrap+HTMX, templates Django.

**Stack**: Python 3.12, Django 5.x, PostgreSQL, `uv`, pytest, Bootstrap 5.

---

## 2. Estado atual (após S1–S5)

```
apps/
├── census/
│   ├── models.py       ← CensusSnapshot, BedStatus
│   ├── services.py     ← process_census_snapshot(), classify_bed_status(), parse_census_csv()
│   ├── admin.py        ← CensusSnapshotAdmin
│   ├── apps.py
│   ├── urls.py         ← NÃO EXISTE AINDA (será criado)
│   └── views.py        ← NÃO EXISTE AINDA (será criado)
├── patients/
│   ├── models.py       ← Patient, Admission, PatientIdentifierHistory
│   ├── services.py     ← search_patients(), ...
│   └── admin.py        ← PatientAdmin (modificar)
└── ingestion/
    └── models.py       ← IngestionRun

config/
└── urls.py             ← urls principais (modificar para incluir census urls)

templates/              ← templates globais
└── base.html           ← base template do portal
```

### Configuração de autenticação

- `LOGIN_URL = "/login/"` (definido em `config/settings.py`)
- Views protegidas usam `@login_required` ou `LoginRequiredMixin`
- Template base usa Bootstrap com sidebar

### Padrões de template

O projeto usa Django templates com Bootstrap. O base template está em `templates/base.html`. Templates de app ficam em `apps/<app>/templates/<app>/`.

---

## 3. Objetivo do Slice

Três funcionalidades independentes:

**A) `merge_patients()`** — função para consolidar dois registros de `Patient` (ex.: paciente com registro antigo e novo após troca de prontuário no hospital). Reaponta `Admission` e `ClinicalEvent`, registra no `PatientIdentifierHistory`, deleta o paciente merged.

**B) Ação admin "Merge selected patients"** — botão no Django Admin para executar merge manual.

**C) Página `/beds/`** — tabela de ocupação de leitos agrupada por setor, usando o `CensusSnapshot` mais recente. Autenticada.

---

## 4. Parte A: `merge_patients()`

### 4.1 Adicionar função em `apps/patients/services.py`

```python
def merge_patients(
    *,
    keep: Patient,
    merge: Patient,
    run: IngestionRun | None = None,
) -> dict[str, int]:
    """Merge 'merge' patient into 'keep' patient.

    Re-points all Admissions and ClinicalEvents from merge to keep,
    records the merge in PatientIdentifierHistory, and deletes merge.

    Args:
        keep: Patient to preserve.
        merge: Patient to merge and delete.
        run: Optional IngestionRun for audit trail.

    Returns:
        Dict with counts: admissions_moved, events_moved
    """
    from apps.patients.models import PatientIdentifierHistory

    if keep.pk == merge.pk:
        raise ValueError("Cannot merge a patient into itself.")

    # Re-point admissions
    admissions_moved = Admission.objects.filter(
        patient=merge
    ).update(patient=keep)

    # Re-point clinical events
    events_moved = ClinicalEvent.objects.filter(
        patient=merge
    ).update(patient=keep)

    # Record the merge
    PatientIdentifierHistory.objects.create(
        patient=keep,
        identifier_type="patient_merge",
        old_value=merge.patient_source_key,
        new_value=keep.patient_source_key,
        ingestion_run=run,
    )

    # Delete the merged patient
    merge.delete()

    return {
        "admissions_moved": admissions_moved,
        "events_moved": events_moved,
    }
```

**Nota**: `ClinicalEvent` é importado de `apps.clinical_docs.models`. O import deve ser **local** (dentro da função) para evitar import circular, pois `clinical_docs` pode importar de `patients`.

### 4.2 Testes: `tests/unit/test_merge_patients.py`

```python
from __future__ import annotations

import pytest
from django.utils import timezone

from apps.clinical_docs.models import ClinicalEvent
from apps.ingestion.models import IngestionRun
from apps.patients.models import (
    Admission, Patient, PatientIdentifierHistory,
)
from apps.patients.services import merge_patients


@pytest.mark.django_db
class TestMergePatients:
    def test_moves_admissions(self):
        keep = Patient.objects.create(
            source_system="tasy", patient_source_key="111", name="KEEP"
        )
        merge = Patient.objects.create(
            source_system="tasy", patient_source_key="222", name="MERGE"
        )
        Admission.objects.create(
            patient=merge, source_admission_key="ADM-1",
        )
        Admission.objects.create(
            patient=merge, source_admission_key="ADM-2",
        )

        result = merge_patients(keep=keep, merge=merge)

        assert result["admissions_moved"] == 2
        assert Admission.objects.filter(patient=keep).count() == 2
        assert not Patient.objects.filter(pk=merge.pk).exists()

    def test_moves_clinical_events(self):
        keep = Patient.objects.create(
            source_system="tasy", patient_source_key="111", name="KEEP"
        )
        merge = Patient.objects.create(
            source_system="tasy", patient_source_key="222", name="MERGE"
        )
        adm = Admission.objects.create(
            patient=merge, source_admission_key="ADM-1",
        )
        ClinicalEvent.objects.create(
            admission=adm, patient=merge,
            event_identity_key="evt-1", content_hash="hash1",
            happened_at=timezone.now(), author_name="DR", profession_type="medica",
            content_text="test",
        )

        result = merge_patients(keep=keep, merge=merge)

        assert result["events_moved"] == 1
        assert ClinicalEvent.objects.filter(patient=keep).count() == 1
        assert not Patient.objects.filter(pk=merge.pk).exists()

    def test_creates_history_record(self):
        keep = Patient.objects.create(
            source_system="tasy", patient_source_key="111", name="KEEP"
        )
        merge = Patient.objects.create(
            source_system="tasy", patient_source_key="222", name="MERGE"
        )

        merge_patients(keep=keep, merge=merge)

        history = PatientIdentifierHistory.objects.filter(
            patient=keep, identifier_type="patient_merge"
        )
        assert history.count() == 1
        assert history.first().old_value == "222"
        assert history.first().new_value == "111"

    def test_merge_into_self_raises(self):
        patient = Patient.objects.create(
            source_system="tasy", patient_source_key="111", name="SELF"
        )
        with pytest.raises(ValueError, match="itself"):
            merge_patients(keep=patient, merge=patient)
```

---

## 5. Parte B: Ação admin

### 5.1 Modificar `apps/patients/admin.py`

Se o arquivo não existir, criá-lo. Se existir, adicionar a ação.

```python
from __future__ import annotations

from django.contrib import admin, messages

from apps.patients.models import Patient
from apps.patients.services import merge_patients


@admin.register(Patient)
class PatientAdmin(admin.ModelAdmin):
    list_display = ["name", "patient_source_key", "date_of_birth", "gender"]
    search_fields = ["name", "patient_source_key"]
    ordering = ["name"]
    actions = ["merge_selected_patients"]

    @admin.action(description="Merge selected patients (keep lowest ID)")
    def merge_selected_patients(self, request, queryset):
        if queryset.count() < 2:
            self.message_user(
                request,
                "Select at least 2 patients to merge.",
                level=messages.WARNING,
            )
            return

        # Sort by ID ascending — keep the lowest
        sorted_patients = list(queryset.order_by("pk"))
        keep = sorted_patients[0]
        to_merge = sorted_patients[1:]

        merged_count = 0
        for merge_patient in to_merge:
            try:
                merge_patients(keep=keep, merge=merge_patient)
                merged_count += 1
            except Exception as exc:
                self.message_user(
                    request,
                    f"Error merging {merge_patient}: {exc}",
                    level=messages.ERROR,
                )

        self.message_user(
            request,
            f"Merged {merged_count} patient(s) into {keep} (ID={keep.pk}).",
            level=messages.SUCCESS,
        )
```

**Verificar** se `apps/patients/admin.py` já existe. Se existir com um `PatientAdmin` já registrado, **apenas adicionar** o método `merge_selected_patients` e o `actions = [...]`. Não sobrescrever configurações existentes.

### 5.2 Verificar registro do admin

Se `apps/patients/admin.py` não existir, o `Patient` pode estar sendo registrado via `admin.site.register(Patient)` em outro lugar. Nesse caso, criar o `PatientAdmin` completo como acima, que vai sobrescrever o registro padrão.

---

## 6. Parte C: Página `/beds/`

### 6.1 `apps/census/views.py`

```python
from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Max, Q
from django.shortcuts import render

from apps.census.models import BedStatus, CensusSnapshot


@login_required
def bed_status_view(request):
    """Display bed occupancy status from the most recent census snapshot."""
    latest_captured = CensusSnapshot.objects.aggregate(
        latest=Max("captured_at")
    )["latest"]

    if latest_captured is None:
        return render(request, "census/bed_status.html", {
            "sectors": [],
            "captured_at": None,
        })

    snapshots = CensusSnapshot.objects.filter(captured_at=latest_captured)

    # Aggregate by sector and status
    sectors_raw = (
        snapshots.values("setor", "bed_status")
        .annotate(count=Count("id"))
        .order_by("setor", "bed_status")
    )

    # Build structured data for template
    sectors: dict[str, dict] = {}
    for row in sectors_raw:
        setor = row["setor"]
        status = row["bed_status"]
        count = row["count"]

        if setor not in sectors:
            sectors[setor] = {
                "name": setor,
                "occupied": 0, "empty": 0, "maintenance": 0,
                "reserved": 0, "isolation": 0, "total": 0,
                "beds": [],
            }

        sectors[setor][status] = count
        sectors[setor]["total"] += count

    # Add individual bed details
    bed_details = snapshots.order_by("leito")
    for bed in bed_details:
        if bed.setor in sectors:
            sectors[bed.setor]["beds"].append({
                "leito": bed.leito,
                "status": bed.bed_status,
                "status_label": BedStatus(bed.bed_status).label,
                "nome": bed.nome if bed.bed_status == BedStatus.OCCUPIED else "",
                "prontuario": bed.prontuario,
            })

    # Sort sectors by name
    sorted_sectors = sorted(sectors.values(), key=lambda s: s["name"])

    return render(request, "census/bed_status.html", {
        "sectors": sorted_sectors,
        "captured_at": latest_captured,
    })
```

### 6.2 `apps/census/urls.py`

```python
from __future__ import annotations

from django.urls import path

from apps.census import views

app_name = "census"

urlpatterns = [
    path("beds/", views.bed_status_view, name="bed_status"),
]
```

### 6.3 Incluir em `config/urls.py`

Adicionar ao `urlpatterns` de `config/urls.py`:

```python
path("", include("apps.census.urls")),
```

Local exato: junto com os outros `path("", include("apps.XXXXX.urls"))`.

### 6.4 Template `apps/census/templates/census/bed_status.html`

Criar diretório `apps/census/templates/census/` e o arquivo:

```django
{% extends "base.html" %}
{% block title %}Leitos — SIRHOSP{% endblock %}

{% block content %}
<div class="container-fluid py-3">
  <h2 class="mb-3">Ocupação de Leitos</h2>

  {% if not captured_at %}
    <div class="alert alert-info">
      Nenhum dado de censo disponível. Execute a extração do censo primeiro.
    </div>
  {% else %}
    <p class="text-muted mb-3">
      Censo capturado em: {{ captured_at|date:"d/m/Y H:i" }}
    </p>

    <div class="table-responsive">
      <table class="table table-striped table-hover">
        <thead>
          <tr>
            <th>Setor</th>
            <th class="text-center">Ocupados</th>
            <th class="text-center">Vagas</th>
            <th class="text-center">Reservas</th>
            <th class="text-center">Manutenção</th>
            <th class="text-center">Isolamento</th>
            <th class="text-center">Total</th>
          </tr>
        </thead>
        <tbody>
          {% for sector in sectors %}
          <tr class="sector-row" data-bs-toggle="collapse"
              data-bs-target="#sector-{{ forloop.counter }}"
              style="cursor: pointer;">
            <td><strong>{{ sector.name }}</strong></td>
            <td class="text-center">
              <span class="badge bg-primary">{{ sector.occupied }}</span>
            </td>
            <td class="text-center">
              <span class="badge bg-success">{{ sector.empty }}</span>
            </td>
            <td class="text-center">
              <span class="badge bg-warning text-dark">{{ sector.reserved }}</span>
            </td>
            <td class="text-center">
              <span class="badge bg-secondary">{{ sector.maintenance }}</span>
            </td>
            <td class="text-center">
              <span class="badge bg-danger">{{ sector.isolation }}</span>
            </td>
            <td class="text-center"><strong>{{ sector.total }}</strong></td>
          </tr>
          <tr class="collapse" id="sector-{{ forloop.counter }}">
            <td colspan="7" class="p-0">
              <table class="table table-sm mb-0">
                <thead>
                  <tr>
                    <th>Leito</th>
                    <th>Status</th>
                    <th>Paciente</th>
                  </tr>
                </thead>
                <tbody>
                  {% for bed in sector.beds %}
                  <tr>
                    <td><code>{{ bed.leito }}</code></td>
                    <td>{{ bed.status_label }}</td>
                    <td>
                      {% if bed.prontuario %}
                        {{ bed.nome }}
                        <small class="text-muted">({{ bed.prontuario }})</small>
                      {% else %}
                        —
                      {% endif %}
                    </td>
                  </tr>
                  {% endfor %}
                </tbody>
              </table>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  {% endif %}
</div>
{% endblock %}
```

**Nota**: Este template assume que o `base.html` tem bloco `content` e Bootstrap 5 carregado. Verifique o base template existente em `templates/base.html` para confirmar os nomes dos blocos (pode ser `{% block main %}` ou `{% block body %}`). Adapte conforme necessário.

---

## 7. Testes adicionais: `tests/unit/test_bed_status_view.py`

```python
from __future__ import annotations

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot


@pytest.mark.django_db
class TestBedStatusView:
    def test_anonymous_redirected(self, client):
        url = reverse("census:bed_status")
        response = client.get(url)
        assert response.status_code == 302
        assert "/login/" in response.url

    def test_authenticated_can_access(self, admin_client):
        url = reverse("census:bed_status")
        response = admin_client.get(url)
        assert response.status_code == 200
        assert "Nenhum dado de censo disponível" in response.content.decode()

    def test_shows_sector_data(self, admin_client):
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="UTI A",
            leito="01",
            prontuario="111",
            nome="PACIENTE UM",
            especialidade="NEF",
            bed_status=BedStatus.OCCUPIED,
        )
        CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="UTI A",
            leito="02",
            prontuario="",
            nome="DESOCUPADO",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )

        url = reverse("census:bed_status")
        response = admin_client.get(url)
        content = response.content.decode()
        assert response.status_code == 200
        assert "UTI A" in content
        # The occupied count should be 1
        assert "PACIENTE UM" in content

    def test_uses_only_latest_snapshot(self, admin_client):
        old_time = timezone.now() - timezone.timedelta(hours=4)
        new_time = timezone.now()

        # Old snapshot has patient AAA
        CensusSnapshot.objects.create(
            captured_at=old_time,
            setor="OLD SETOR",
            leito="01",
            prontuario="AAA",
            nome="OLD PATIENT",
            especialidade="TST",
            bed_status=BedStatus.OCCUPIED,
        )

        # New snapshot has patient BBB in different sector
        CensusSnapshot.objects.create(
            captured_at=new_time,
            setor="NEW SETOR",
            leito="01",
            prontuario="BBB",
            nome="NEW PATIENT",
            especialidade="TST",
            bed_status=BedStatus.OCCUPIED,
        )

        url = reverse("census:bed_status")
        response = admin_client.get(url)
        content = response.content.decode()

        # New sector should be present
        assert "NEW SETOR" in content
        # Old sector should NOT be present
        assert "OLD SETOR" not in content
```

---

## 8. Quality Gate

```bash
# Verificar que URLs resolvem
uv run python manage.py check

# Rodar todos os testes
./scripts/test-in-container.sh unit

# Lint
./scripts/test-in-container.sh lint

# Verificar URL de leitos
uv run python manage.py show_urls 2>/dev/null || \
  uv run python -c "from django.urls import reverse; print(reverse('census:bed_status'))"
```

---

## 9. Relatório

Gerar `/tmp/sirhosp-slice-CIS-S6-report.md`.

---

## 10. Anti-padrões PROIBIDOS

- ❌ Fazer import de `ClinicalEvent` no topo de `patients/services.py` (import circular)
- ❌ Usar `print()` em views (usar templates)
- ❌ Esquecer `@login_required` na view de leitos
- ❌ Hardcodar URLs nos templates (usar `{% url %}`)
- ❌ Modificar `base.html` sem necessidade
- ❌ Criar templates sem herdar de `base.html`
- ❌ Sobrescrever `PatientAdmin` existente sem preservar configurações
