"""XLSX export of the aggregate cut (PEND-S4, D8/PP-08).

Any authenticated user downloads every item of the shared conservative
cut — filters and per-item ordering apply, only view mode and
pagination are ignored. One row per item in its current state, exact
PP-08 columns, literal text cells, no history, no server-side file.
``Cache-Control: private, no-store`` on every response; GET never
mutates (a count-only log line carries no clinical payload).
"""

from __future__ import annotations

import logging

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.pending_items.export import (
    XLSX_MIME,
    build_pending_items_workbook,
    created_by_label,
    export_filename,
    format_export_datetime,
    updated_by_label,
)
from apps.pending_items.queries import (
    FIRST_UNIT_UNKNOWN,
    apply_aggregate_filters,
    apply_time_bounds,
    base_current_items,
    parse_aggregate_filters,
    resolve_current_cut,
    resolve_first_units,
    resolve_specialty,
    sort_aggregate_items,
    specialty_labels,
)
from apps.pending_items.views import private_no_store

logger = logging.getLogger(__name__)


@login_required
@private_no_store
@require_GET
def aggregate_export(request: HttpRequest) -> HttpResponse:
    """Download the filtered cut as XLSX, ignoring mode and page."""
    now = timezone.now()
    cut = resolve_current_cut()
    filters, filter_error = parse_aggregate_filters(request.GET)
    if filter_error is None:
        items = apply_time_bounds(
            list(
                apply_aggregate_filters(
                    base_current_items(cut), cut, filters
                )
            ),
            filters,
            now,
        )
    else:
        items = []
    ordered = sort_aggregate_items(items, cut, filters, now)
    first_units = resolve_first_units(
        [item.admission_id for item in ordered]
    )
    code_to_name, name_to_code = specialty_labels()
    rows: list[list[str]] = []
    for item in ordered:
        occupation = cut.occupations[item.admission_id]
        _sigla, especialidade = resolve_specialty(
            occupation.especialidade, code_to_name, name_to_code
        )
        rows.append(
            [
                occupation.prontuario,
                occupation.patient_name,
                occupation.setor,
                occupation.leito,
                first_units.get(
                    occupation.admission_id, FIRST_UNIT_UNKNOWN
                ),
                especialidade,
                item.item_type.name,
                item.description,
                item.get_status_display(),
                format_export_datetime(item.created_at),
                created_by_label(item),
                format_export_datetime(item.updated_at),
                updated_by_label(item),
            ]
        )
    payload = build_pending_items_workbook(rows)
    stamp = cut.captured_at if cut.captured_at is not None else now
    filename = export_filename(stamp)
    logger.info(
        "pending_items_export user=%s rows=%d",
        request.user.get_username(),
        len(rows),
    )
    response = HttpResponse(payload, content_type=XLSX_MIME)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response
