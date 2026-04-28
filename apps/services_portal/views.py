"""Services portal views: dashboard, census, risk monitor, ingestion metrics.

Slice S2: Dashboard with operational stats (demo data).
Slice DRD-S1: Dashboard with real DB queries.
Slice IRMD-S6: Ingestion metric cards on dashboard and metrics page route.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.db.models import Max, Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot
from apps.ingestion.models import IngestionRun
from apps.patients.models import Admission, Patient


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """Main dashboard with operational indicators from real DB queries.

    Displays current inpatient census from latest CensusSnapshot,
    total registered patients, today's discharges, and data collection status.
    """
    latest = CensusSnapshot.objects.aggregate(latest=Max("captured_at"))["latest"]

    if latest is not None:
        snapshots = CensusSnapshot.objects.filter(captured_at=latest)
        internados = snapshots.filter(bed_status=BedStatus.OCCUPIED).count()
        setores = snapshots.values("setor").distinct().count()
        ultima_varredura = latest.strftime("%d/%m/%Y %H:%M")
    else:
        internados = 0
        setores = 0
        ultima_varredura = "Nenhum dado disponível"

    cadastrados = Patient.objects.count()
    altas_hoje = Admission.objects.filter(
        discharge_date__date=timezone.localdate(),
    ).count()

    # ── IRMD-S6: Ingestion metrics for last 24h ──────────────────────
    ingestion_stats = _compute_ingestion_stats()

    context = {
        "page_title": "Dashboard",
        "stats": {
            "internados": internados,
            "cadastrados": cadastrados,
            "altas_hoje": altas_hoje,
        },
        "coleta": {
            "setores": setores,
            "ultima_varredura": ultima_varredura,
        },
        "ingestion_stats": ingestion_stats,
    }
    return render(request, "services_portal/dashboard.html", context)


@login_required
def discharge_chart(request: HttpRequest) -> HttpResponse:
    """Discharge chart page with daily bars and moving averages.

    Query parameter:
        ?dias=N  — number of days to display (default: 90)

    The chart always shows data through YESTERDAY (today is excluded
    because it is still in progress).
    """
    # Parse ?dias parameter
    dias_str = request.GET.get("dias", "90").strip()
    try:
        dias = int(dias_str)
        if dias < 1:
            dias = 90
    except (ValueError, TypeError):
        dias = 90

    from apps.discharges.models import DailyDischargeCount

    today = timezone.localdate()

    entries_recent = list(
        DailyDischargeCount.objects
        .filter(date__lt=today)
        .order_by("-date")[:dias]
    )
    entries_recent.reverse()  # chronological order

    labels = [e.date.strftime("%d/%m/%Y") for e in entries_recent]
    counts = [e.count for e in entries_recent]

    chart_data = {
        "labels": labels,
        "counts": counts,
        "ma3": _moving_average(counts, 3),
        "ma10": _moving_average(counts, 10),
        "ma30": _moving_average(counts, 30),
    }

    context = {
        "page_title": "Altas por Dia",
        "chart_data": chart_data,
        "dias": dias,
        "period_options": [30, 60, 90, 180, 365],
    }
    return render(request, "services_portal/discharge_chart.html", context)


def _moving_average(values: list[int], window: int) -> list[float | None]:
    """Calculate simple moving average over `window` days.

    First (window-1) positions are None (insufficient history).
    """
    result: list[float | None] = []
    for i in range(len(values)):
        if i < window - 1:
            result.append(None)
        else:
            window_slice = values[i - window + 1 : i + 1]
            result.append(round(sum(window_slice) / window, 1))
    return result


def _build_filtered_queryset(
    periodo: str = "24h",
    status: str = "",
    intent: str = "",
    failure_reason: str = "",
):
    """Build a filtered IngestionRun queryset and its aggregated stats.

    Returns a dict with keys:
        runs: the filtered queryset
        stats: dict with total_finished, success_rate, timeout_rate,
               avg_duration_seconds
    """
    now = timezone.now()
    periodo_hours = {"24h": 24, "7d": 7 * 24, "30d": 30 * 24}
    hours = periodo_hours.get(periodo, 24)
    window_start = now - timedelta(hours=hours)

    qs = IngestionRun.objects.filter(finished_at__gte=window_start)

    if status:
        qs = qs.filter(status=status)
    if intent:
        qs = qs.filter(intent=intent)
    if failure_reason:
        qs = qs.filter(failure_reason=failure_reason)

    total = qs.count()

    if total == 0:
        return {
            "runs": IngestionRun.objects.none(),
            "stats": {
                "total_finished": 0,
                "success_rate": 0.0,
                "timeout_rate": 0.0,
                "avg_duration_seconds": 0,
            },
        }

    success_count = qs.filter(status="succeeded").count()
    timeout_count = qs.filter(timed_out=True).count()

    success_rate = round(success_count / total * 100, 1)
    timeout_rate = round(timeout_count / total * 100, 1)

    runs_with_duration = qs.exclude(processing_started_at__isnull=True)
    if runs_with_duration.exists():
        durations: list[float] = []
        for run in runs_with_duration:
            if run.processing_started_at and run.finished_at:
                durations.append(
                    (run.finished_at - run.processing_started_at).total_seconds()
                )
        avg_seconds = round(sum(durations) / len(durations)) if durations else 0
    else:
        avg_seconds = 0

    return {
        "runs": qs.order_by("-finished_at"),
        "stats": {
            "total_finished": total,
            "success_rate": success_rate,
            "timeout_rate": timeout_rate,
            "avg_duration_seconds": avg_seconds,
        },
    }


def _compute_ingestion_stats() -> dict:
    """Compute ingestion operational metrics for the last 24 hours.

    Returns a dict with:
        total_finished, success_rate, timeout_rate, avg_duration_seconds.
    All values are zero when no runs exist in the window.

    Delegates to _build_filtered_queryset for consistency.
    """
    return _build_filtered_queryset(periodo="24h")["stats"]


@login_required
def censo(request: HttpRequest) -> HttpResponse:
    """Hospital census: filter by ward/sector and search patients.

    Displays a table of current inpatients (occupied beds only)
    from the latest CensusSnapshot. Supports filtering by sector
    (dropdown populated from real data) and free-text search
    across patient name and record number.
    """
    latest = CensusSnapshot.objects.aggregate(latest=Max("captured_at"))["latest"]

    if latest is None:
        return render(request, "services_portal/censo.html", {
            "page_title": "Censo Hospitalar",
            "setores": [],
            "setor_filtro": "",
            "busca": "",
            "pacientes": [],
            "total": 0,
            "captured_at": None,
        })

    # Base queryset: only occupied beds from the most recent snapshot
    qs = CensusSnapshot.objects.filter(
        captured_at=latest,
        bed_status=BedStatus.OCCUPIED,
    ).order_by("setor", "leito")

    # Distinct sectors for the dropdown
    setores = list(
        qs.values_list("setor", flat=True)
        .distinct()
        .order_by("setor")
    )

    # Filter by sector
    setor_filtro = request.GET.get("setor", "").strip()
    if setor_filtro and setor_filtro != "Todos":
        qs = qs.filter(setor=setor_filtro)

    # Free-text search
    busca = request.GET.get("q", "").strip()
    if busca:
        qs = qs.filter(
            Q(nome__icontains=busca) | Q(prontuario__icontains=busca)
        )

    snapshots = list(qs)
    pacientes = [
        {
            "leito": s.leito,
            "nome": s.nome,
            "registro": s.prontuario,
            "admissao": "",
            "setor": s.setor,
        }
        for s in snapshots
    ]

    return render(request, "services_portal/censo.html", {
        "page_title": "Censo Hospitalar",
        "setores": setores,
        "setor_filtro": setor_filtro,
        "busca": busca,
        "pacientes": pacientes,
        "total": len(pacientes),
        "captured_at": latest,
    })


@login_required
def ingestion_metrics(request: HttpRequest) -> HttpResponse:
    """Ingestion operational metrics page with filters and run table (S7).

    Supports filtering by period (24h/7d/30d), status, intent and
    failure_reason via querystring. Renders aggregated summary cards
    and a detailed run table, both coherent with the filtered dataset.
    """
    periodo = request.GET.get("periodo", "24h").strip()
    status = request.GET.get("status", "").strip()
    intent = request.GET.get("intent", "").strip()
    failure_reason = request.GET.get("failure_reason", "").strip()

    result = _build_filtered_queryset(
        periodo=periodo,
        status=status,
        intent=intent,
        failure_reason=failure_reason,
    )

    # Collect distinct values for filter dropdowns from the full dataset
    # (not filtered by status/intent so dropdowns always have options)
    all_finished = IngestionRun.objects.filter(finished_at__isnull=False)
    all_statues = sorted(
        all_finished.values_list("status", flat=True).distinct()
    )
    all_intents = sorted(
        t for t in
        all_finished.values_list("intent", flat=True).distinct()
        if t
    )
    all_failure_reasons = sorted(
        r for r in
        all_finished.exclude(failure_reason="")
        .values_list("failure_reason", flat=True).distinct()
    )

    context = {
        "page_title": "Métricas de Ingestão",
        "ingestion_stats": result["stats"],
        "runs": result["runs"],
        "filters": {
            "periodo": periodo,
            "status": status,
            "intent": intent,
            "failure_reason": failure_reason,
        },
        "filter_options": {
            "statuses": all_statues,
            "intents": all_intents,
            "failure_reasons": all_failure_reasons,
        },
    }
    return render(request, "services_portal/ingestion_metrics.html", context)


@login_required
def monitor_risco(request: HttpRequest) -> HttpResponse:
    """Risk monitor: search keywords in clinical events.

    Supports multiple comma-separated terms and a time period
    dropdown (24h, 48h, 7 days). Results are grouped by patient
    in Bootstrap accordion cards with highlighted snippets.

    Uses the existing search service (SearchQueryParams) when
    real data is available, with fallback demo results.
    """
    termos = request.GET.get("q", "").strip()
    periodo = request.GET.get("periodo", "48h").strip()

    resultados: list[dict] = []

    if termos:
        # Try real search first, fall back to demo if no results
        resultados = _search_clinical_events_html(termos, periodo)
        if not resultados:
            resultados = _demo_resultados(termos)

    context = {
        "page_title": "Monitor de Risco",
        "termos": termos,
        "periodo": periodo,
        "resultados": resultados,
        "total_pacientes": len(resultados),
        "total_ocorrencias": sum(r["ocorrencias"] for r in resultados),
    }
    return render(request, "services_portal/monitor_risco.html", context)


def _search_clinical_events_html(termos: str, periodo: str) -> list[dict]:
    """Attempt real clinical event search, return empty if backend unavailable."""
    try:
        from apps.search.services import SearchQueryParams, search_clinical_events

        # Calculate date_from based on period
        days_map = {"24h": 1, "48h": 2, "7d": 7}
        days = days_map.get(periodo, 2)
        from datetime import datetime as dt_mod

        date_from = dt_mod.combine(
            date.today() - timedelta(days=days),
            dt_mod.min.time(),
        )

        params = SearchQueryParams(
            query=termos,
            date_from=date_from,
        )
        qs = search_clinical_events(params)[:50]

        # Group results by patient
        grouped: dict[int, dict] = {}
        for event in qs:
            pid = event.patient_id
            if pid not in grouped:
                grouped[pid] = {
                    "patient_id": pid,
                    "patient_name": event.patient.name,
                    "patient_record": event.patient.patient_source_key,
                    "admission_ward": "",
                    "ocorrencias": 0,
                    "eventos": [],
                }
            grouped[pid]["ocorrencias"] += 1
            grouped[pid]["eventos"].append({
                "texto": event.content_text[:200],
                "data": event.happened_at.strftime("%d/%m %H:%M"),
                "autor": event.author_name or "",
            })

        return list(grouped.values())
    except Exception:
        return []


def _demo_resultados(termos: str) -> list[dict]:
    """Generate demo results for risk monitor visualization."""
    t = termos.split(",")[0].strip().lower() if termos else "queda"
    return [
        {
            "patient_id": 1,
            "patient_name": "Fulano de Tal",
            "patient_record": "00123",
            "admission_ward": "202-A",
            "ocorrencias": 2,
            "eventos": [
                {
                    "texto": (
                        f"Paciente com risco de {t} alto,"
                        " orientado a manter grades elevadas"
                        " e campainha ao alcance."
                    ),
                    "data": "23/01 10:00",
                    "autor": "Enfermeiro Carlos",
                },
                {
                    "texto": (
                        f"Reavaliado risco de {t}."
                        " Mantida escala de Morse em 45 pontos."
                    ),
                    "data": "23/01 16:30",
                    "autor": "Fisioterapeuta Ana",
                },
            ],
        },
        {
            "patient_id": 2,
            "patient_name": "Beltrano de Souza",
            "patient_record": "00456",
            "admission_ward": "UTI-05",
            "ocorrencias": 1,
            "eventos": [
                {
                    "texto": (
                        f"Paciente apresentou episódio de {t}"
                        " durante a madrugada. Realizado"
                        " curativo em região frontal."
                    ),
                    "data": "24/01 03:15",
                    "autor": "Enfermeira Julia",
                },
            ],
        },
    ]
