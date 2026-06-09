"""Services portal views: dashboard, census, risk monitor, ingestion metrics.

Slice S2: Dashboard with operational stats (demo data).
Slice DRD-S1: Dashboard with real DB queries.
Slice IRMD-S6: Ingestion metric cards on dashboard and metrics page route.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from itertools import groupby
from typing import Any

from django.contrib.auth.decorators import login_required
from django.core.paginator import EmptyPage, Paginator
from django.db.models import (
    Count,
    F,
    Func,
    IntegerField,
    Max,
    OuterRef,
    Q,
    Subquery,
    Value,
)
from django.db.models.functions import Cast, Coalesce, ExtractHour
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from apps.admissions.models import DailyAdmissionCount
from apps.census.models import (
    BedStatus,
    CensusSnapshot,
    OfficialCensusRecord,
    PatientMovement,
    Specialty,
    Ward,
)
from apps.deaths.models import DailyDeathCount
from apps.discharges.models import DailyDischargeCount, DischargeRecord
from apps.ingestion.models import (
    CensusExecutionBatch,
    FinalRunFailure,
    IngestionRun,
    IngestionRunAttempt,
)
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
        ultima_varredura = timezone.localtime(latest).strftime("%d/%m/%Y %H:%M")
    else:
        internados = 0
        setores = 0
        ultima_varredura = "Nenhum dado disponível"

    cadastrados = Patient.objects.count()
    today = timezone.localdate()
    altas_hoje = (
        DailyDischargeCount.objects.filter(date=today)
        .values_list("count", flat=True)
        .first()
        or 0
    )

    # Daily stats (collected retroactively — latest available date)
    adm_entry = DailyAdmissionCount.objects.order_by("-date").first()
    death_entry = DailyDeathCount.objects.order_by("-date").first()
    discharge_entry = DailyDischargeCount.objects.order_by("-date").first()
    ofcensus_entry = OfficialCensusRecord.objects.order_by("-date").first()

    stats = {
        "internados": internados,
        "cadastrados": cadastrados,
        "altas_hoje": altas_hoje,
        "admissoes": adm_entry.count if adm_entry else 0,
        "admissoes_date": adm_entry.date if adm_entry else today,
        "obitos": death_entry.count if death_entry else 0,
        "obitos_date": death_entry.date if death_entry else today,
        "altas": discharge_entry.count if discharge_entry else 0,
        "altas_date": discharge_entry.date if discharge_entry else today,
        "censo_oficial": (
            OfficialCensusRecord.objects.filter(
                date=ofcensus_entry.date
            ).count() if ofcensus_entry else 0
        ),
        "censo_oficial_date": ofcensus_entry.date if ofcensus_entry else today,
    }

    # ── IRMD-S6: Ingestion metrics for last 24h ──────────────────────
    ingestion_stats = _compute_ingestion_stats()

    context = {
        "page_title": "Dashboard",
        "stats": stats,
        "coleta": {
            "setores": setores,
            "ultima_varredura": ultima_varredura,
        },
        "ingestion_stats": ingestion_stats,
    }
    return render(request, "services_portal/dashboard.html", context)


@login_required
def discharge_list(request: HttpRequest) -> HttpResponse:
    date_str = request.GET.get("date", "").strip()
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            selected_date = None
    else:
        selected_date = None

    if selected_date:
        entry = DailyDischargeCount.objects.filter(date=selected_date).first()
    else:
        entry = DailyDischargeCount.objects.order_by("-date").first()
        selected_date = entry.date if entry else timezone.localdate()

    records, columns = _discharge_records_for_template(entry)
    return render(request, "services_portal/discharge_list.html", {
        "page_title": "Altas",
        "date": selected_date,
        "count": entry.count if entry else 0,
        "records": records,
        "columns": columns,
    })


@login_required
def admission_list(request: HttpRequest) -> HttpResponse:
    date_str = request.GET.get("date", "").strip()
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            selected_date = None
    else:
        selected_date = None

    if selected_date:
        entry = DailyAdmissionCount.objects.filter(date=selected_date).first()
    else:
        entry = DailyAdmissionCount.objects.order_by("-date").first()
        selected_date = entry.date if entry else timezone.localdate()

    records, columns = _admission_records_for_template(entry)
    return render(request, "services_portal/admission_list.html", {
        "page_title": "Admissões",
        "date": selected_date,
        "count": entry.count if entry else 0,
        "records": records,
        "columns": columns,
    })


@login_required
def death_list(request: HttpRequest) -> HttpResponse:
    date_str = request.GET.get("date", "").strip()
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            selected_date = None
    else:
        selected_date = None

    if selected_date:
        entry = DailyDeathCount.objects.filter(date=selected_date).first()
    else:
        entry = DailyDeathCount.objects.order_by("-date").first()
        selected_date = entry.date if entry else timezone.localdate()

    records, columns = _death_records_for_template(entry)
    return render(request, "services_portal/death_list.html", {
        "page_title": "Óbitos",
        "date": selected_date,
        "count": entry.count if entry else 0,
        "records": records,
        "columns": columns,
    })


@login_required
def admission_chart(request: HttpRequest) -> HttpResponse:
    """Admission chart page with daily bars and weekday averages.

    Query parameter:
        ?dias=N  — number of days to display (default: 90)

    Data is sourced from DailyAdmissionCount and excludes today
    (in-progress day).
    """
    dias = _parse_dias_param(request)
    context = _daily_count_chart_context(
        model=DailyAdmissionCount,
        dias=dias,
        dataset_label="Admissões",
        page_title="Admissões por Dia",
        daily_chart_title="Admissões por Dia",
        weekday_chart_title="Média de Admissões por Dia da Semana",
        list_url_name="services_portal:admission_list",
        list_link_label="Ver lista de admissões",
    )
    return render(request, "services_portal/daily_event_chart.html", context)


@login_required
def death_chart(request: HttpRequest) -> HttpResponse:
    """Death chart page with daily bars and weekday averages.

    Query parameter:
        ?dias=N  — number of days to display (default: 90)

    Data is sourced from DailyDeathCount and excludes today
    (in-progress day).
    """
    dias = _parse_dias_param(request)
    context = _daily_count_chart_context(
        model=DailyDeathCount,
        dias=dias,
        dataset_label="Óbitos",
        page_title="Óbitos por Dia",
        daily_chart_title="Óbitos por Dia",
        weekday_chart_title="Média de Óbitos por Dia da Semana",
        list_url_name="services_portal:death_list",
        list_link_label="Ver lista de óbitos",
    )
    return render(request, "services_portal/daily_event_chart.html", context)


@login_required
def official_census_list(request: HttpRequest) -> HttpResponse:
    date_str = request.GET.get("date", "").strip()
    if date_str:
        try:
            selected_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            selected_date = None
    else:
        selected_date = None

    if selected_date:
        records = OfficialCensusRecord.objects.filter(date=selected_date)
    else:
        latest = OfficialCensusRecord.objects.order_by("-date").first()
        if latest:
            selected_date = latest.date
            records = OfficialCensusRecord.objects.filter(date=selected_date)
        else:
            selected_date = timezone.localdate()
            records = OfficialCensusRecord.objects.none()

    # ── Filter by unidade (setor) ────────────────────────────────────
    unidade_filter = request.GET.get("unidade", "").strip()
    if unidade_filter:
        records = records.filter(unidade=unidade_filter)

    # ── Filter by especialidade ──────────────────────────────────────
    especialidade_filter = request.GET.get("especialidade", "").strip()
    if especialidade_filter:
        records = records.filter(especialidade=especialidade_filter)

    # ── Annotate numeric tempo_internacao for proper integer ordering ─
    # The raw field is a string like "5 dias". We extract digits via
    # regexp_replace, NULLIF empty -> NULL, CAST to integer, COALESCE to 0.
    tempo_numeric = Coalesce(
        Cast(
            Func(
                Func(
                    F("tempo_internacao"),
                    Value(r"\D"),
                    Value(""),
                    Value("g"),
                    function="regexp_replace",
                ),
                Value(""),
                function="NULLIF",
            ),
            output_field=IntegerField(),
        ),
        Value(0),
        output_field=IntegerField(),
    )
    records = records.annotate(tempo_internacao_numeric=tempo_numeric)

    # ── Ordering ─────────────────────────────────────────────────────
    ordering = request.GET.get("ordenar", "").strip()
    if ordering == "tempo_asc":
        records = records.order_by("tempo_internacao_numeric")
    elif ordering == "tempo_desc":
        records = records.order_by("-tempo_internacao_numeric")
    elif ordering == "unidade":
        records = records.order_by("unidade", "quarto_leito")
    elif ordering == "especialidade":
        records = records.order_by("especialidade", "unidade")
    else:
        records = records.order_by("id")

    # ── Distinct values for filter dropdowns ─────────────────────────
    # Build ward name map from the bed catalog
    ward_map: dict[str, str] = {
        w.source_code: w.name
        for w in Ward.objects.all()
    }

    unidade_codes = list(
        OfficialCensusRecord.objects.filter(date=selected_date)
        .values_list("unidade", flat=True)
        .distinct()
        .order_by("unidade")
    )
    unidade_options = [
        {
            "value": code,
            "label": ward_map.get(code, code),
        }
        for code in unidade_codes
    ]
    especialidade_options = list(
        OfficialCensusRecord.objects.filter(date=selected_date)
        .values_list("especialidade", flat=True)
        .distinct()
        .order_by("especialidade")
    )

    # ── Resolve specialty codes ←→ full names ───────────────────────
    specialty_code_to_name: dict[str, str] = {
        s.code: s.name
        for s in Specialty.objects.all()
    }
    specialty_name_to_code: dict[str, str] = {
        s.name: s.code
        for s in Specialty.objects.all()
    }

    def _resolve_especialidade(raw: str) -> tuple[str, str]:
        """Return (sigla, nome_completo) given either a code or full name."""
        if raw in specialty_code_to_name:
            return raw, specialty_code_to_name[raw]
        if raw in specialty_name_to_code:
            return specialty_name_to_code[raw], raw
        return raw, raw

    # Annotate each record with ward name and specialty sigla/name for display
    records_list: list[Any] = list(records)
    for r in records_list:
        r.unidade_nome = ward_map.get(r.unidade, r.unidade)
        sigla, nome = _resolve_especialidade(r.especialidade)
        r.especialidade_sigla = sigla
        r.especialidade_nome = nome

    # ── Look up internal Patient IDs for direct linking ──────────────
    prontuarios = [r.prontuario for r in records_list if r.prontuario]
    patient_map: dict[str, int] = {}
    if prontuarios:
        patient_map = {
            p.patient_source_key: p.pk
            for p in Patient.objects.filter(patient_source_key__in=prontuarios)
        }
    for r in records_list:
        r.patient_id = patient_map.get(r.prontuario)

    columns = [
        "prontuario", "nome", "unidade", "quarto_leito",
        "data_internacao", "tempo_internacao", "especialidade",
    ]

    return render(request, "services_portal/official_census_list.html", {
        "page_title": "Censo Oficial",
        "date": selected_date,
        "count": len(records_list),
        "records": records_list,
        "columns": columns,
        "unidade_options": unidade_options,
        "unidade_filter": unidade_filter,
        "especialidade_options": especialidade_options,
        "especialidade_filter": especialidade_filter,
        "ordering": ordering,
    })


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

    # DWI-S1: weekend flags and weekday abbreviations for per-bar coloring
    _WEEKDAY_ABBR = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
    weekend_flags = []
    weekday_short = []
    for e in entries_recent:
        wd = e.date.weekday()  # 0=Mon … 6=Sun
        weekend_flags.append(wd >= 5)
        weekday_short.append(_WEEKDAY_ABBR[wd])

    chart_data = {
        "labels": labels,
        "counts": counts,
        "sma7": _moving_average(counts, 7),
        "ema7": _exponential_moving_average(counts, 7),
        "sma30": _moving_average(counts, 30),
        "weekend_flags": weekend_flags,
        "weekday_short": weekday_short,
    }

    weekday_avg = _weekday_average(entries_recent)

    # ── Distribuicao horaria por especialidade ─────────────────────
    # Parse separate date range for hourly data
    raw_hour_start = request.GET.get("h_start", "")
    raw_hour_end = request.GET.get("h_end", "")

    try:
        h_start = datetime.strptime(raw_hour_start, "%Y-%m-%d").date() if raw_hour_start else None
    except (ValueError, TypeError):
        h_start = None

    try:
        h_end = datetime.strptime(raw_hour_end, "%Y-%m-%d").date() if raw_hour_end else None
    except (ValueError, TypeError):
        h_end = None

    if not h_start:
        h_start = today - timedelta(days=14)
    if not h_end:
        h_end = today

    # Format for the date inputs
    h_start_str = h_start.isoformat()
    h_end_str = h_end.isoformat()

    hourly_qs = (
        DischargeRecord.objects
        .filter(
            alta_em__isnull=False,
            alta_em__date__gte=h_start,
            alta_em__date__lte=h_end,
        )
        .annotate(hora=ExtractHour("alta_em"))
        .values("hora", "especialidade")
        .annotate(total=Count("id"))
        .order_by("hora", "especialidade")
    )

    # Build hour × specialty matrix
    specialties: set[str] = set()
    hour_data: list[dict] = list(hourly_qs)
    for row in hour_data:
        if row["especialidade"]:
            specialties.add(row["especialidade"])

    sorted_specialties = sorted(specialties)
    hour_dist: dict[str, list[int]] = {esp: [0] * 24 for esp in sorted_specialties}
    for row in hour_data:
        esp = row["especialidade"]
        h = row["hora"]
        if esp and h is not None and 0 <= h <= 23:
            hour_dist[esp][h] = row["total"]

    # Hour labels
    hour_labels = [f"{h:02d}h" for h in range(24)]

    # Build table: total, after 16h, % after 16h
    hourly_table: list[dict[str, Any]] = []
    for esp in sorted_specialties:
        vals = hour_dist[esp]
        total = sum(vals)
        after_16 = sum(vals[16:])
        pct = round(after_16 / total * 100, 1) if total else 0.0
        hourly_table.append({
            "especialidade": esp,
            "total": total,
            "after_16": after_16,
            "pct": pct,
        })
    hourly_table.sort(key=lambda r: -r["pct"])

    context = {
        "page_title": "Altas por Dia",
        "chart_data": chart_data,
        "weekday_avg": weekday_avg,
        "dias": dias,
        "period_options": [30, 60, 90, 180, 365],
        "hour_labels": hour_labels,
        "hour_dist": hour_dist,
        "sorted_specialties": sorted_specialties,
        "hourly_table": hourly_table,
        "h_start": h_start_str,
        "h_end": h_end_str,
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


def _exponential_moving_average(
    values: list[int], span: int
) -> list[float | None]:
    """Calculate exponential moving average with the given span.

    Uses α = 2/(span+1), the common convention that matches pandas.
    The EMA is seeded at position (span-1) with the SMA of the first
    `span` values. Positions before that are None.
    """
    n = len(values)
    result: list[float | None] = [None] * n

    if n < span or span < 1:
        return result

    alpha = 2.0 / (span + 1.0)

    # Seed: SMA of first `span` values at index span-1
    seed_slice = values[:span]
    seed = sum(seed_slice) / len(seed_slice)
    result[span - 1] = round(seed, 1)

    # Compute EMA forward
    ema = seed
    for i in range(span, n):
        ema = alpha * values[i] + (1 - alpha) * ema
        result[i] = round(ema, 1)

    return result


def _parse_dias_param(request: HttpRequest) -> int:
    """Parse ?dias=N from request, defaulting to 90.

    Returns an integer between 1 and 365; invalid/non-numeric values
    fall back to 90.
    """
    dias_str = request.GET.get("dias", "90").strip()
    try:
        dias = int(dias_str)
        if dias < 1:
            dias = 90
    except (ValueError, TypeError):
        dias = 90
    return dias


def _daily_count_chart_context(
    model,
    dias: int,
    dataset_label: str,
    page_title: str,
    daily_chart_title: str,
    weekday_chart_title: str,
    list_url_name: str,
    list_link_label: str,
) -> dict:
    """Build shared chart context for admission/death daily event charts.

    Args:
        model: Django model class with date, count fields (DailyAdmissionCount
               or DailyDeathCount).
        dias: Number of days to include (excludes today).
        dataset_label: Label for the chart dataset ("Admissões" or "Óbitos").
        page_title: HTML page title.
        daily_chart_title: Title for the daily bar chart card.
        weekday_chart_title: Title for the weekday average card.
        list_url_name: Named URL for the corresponding list page.
        list_link_label: Button label for the back-to-list link.

    Returns:
        Dict with chart_data, weekday_avg, period_options, and metadata.
    """
    today = timezone.localdate()

    entries = list(
        model.objects.filter(date__lt=today)
        .order_by("-date")[:dias]
    )
    entries.reverse()  # chronological order

    labels = [e.date.strftime("%d/%m/%Y") for e in entries]
    counts = [e.count for e in entries]

    _WEEKDAY_ABBR = ["seg", "ter", "qua", "qui", "sex", "sáb", "dom"]
    weekend_flags = []
    weekday_short = []
    for e in entries:
        wd = e.date.weekday()  # 0=Mon … 6=Sun
        weekend_flags.append(wd >= 5)
        weekday_short.append(_WEEKDAY_ABBR[wd])

    chart_data = {
        "labels": labels,
        "counts": counts,
        "dataset_label": dataset_label,
        "weekend_flags": weekend_flags,
        "weekday_short": weekday_short,
    }

    weekday_avg = _weekday_average(entries)

    from django.urls import reverse
    context = {
        "page_title": page_title,
        "daily_chart_title": daily_chart_title,
        "weekday_chart_title": weekday_chart_title,
        "chart_data": chart_data,
        "weekday_avg": weekday_avg,
        "dias": dias,
        "period_options": [30, 60, 90, 180, 365],
        "list_url": reverse(list_url_name),
        "list_link_label": list_link_label,
        "dataset_label": dataset_label,
    }
    return context


def _weekday_average(entries: list) -> dict:
    """Compute average discharge count per weekday (Seg..Dom).

    Args:
        entries: list of DailyDischargeCount (already filtered for period).

    Returns:
        dict with keys:
            labels: ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom']
            values: [float] average count per weekday (0.0 if no data).
            counts: [int] number of observations per weekday.
    """
    weekday_labels = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    sums = [0] * 7
    n_days: list[int] = [0] * 7

    for entry in entries:
        wd = entry.date.weekday()  # 0=Mon … 6=Sun
        sums[wd] += entry.count
        n_days[wd] += 1

    values = [
        round(sums[i] / n_days[i], 1) if n_days[i] > 0 else 0.0
        for i in range(7)
    ]

    return {
        "labels": weekday_labels,
        "values": values,
        "counts": n_days,
        "has_data": any(n > 0 for n in n_days),
    }


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
    """Hospital census: filter by ward/sector, specialty, and search patients.

    Displays a table of current inpatients (occupied beds only)
    from the latest CensusSnapshot. Standardized column order and
    filter structure matching the official census page.
    """
    latest = CensusSnapshot.objects.aggregate(latest=Max("captured_at"))["latest"]

    if latest is None:
        return render(request, "services_portal/censo.html", {
            "page_title": "Censo Hospitalar",
            "busca": "",
            "pacientes": [],
            "total": 0,
            "captured_at": None,
            "unidade_options": [],
            "unidade_filter": "",
            "especialidade_options": [],
            "especialidade_filter": "",
            "ordering": "",
        })

    # Base queryset: only occupied beds from the most recent snapshot
    qs = CensusSnapshot.objects.filter(
        captured_at=latest,
        bed_status=BedStatus.OCCUPIED,
    ).order_by("setor", "leito")

    # Free-text search
    busca = request.GET.get("q", "").strip()
    if busca:
        qs = qs.filter(
            Q(nome__icontains=busca) | Q(prontuario__icontains=busca)
        )

    # Filter by unidade (setor)
    unidade_filter = request.GET.get("unidade", "").strip()
    if unidade_filter:
        qs = qs.filter(setor=unidade_filter)

    # Filter by especialidade
    especialidade_filter = request.GET.get("especialidade", "").strip()
    if especialidade_filter:
        qs = qs.filter(especialidade=especialidade_filter)

    snapshots = list(qs)

    # Look up internal Patient IDs for direct linking to admission_list
    prontuarios = [s.prontuario for s in snapshots if s.prontuario]
    patient_map: dict[str, int] = {}
    if prontuarios:
        patient_map = {
            p.patient_source_key: p.pk
            for p in Patient.objects.filter(patient_source_key__in=prontuarios)
        }

    # Look up admission dates for current inpatients (no discharge yet)
    patient_ids = list(patient_map.values())
    admission_date_map: dict[int, date] = {}
    if patient_ids:
        admissions = (
            Admission.objects
            .filter(patient_id__in=patient_ids, discharge_date__isnull=True)
            .order_by("patient_id", "-admission_date")
        )
        seen: set[int] = set()
        for adm in admissions:
            if adm.patient_id not in seen:
                seen.add(adm.patient_id)
                if adm.admission_date:
                    admission_date_map[adm.patient_id] = (
                        adm.admission_date.date()
                        if hasattr(adm.admission_date, "date")
                        else adm.admission_date
                    )

    today = timezone.localdate()

    # ── Resolve specialty codes ←→ full names ───────────────────────
    specialty_code_to_name: dict[str, str] = {
        s.code: s.name
        for s in Specialty.objects.all()
    }
    specialty_name_to_code: dict[str, str] = {
        s.name: s.code
        for s in Specialty.objects.all()
    }

    def _resolve_especialidade(raw: str) -> tuple[str, str]:
        """Return (sigla, nome_completo) given either a code or full name."""
        if raw in specialty_code_to_name:
            return raw, specialty_code_to_name[raw]
        if raw in specialty_name_to_code:
            return specialty_name_to_code[raw], raw
        return raw, raw

    pacientes: list[dict[str, Any]] = []
    for s in snapshots:
        pid = patient_map.get(s.prontuario)
        adm_date = admission_date_map.get(pid) if pid else None

        # Use data from XLSX census when available (preferred), fallback to Admission
        if s.tempo_internacao is not None:
            # Direct from XLSX — numeric, formatted for display
            dias = s.tempo_internacao
            tempo_internacao = f"{dias} dia{'s' if dias != 1 else ''}"
            tempo_numeric = dias
            data_internacao = s.data_internacao or ""
        elif adm_date:
            data_internacao = adm_date.strftime("%d/%m/%Y")
            dias = (today - adm_date).days
            tempo_internacao = f"{dias} dia{'s' if dias != 1 else ''}"
            tempo_numeric = dias
        else:
            data_internacao = ""
            tempo_internacao = ""
            tempo_numeric = 0

        esp_sigla, esp_nome = _resolve_especialidade(s.especialidade)

        pacientes.append({
            "prontuario": s.prontuario,
            "nome": s.nome,
            "unidade": s.setor,
            "unidade_nome": s.setor,
            "quarto_leito": s.leito,
            "especialidade": esp_sigla,
            "especialidade_nome": esp_nome,
            "data_internacao": data_internacao,
            "tempo_internacao": tempo_internacao,
            "tempo_numeric": tempo_numeric,
            "patient_id": pid,
        })

    # ── Ordering ─────────────────────────────────────────────────────
    ordering = request.GET.get("ordenar", "").strip()
    if ordering == "tempo_asc":
        pacientes.sort(key=lambda p: p["tempo_numeric"])
    elif ordering == "tempo_desc":
        pacientes.sort(key=lambda p: -p["tempo_numeric"])
    elif ordering == "unidade":
        pacientes.sort(key=lambda p: (p["unidade"], p["quarto_leito"]))
    elif ordering == "especialidade":
        pacientes.sort(key=lambda p: (p["especialidade"], p["unidade"]))

    # ── Distinct values for filter dropdowns ─────────────────────────
    base_dropdown = CensusSnapshot.objects.filter(
        captured_at=latest,
        bed_status=BedStatus.OCCUPIED,
    )
    unidade_options = list(
        base_dropdown.values_list("setor", flat=True)
        .distinct()
        .order_by("setor")
    )
    raw_especialidade_options = list(
        base_dropdown.values_list("especialidade", flat=True)
        .exclude(especialidade="")
        .distinct()
        .order_by("especialidade")
    )
    # CES-S1: Build options with value (for filtering) and label (for display).
    # Uses specialty_code_to_name dict already built above for resolution.
    especialidade_options = [
        {
            "value": raw,
            "label": specialty_code_to_name.get(raw, raw),
            "code": raw,
        }
        for raw in raw_especialidade_options
    ]

    return render(request, "services_portal/censo.html", {
        "page_title": "Censo Hospitalar",
        "busca": busca,
        "pacientes": pacientes,
        "total": len(pacientes),
        "captured_at": latest,
        "unidade_options": unidade_options,
        "unidade_filter": unidade_filter,
        "especialidade_options": especialidade_options,
        "especialidade_filter": especialidade_filter,
        "ordering": ordering,
    })


@login_required
def ingestion_metrics(request: HttpRequest) -> HttpResponse:
    """Ingestion operational metrics page with filters and run table (S7).

    Supports filtering by period (24h/7d/30d), status, intent and
    failure_reason via querystring. Renders aggregated summary cards
    and a detailed run table, both coherent with the filtered dataset.

    CQM-S5: Also delivers batch_failure_stats for the latest finished
    census execution batch.

    IWBO-S3: Batch detail mode via ?batch_id=<id>. When batch_id is
    present and valid, renders run table only for that batch. Without
    batch_id, no global runs table is shown — only batch history.
    """
    periodo = request.GET.get("periodo", "24h").strip()
    status = request.GET.get("status", "").strip()
    intent = request.GET.get("intent", "").strip()
    failure_reason = request.GET.get("failure_reason", "").strip()
    tab = request.GET.get("tab", "runs").strip()
    if tab not in ("runs", "patients"):
        tab = "runs"

    # IWBO-S3: Parse batch_id for detail mode
    batch_id_raw = request.GET.get("batch_id", "").strip()
    selected_batch = None
    show_batch_detail = False
    batch_not_found = False
    selected_batch_runs_page = None
    selected_batch_stats = None

    if batch_id_raw:
        try:
            batch_id_val = int(batch_id_raw)
            selected_batch = CensusExecutionBatch.objects.filter(pk=batch_id_val).first()
        except (ValueError, TypeError):
            selected_batch = None

        if selected_batch is not None:
            show_batch_detail = True

            # Build filtered queryset within the batch (no period filter —
            # batch detail must show all runs of the batch regardless of
            # the default 24h window).
            qs = IngestionRun.objects.filter(batch=selected_batch)
            if status:
                qs = qs.filter(status=status)
            if intent:
                qs = qs.filter(intent=intent)
            if failure_reason:
                qs = qs.filter(failure_reason=failure_reason)

            # Stats for the batch's filtered runs
            total = qs.count()
            success_count = qs.filter(status="succeeded").count()
            timeout_count = qs.filter(timed_out=True).count()
            success_rate = round(success_count / total * 100, 1) if total else 0.0
            timeout_rate = round(timeout_count / total * 100, 1) if total else 0.0

            runs_with_duration = qs.exclude(processing_started_at__isnull=True)
            durations: list[float] = []
            for run in runs_with_duration:
                if run.processing_started_at and run.finished_at:
                    durations.append(
                        (run.finished_at - run.processing_started_at).total_seconds()
                    )
            avg_seconds = round(sum(durations) / len(durations)) if durations else 0

            selected_batch_stats = {
                "total_finished": total,
                "success_rate": success_rate,
                "timeout_rate": timeout_rate,
                "avg_duration_seconds": avg_seconds,
            }

            # Paginate runs within the batch
            run_page_size = 50
            run_paginator = Paginator(qs.order_by("-finished_at"), run_page_size)
            run_page_number = request.GET.get("run_page", 1)
            try:
                run_page_number = int(run_page_number)
            except (ValueError, TypeError):
                run_page_number = 1
            try:
                selected_batch_runs_page = run_paginator.page(run_page_number)
            except EmptyPage:
                selected_batch_runs_page = run_paginator.page(
                    run_paginator.num_pages
                )
        else:
            batch_not_found = True

    result = _build_filtered_queryset(
        periodo=periodo,
        status=status,
        intent=intent,
        failure_reason=failure_reason,
    )

    # Collect distinct values for filter dropdowns from the full dataset
    # (not filtered by status/intent so dropdowns always have options).
    # .order_by() clears Meta.ordering so .distinct() works correctly;
    # otherwise DISTINCT applies to (field, started_at) tuples.
    all_finished = IngestionRun.objects.filter(finished_at__isnull=False)
    all_statuses = sorted(
        all_finished.order_by().values_list("status", flat=True).distinct()
    )
    all_intents = sorted(
        t for t in
        all_finished.order_by().values_list("intent", flat=True).distinct()
        if t
    )
    all_failure_reasons = sorted(
        r for r in
        all_finished.order_by().exclude(failure_reason="")
        .values_list("failure_reason", flat=True).distinct()
    )

    batch_failure_stats = _get_latest_batch_failure_stats()

    # IWBO-S2: Batch history table (paginated)
    batch_history_context = _get_batch_history_context(request)

    context: dict[str, Any] = {
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
            "statuses": all_statuses,
            "intents": all_intents,
            "failure_reasons": all_failure_reasons,
        },
        "batch_failure_stats": batch_failure_stats,
        "active_tab": tab,
        **batch_history_context,
        # IWBO-S3: Batch detail keys
        "show_batch_detail": show_batch_detail,
        "selected_batch": selected_batch,
        "selected_batch_runs_page": selected_batch_runs_page,
        "selected_batch_stats": selected_batch_stats,
        "batch_not_found": batch_not_found,
        "run_filters": {
            "status": status,
            "intent": intent,
            "failure_reason": failure_reason,
        },
    }
    return render(request, "services_portal/ingestion_metrics.html", context)


def _get_latest_batch_failure_stats() -> dict:
    """Aggregate final-failure stats for the latest finished census batch.

    IWBO-S1: Also computes observed worker efficiency metrics from
    the batch's runs and attempt records.

    Returns a dict with keys:
        has_batch: bool — False when no finished batch exists.
        batch_id, status, total_duration_seconds, started_at,
        enqueue_finished_at, finished_at — batch metadata.
        final_failures_total: int — number of FinalRunFailure rows.
        failures_by_intent: dict[str, int] — count per operational intent.
        failure_patients: list[dict] — sorted by failed_at descending;
            each dict has patient_record, intent, failed_at,
            attempts_exhausted.
        runs_total, runs_succeeded, runs_failed, runs_active — job counts.
        observed_worker_count, observed_worker_labels — worker identity.
        observed_peak_concurrency, observed_avg_concurrency — concurrency.
        throughput_jobs_per_minute — jobs / drain minutes.
        avg_processing_duration_seconds, avg_attempt_duration_seconds.

    CQM-S5: Safe fallback to empty structure when no batch is available.
    """
    batch = (
        CensusExecutionBatch.objects
        .filter(finished_at__isnull=False)
        .order_by("-finished_at")
        .first()
    )

    if batch is None:
        return _empty_batch_stats()

    failures = FinalRunFailure.objects.filter(
        batch=batch,
    ).order_by("-failed_at")

    failures_by_intent: dict[str, int] = {}
    failure_patients: list[dict] = []

    for f in failures:
        failures_by_intent[f.intent] = (
            failures_by_intent.get(f.intent, 0) + 1
        )
        failure_patients.append({
            "patient_record": f.patient_record,
            "intent": f.intent,
            "failed_at": f.failed_at,
            "attempts_exhausted": f.attempts_exhausted,
        })

    total_duration_hours: float | None = None
    if batch.total_duration_seconds is not None:
        total_duration_hours = round(batch.total_duration_seconds / 3600, 1)

    # ── IWBO-S1: Batch run and attempt metrics ───────────────────────
    batch_runs = IngestionRun.objects.filter(batch=batch)
    runs_total = batch_runs.count()
    runs_succeeded = batch_runs.filter(status="succeeded").count()
    runs_failed = batch_runs.filter(status="failed").count()
    runs_active = batch_runs.filter(status__in=["queued", "running"]).count()

    # Worker labels distinct non-empty
    worker_labels_qs = (
        batch_runs
        .exclude(worker_label="")
        .values_list("worker_label", flat=True)
        .distinct()
        .order_by("worker_label")
    )
    observed_worker_labels = list(worker_labels_qs)
    observed_worker_count = len(observed_worker_labels)

    # Attempt-level metrics
    attempts = IngestionRunAttempt.objects.filter(run__batch=batch)

    # Sweep-line for peak concurrency
    events: list[tuple] = []
    for attempt in attempts.iterator():
        if attempt.started_at is not None:
            events.append((attempt.started_at, 1))
        if attempt.finished_at is not None:
            events.append((attempt.finished_at, -1))

    # Sort: finished_at (-1) before started_at (+1) for equal timestamps
    events.sort(key=lambda e: (e[0], e[1]))

    peak_concurrency = 0
    current = 0
    for _ts, delta in events:
        current += delta
        if current > peak_concurrency:
            peak_concurrency = current

    # Drain window
    drain_seconds: float | None = None
    if batch.enqueue_finished_at and batch.finished_at:
        drain_seconds = (
            batch.finished_at - batch.enqueue_finished_at
        ).total_seconds()

    # Average concurrency = sum(attempt_durations) / drain_seconds
    total_attempt_duration: float = 0.0
    attempt_durations: list[float] = []
    for attempt in attempts.iterator():
        if attempt.started_at is not None and attempt.finished_at is not None:
            secs = (attempt.finished_at - attempt.started_at).total_seconds()
            total_attempt_duration += secs
            attempt_durations.append(secs)

    avg_concurrency = 0.0
    if drain_seconds and drain_seconds > 0:
        avg_concurrency = round(total_attempt_duration / drain_seconds, 1)

    # Throughput: terminal runs / minutes of drain
    throughput = 0.0
    if drain_seconds and drain_seconds > 0:
        terminal_runs = runs_succeeded + runs_failed
        drain_minutes = drain_seconds / 60.0
        if drain_minutes > 0:
            throughput = round(terminal_runs / drain_minutes, 1)

    # Average processing duration (from run timestamps)
    runs_with_duration = batch_runs.exclude(
        processing_started_at__isnull=True
    ).exclude(finished_at__isnull=True)
    processing_durations: list[float] = []
    for run in runs_with_duration.iterator():
        if run.finished_at is not None and run.processing_started_at is not None:
            pd = (run.finished_at - run.processing_started_at).total_seconds()
            processing_durations.append(pd)
    avg_processing = (
        round(sum(processing_durations) / len(processing_durations))
        if processing_durations else 0
    )

    # Average attempt duration
    avg_attempt = (
        round(sum(attempt_durations) / len(attempt_durations))
        if attempt_durations else 0
    )

    return {
        "has_batch": True,
        "batch_id": batch.pk,
        "status": batch.status,
        "total_duration_seconds": batch.total_duration_seconds,
        "total_duration_hours": total_duration_hours,
        "started_at": batch.started_at,
        "enqueue_finished_at": batch.enqueue_finished_at,
        "finished_at": batch.finished_at,
        "final_failures_total": len(failure_patients),
        "failures_by_intent": failures_by_intent,
        "failure_patients": failure_patients,
        # IWBO-S1: Worker efficiency metrics
        "runs_total": runs_total,
        "runs_succeeded": runs_succeeded,
        "runs_failed": runs_failed,
        "runs_active": runs_active,
        "observed_worker_count": observed_worker_count,
        "observed_worker_labels": observed_worker_labels,
        "observed_peak_concurrency": peak_concurrency,
        "observed_avg_concurrency": avg_concurrency,
        "throughput_jobs_per_minute": throughput,
        "avg_processing_duration_seconds": avg_processing,
        "avg_attempt_duration_seconds": avg_attempt,
    }


def _empty_batch_stats() -> dict:
    """Return fully zeroed batch stats structure.

    Used when no finished batch exists or as safe fallback.
    Includes all keys from CQM-S5 and IWBO-S1.
    """
    return {
        "has_batch": False,
        "batch_id": None,
        "status": None,
        "total_duration_seconds": None,
        "total_duration_hours": None,
        "started_at": None,
        "enqueue_finished_at": None,
        "finished_at": None,
        "final_failures_total": 0,
        "failures_by_intent": {},
        "failure_patients": [],
        "runs_total": 0,
        "runs_succeeded": 0,
        "runs_failed": 0,
        "runs_active": 0,
        "observed_worker_count": 0,
        "observed_worker_labels": [],
        "observed_peak_concurrency": 0,
        "observed_avg_concurrency": 0.0,
        "throughput_jobs_per_minute": 0.0,
        "avg_processing_duration_seconds": 0,
        "avg_attempt_duration_seconds": 0,
        # IWBO-S2: Batch history table fields
        "drain_duration_seconds": None,
    }


# ── IWBO-S2: Batch history helpers ──────────────────────────────────────


_BATCH_PAGE_SIZE = 20


def _compute_batch_metrics(batch: CensusExecutionBatch) -> dict:
    """Compute derived metrics for a single CensusExecutionBatch.

    Calculates run counts, worker identity, concurrency, throughput,
    and average durations from the batch's IngestionRun and
    IngestionRunAttempt records.

    Returns dict with keys:
        batch_id, status, started_at, enqueue_finished_at, finished_at,
        drain_duration_seconds, runs_total, runs_succeeded, runs_failed,
        runs_active, observed_worker_count, observed_worker_labels,
        observed_peak_concurrency, observed_avg_concurrency,
        throughput_jobs_per_minute, avg_processing_duration_seconds,
        avg_attempt_duration_seconds.
    """
    batch_runs = IngestionRun.objects.filter(batch=batch)
    runs_total = batch_runs.count()
    runs_succeeded = batch_runs.filter(status="succeeded").count()
    runs_failed = batch_runs.filter(status="failed").count()
    runs_active = batch_runs.filter(status__in=["queued", "running"]).count()

    # Worker labels distinct non-empty
    worker_labels_qs = (
        batch_runs
        .exclude(worker_label="")
        .values_list("worker_label", flat=True)
        .distinct()
        .order_by("worker_label")
    )
    observed_worker_labels = list(worker_labels_qs)
    observed_worker_count = len(observed_worker_labels)

    # Attempt-level metrics
    attempts = IngestionRunAttempt.objects.filter(run__batch=batch)

    # Sweep-line for peak concurrency
    events: list[tuple] = []
    for attempt in attempts.iterator():
        if attempt.started_at is not None:
            events.append((attempt.started_at, 1))
        if attempt.finished_at is not None:
            events.append((attempt.finished_at, -1))

    events.sort(key=lambda e: (e[0], e[1]))

    peak_concurrency = 0
    current = 0
    for _ts, delta in events:
        current += delta
        if current > peak_concurrency:
            peak_concurrency = current

    # Drain window
    drain_seconds: float | None = None
    if batch.enqueue_finished_at and batch.finished_at:
        drain_seconds = (
            batch.finished_at - batch.enqueue_finished_at
        ).total_seconds()

    # Average concurrency = sum(attempt_durations) / drain_seconds
    total_attempt_duration: float = 0.0
    attempt_durations: list[float] = []
    for attempt in attempts.iterator():
        if attempt.started_at is not None and attempt.finished_at is not None:
            secs = (attempt.finished_at - attempt.started_at).total_seconds()
            total_attempt_duration += secs
            attempt_durations.append(secs)

    avg_concurrency = 0.0
    if drain_seconds and drain_seconds > 0:
        avg_concurrency = round(total_attempt_duration / drain_seconds, 1)

    # Throughput: terminal runs / minutes of drain
    throughput = 0.0
    if drain_seconds and drain_seconds > 0:
        terminal_runs = runs_succeeded + runs_failed
        drain_minutes = drain_seconds / 60.0
        if drain_minutes > 0:
            throughput = round(terminal_runs / drain_minutes, 1)

    # Average processing duration (from run timestamps)
    runs_with_duration = batch_runs.exclude(
        processing_started_at__isnull=True
    ).exclude(finished_at__isnull=True)
    processing_durations: list[float] = []
    for run in runs_with_duration.iterator():
        if run.finished_at is not None and run.processing_started_at is not None:
            pd = (run.finished_at - run.processing_started_at).total_seconds()
            processing_durations.append(pd)
    avg_processing = (
        round(sum(processing_durations) / len(processing_durations))
        if processing_durations else 0
    )

    # Average attempt duration
    avg_attempt = (
        round(sum(attempt_durations) / len(attempt_durations))
        if attempt_durations else 0
    )

    return {
        "batch_id": batch.pk,
        "status": batch.status,
        "started_at": batch.started_at,
        "enqueue_finished_at": batch.enqueue_finished_at,
        "finished_at": batch.finished_at,
        "drain_duration_seconds": drain_seconds,
        "drain_duration_hours": round(drain_seconds / 3600, 1) if drain_seconds else None,
        "runs_total": runs_total,
        "runs_succeeded": runs_succeeded,
        "runs_failed": runs_failed,
        "runs_active": runs_active,
        "observed_worker_count": observed_worker_count,
        "observed_worker_labels": observed_worker_labels,
        "observed_peak_concurrency": peak_concurrency,
        "observed_avg_concurrency": avg_concurrency,
        "throughput_jobs_per_minute": throughput,
        "avg_processing_duration_seconds": avg_processing,
        "avg_attempt_duration_seconds": avg_attempt,
    }


def _get_batch_history_context(request: HttpRequest) -> dict:
    """Build context for the paginated batch history table.

    Queries finished CensusExecutionBatch records ordered by
    -finished_at, -id, paginates using batch_page param, and
    computes metrics only for batches on the current page.

    Returns dict with keys:
        batch_history: list of batch metric dicts for current page.
        batch_page: django Page object (for template pagination).
    """
    batches_qs = (
        CensusExecutionBatch.objects
        .filter(finished_at__isnull=False)
        .order_by("-finished_at", "-id")
    )

    page_size = _BATCH_PAGE_SIZE
    page_param = "batch_page"

    paginator = Paginator(batches_qs, page_size)

    page_number = request.GET.get(page_param, 1)
    try:
        page_number = int(page_number)
    except (ValueError, TypeError):
        page_number = 1

    try:
        page = paginator.page(page_number)
    except EmptyPage:
        page = paginator.page(paginator.num_pages)

    # Compute metrics only for batches on this page
    batch_metrics = []
    for batch in page.object_list:
        batch_metrics.append(_compute_batch_metrics(batch))

    return {
        "batch_history": batch_metrics,
        "batch_page": page,
    }


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


# ── Template record helpers (normalized → dict fallback) ──────────────


def _admission_records_for_template(entry) -> tuple[list[dict], list[str]]:
    """Build template-friendly records from AdmissionRecord or raw_data."""
    if entry and hasattr(entry, "records"):
        record_objs = list(entry.records.all())
        if record_objs:
            recs = []
            for r in record_objs:
                d = {
                    "prontuario": r.prontuario,
                    "nome": r.nome,
                    "data_internacao": r.data_internacao,
                }
                d.update(r.raw_extra)
                recs.append(d)
            return recs, list(recs[0].keys())
    # Fallback to raw_data
    records = entry.raw_data if entry else []
    columns = list(records[0].keys()) if records else []
    return records, columns


def _death_records_for_template(entry) -> tuple[list[dict], list[str]]:
    """Build template-friendly records from DeathRecord or raw_data."""
    if entry and hasattr(entry, "records"):
        record_objs = list(entry.records.all())
        if record_objs:
            recs = []
            for r in record_objs:
                d = {
                    "prontuario": r.prontuario,
                    "nome": r.nome,
                    "data_obito": r.data_obito,
                }
                d.update(r.raw_extra)
                recs.append(d)
            return recs, list(recs[0].keys())
    records = entry.raw_data if entry else []
    columns = list(records[0].keys()) if records else []
    return records, columns


def _discharge_records_for_template(entry) -> tuple[list[dict], list[str]]:
    """Build template-friendly records from DischargeRecord or raw_data."""
    if entry and hasattr(entry, "records"):
        record_objs = list(entry.records.all())
        if record_objs:
            recs = []
            for r in record_objs:
                d = {
                    "prontuario": r.prontuario,
                    "nome": r.nome,
                    "data_internacao": r.data_internacao,
                    "leito": r.leito,
                    "especialidade": r.especialidade,
                }
                d.update(r.raw_extra)
                recs.append(d)
            return recs, list(recs[0].keys())
    records = entry.raw_data if entry else []
    columns = list(records[0].keys()) if records else []
    return records, columns


_HIGH_TURNOVER_KEYWORDS = (
    "CRPA", "SALA", "OBSERVACAO", "OBSERVAÇÃO",
    "PS", "EMERGENCIA", "EMERGÊNCIA", "PRONTO",
)


def _is_high_turnover_sector(sector: str) -> bool:
    """Check if a sector name indicates high patient turnover."""
    if not sector:
        return False
    upper = sector.upper()
    return any(kw in upper for kw in _HIGH_TURNOVER_KEYWORDS)


@login_required
def sector_passage_history(request: HttpRequest) -> HttpResponse:
    """Setores > Histórico de Passagem: patients who passed through a sector.

    Shows patients whose movement through the selected sector was captured
    by census snapshots within the period.  Ground-truth for "currently in
    sector" is the latest CensusSnapshot, not PatientMovement flags.

    GET params:
        setor — sector name (default: first sector from movements)
        dias  — period in days: 7, 30, 90 (default: 7)
    """
    dias_str = request.GET.get("dias", "7").strip()
    try:
        dias = int(dias_str)
        if dias not in (7, 30, 90):
            dias = 7
    except (ValueError, TypeError):
        dias = 7

    cutoff = timezone.now() - timedelta(days=dias)

    # ── Sectors dropdown ────────────────────────────────────────────
    sectors_list = list(
        PatientMovement.objects.values_list("sector", flat=True)
        .distinct()
        .order_by("sector")
    )

    sector = request.GET.get("setor", "").strip()
    if not sector and sectors_list:
        sector = sectors_list[0]

    # ── Base queryset ───────────────────────────────────────────────
    qs = PatientMovement.objects.filter(
        last_seen_at__gte=cutoff,
    )

    if sector:
        qs = qs.filter(sector=sector)

    qs = qs.select_related("patient")

    # ── Annotate with is_latest flag ─────────────────────────────────
    patient_max_seq = PatientMovement.objects.filter(
        patient=OuterRef("patient")
    ).values("patient").annotate(
        max_seq=Max("sequence")
    ).values("max_seq")

    qs = qs.annotate(
        is_latest=Q(sequence=Subquery(patient_max_seq))
    )

    # ── Ground truth: who is in this sector RIGHT NOW? ───────────────
    latest_census = CensusSnapshot.objects.aggregate(
        latest=Max("captured_at")
    )["latest"]

    current_patient_ids: set[int] = set()
    if latest_census and sector:
        current_prontuarios = CensusSnapshot.objects.filter(
            captured_at=latest_census,
            setor=sector,
            bed_status=BedStatus.OCCUPIED,
        ).values_list("prontuario", flat=True)

        current_pront_list = [p for p in current_prontuarios if p]
        if current_pront_list:
            current_patient_ids = set(
                Patient.objects.filter(
                    patient_source_key__in=current_pront_list
                ).values_list("id", flat=True)
            )

    # ── Summary cards ────────────────────────────────────────────────
    total = qs.count()
    still_in = qs.filter(patient_id__in=current_patient_ids).count()
    left = total - still_in

    today = timezone.localdate()

    # Average stay: separate current patients vs those who left
    avg_current_stay: float | None = None
    avg_completed_stay: float | None = None

    if still_in > 0:
        current_qs = qs.filter(patient_id__in=current_patient_ids)
        current_days = [
            max((today - m.movement_date).days, 0)
            for m in current_qs.iterator()
        ]
        if current_days:
            avg_current_stay = round(
                sum(current_days) / len(current_days), 1
            )

    if left > 0:
        left_qs = qs.exclude(patient_id__in=current_patient_ids)
        left_days = [
            max((today - m.movement_date).days, 0)
            for m in left_qs.iterator()
        ]
        if left_days:
            avg_completed_stay = round(
                sum(left_days) / len(left_days), 1
            )

    # ── Patient table ────────────────────────────────────────────────
    movements = qs.order_by("-movement_date")

    patients: list[dict[str, Any]] = []
    for m in movements:
        if m.discharge_type:
            destination = m.discharge_type
        elif m.patient_id in current_patient_ids:
            destination = "(no setor)"
        else:
            destination = "(não está mais no setor)"

        days_in_sector = (today - m.movement_date).days
        if days_in_sector < 0:
            days_in_sector = 0

        patients.append({
            "name": m.patient.name,
            "prontuario": m.patient.patient_source_key,
            "entry_date": m.movement_date,
            "days": days_in_sector,
            "destination": destination,
        })

    context = {
        "page_title": "Setores — Histórico de Passagem",
        "sectors": sectors_list,
        "selected_sector": sector,
        "period_days": dias,
        "period_options": [7, 30, 90],
        "summary": {
            "total": total,
            "still_in": still_in,
            "left": left,
            "avg_current_stay": avg_current_stay,
            "avg_completed_stay": avg_completed_stay,
        },
        "patients": patients,
        "active_tab": "setores",
        "high_turnover_warning": (
            _is_high_turnover_sector(sector) if sector else False
        ),
    }
    return render(
        request,
        "services_portal/sector_passage_history.html",
        context,
    )


@login_required
def sector_occupation(request: HttpRequest) -> HttpResponse:
    """Redirect to renamed Histórico de Passagem page."""
    from django.shortcuts import redirect
    return redirect("services_portal:sector_passage_history")


@login_required
def sector_indicators(request: HttpRequest) -> HttpResponse:
    """Setores > Indicadores: aggregated analytics from PatientMovement.

    GET params:
        dias — period in days: 7, 30, 90, 180 (default: 30)
        origem — optional origin sector to filter Card 2 (flow)

    Provides 4 analytical cards in context:
        avg_stay, destinations, long_stay, bottlenecks

    Cards now use CensusSnapshot as ground truth for current occupancy
    and next-movement dates for actual stay calculation.
    """
    dias_str = request.GET.get("dias", "30").strip()
    try:
        dias = int(dias_str)
        if dias not in (7, 30, 90, 180):
            dias = 30
    except (ValueError, TypeError):
        dias = 30

    cutoff = timezone.now() - timedelta(days=dias)
    today = timezone.localdate()

    # ── Shared: latest census ground truth ──────────────────────────
    latest_census = CensusSnapshot.objects.aggregate(
        latest=Max("captured_at")
    )["latest"]

    current_by_sector: dict[str, set[str]] = {}
    if latest_census:
        for snap in CensusSnapshot.objects.filter(
            captured_at=latest_census,
            bed_status=BedStatus.OCCUPIED,
        ):
            pront = snap.prontuario.strip()
            if pront:
                current_by_sector.setdefault(snap.setor, set()).add(pront)

    # ── Card 1: Average stay by sector ──────────────────────────────
    # Correct calculation: for each movement, stay = next movement_date
    # minus this movement_date (or today minus movement_date for the
    # last movement).  Assumes movements are ordered by sequence.
    sector_stays: dict[str, list[int]] = {}
    movements_all = list(
        PatientMovement.objects
        .filter(first_seen_at__gte=cutoff)
        .order_by("patient", "sequence")
    )
    # Group consecutive movements per patient
    for _patient_id, group in groupby(
        movements_all, key=lambda m: m.patient_id
    ):
        mvts = list(group)
        for i, m in enumerate(mvts):
            if i + 1 < len(mvts):
                nxt = mvts[i + 1].movement_date
                days = (nxt - m.movement_date).days
            else:
                days = (today - m.movement_date).days
            if days < 0:
                days = 0
            sector_stays.setdefault(m.sector, []).append(days)

    avg_stay: list[dict[str, Any]] = []
    for sector, stays in sector_stays.items():
        if stays:
            avg_stay.append({
                "sector": sector,
                "avg_days": round(sum(stays) / len(stays), 1),
            })
    avg_stay.sort(key=lambda x: -x["avg_days"])

    # ── Card 2: Top destination sectors from origin ─────────────────
    # Filters by PREVIOUS movement's sector (actual clinical origin),
    # not the census 'origin' field (which contains bed codes).
    origem = request.GET.get("origem", "").strip()

    if origem:
        # Find movements whose previous movement was in sector `origem`
        prev_sector_subq = PatientMovement.objects.filter(
            patient=OuterRef("patient"),
            sequence=OuterRef("sequence") - 1,
        ).values("sector")[:1]

        dest_qs = (
            PatientMovement.objects
            .filter(first_seen_at__gte=cutoff)
            .annotate(prev_sector=Subquery(prev_sector_subq))
            .filter(prev_sector=origem)
        )
    else:
        dest_qs = PatientMovement.objects.filter(first_seen_at__gte=cutoff)

    destinations = list(
        dest_qs
        .values("sector")
        .annotate(count=Count("id"))
        .order_by("-count")[:10]
    )

    # Origin dropdown: now shows actual sector names (not bed codes)
    origin_options = sorted(
        PatientMovement.objects
        .order_by()  # clear Meta.ordering so distinct() works on sector alone
        .values_list("sector", flat=True)
        .distinct()
    )

    # ── Card 3: Long-stay patients (>15 days) ───────────────────────
    # Only counts patients who are STILL in the sector (per latest
    # census), not just anyone with discharge_type="".
    long_stay_threshold = timezone.now() - timedelta(days=15)
    long_stay_counts: dict[str, int] = {}

    long_movements = PatientMovement.objects.filter(
        first_seen_at__lte=long_stay_threshold,
    ).select_related("patient")

    for m in long_movements.iterator():
        pront = m.patient.patient_source_key
        if pront and pront in current_by_sector.get(m.sector, set()):
            long_stay_counts[m.sector] = (
                long_stay_counts.get(m.sector, 0) + 1
            )

    long_stay = sorted(
        [{"sector": s, "count": c} for s, c in long_stay_counts.items()],
        key=lambda x: -x["count"],
    )

    # ── Card 4: Bottlenecks (entries > exits) ───────────────────────
    # Entry: movement first seen in period.
    # Exit:  movement last seen in period AND patient NOT in latest
    #        census for that sector (they left).
    entries_qs = (
        PatientMovement.objects
        .filter(first_seen_at__gte=cutoff)
        .values("sector")
        .annotate(entry_count=Count("id"))
    )
    entries_map: dict[str, int] = {
        e["sector"]: e["entry_count"] for e in entries_qs
    }

    exits_map: dict[str, int] = {}
    exit_movements = PatientMovement.objects.filter(
        last_seen_at__gte=cutoff,
    ).select_related("patient")
    for m in exit_movements.iterator():
        pront = m.patient.patient_source_key
        if pront and pront not in current_by_sector.get(m.sector, set()):
            exits_map[m.sector] = exits_map.get(m.sector, 0) + 1

    all_sectors = set(list(entries_map.keys()) + list(exits_map.keys()))
    bottlenecks: list[dict[str, Any]] = []
    for sector in sorted(all_sectors):
        entry_count = entries_map.get(sector, 0)
        exit_count = exits_map.get(sector, 0)
        net = entry_count - exit_count
        if net > 0:
            bottlenecks.append({
                "sector": sector,
                "entries": entry_count,
                "exits": exit_count,
                "net": net,
            })
    bottlenecks.sort(key=lambda b: -b["net"])

    context = {
        "page_title": "Setores — Indicadores",
        "period_days": dias,
        "period_options": [7, 30, 90, 180],
        "avg_stay": avg_stay,
        "origin_filter": origem,
        "origin_options": origin_options,
        "destinations": destinations,
        "long_stay": long_stay,
        "bottlenecks": bottlenecks,
    }
    return render(
        request, "services_portal/sector_indicators.html", context
    )
