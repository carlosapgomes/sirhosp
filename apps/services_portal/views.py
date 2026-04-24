"""Services portal views: dashboard, census, risk monitor.

Slice S2: Dashboard with operational stats (demo data).
"""

from __future__ import annotations

from datetime import date, timedelta

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render


@login_required
def dashboard(request: HttpRequest) -> HttpResponse:
    """Main dashboard with operational indicators.

    Displays current inpatient census, total registered patients,
    24h discharges, and data collection status.

    Uses demo/stub data for indicators not yet backed by real queries.
    """
    context = {
        "page_title": "Dashboard",
        "stats": {
            "internados": 142,
            "cadastrados": 5230,
            "altas_24h": 12,
        },
        "coleta": {
            "setores": 18,
            "ultima_varredura": "há 4 minutos",
        },
    }
    return render(request, "services_portal/dashboard.html", context)


@login_required
def censo(request: HttpRequest) -> HttpResponse:
    """Hospital census: filter by ward/sector and search patients.

    Displays a table of current inpatients with bed, name, registry,
    and admission date. Supports filtering by sector (dropdown) and
    free-text search.

    Uses demo/stub data until current inpatient sync is implemented.
    """
    # Demo sectors
    setores_demo = [
        "UTI Adulto", "UTI Neonatal", "Clínica Médica",
        "Clínica Cirúrgica", "Ortopedia", "Cardiologia",
        "Neurologia", "Pediatria", "Maternidade",
        "Pronto Socorro", "Oncologia", "Nefrologia",
    ]

    # Demo patient data (table rows)
    def _p(leito, nome, registro, admissao, setor):
        return {"leito": leito, "nome": nome, "registro": registro,
                "admissao": admissao, "setor": setor}

    pacientes_demo = [
        _p("202-A", "Fulano de Tal", "00123", "20/01/2026", "Clínica Médica"),
        _p("UTI-05", "Beltrano de Souza", "00456", "22/01/2026", "UTI Adulto"),
        _p("301-B", "Maria Oliveira", "00789", "25/01/2026", "Clínica Médica"),
        _p("UTI-02", "José Ferreira", "00890", "23/01/2026", "UTI Adulto"),
        _p("405-C", "Ana Paula Reis", "00332", "05/02/2026", "Ortopedia"),
        _p("UTI-NEO-01", "Lucas Mendes", "01234", "28/01/2026", "UTI Neonatal"),
        _p("502-A", "Carla Dantas", "01567", "18/01/2026", "Cardiologia"),
        _p("601-D", "Rafael Torres", "01890", "10/02/2026", "Neurologia"),
    ]

    setor_filtro = request.GET.get("setor", "").strip()
    busca = request.GET.get("q", "").strip()

    # Filter
    pacientes = pacientes_demo
    if setor_filtro and setor_filtro != "Todos":
        pacientes = [p for p in pacientes if p["setor"] == setor_filtro]
    if busca:
        busca_lower = busca.lower()
        pacientes = [
            p for p in pacientes
            if busca_lower in p["nome"].lower() or busca_lower in p["registro"]
        ]

    context = {
        "page_title": "Censo Hospitalar",
        "setores": setores_demo,
        "setor_filtro": setor_filtro,
        "busca": busca,
        "pacientes": pacientes,
        "total": len(pacientes),
    }
    return render(request, "services_portal/censo.html", context)


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
        date_from = date.today() - timedelta(days=days)

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
