"""Unit evidence for slice UPA-001 R5: photo resolved by the latest eligible run.

The photo is the census cycle of the latest ``census_extraction`` run with
``status = succeeded`` holding at least one snapshot row, ordered by the
minimum row ``captured_at`` descending and then by run primary key descending.
``finished_at`` never decides, ``running``/``failed``/rowless runs never
surface and legacy rows without a run never surface.

Synthetic values only.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from apps.census.models import BedStatus, CensusSnapshot
from apps.ingestion.models import IngestionRun
from apps.upstream_api.photo import build_current_photo

BAHIA = ZoneInfo("America/Bahia")
BASE_CAPTURED_AT = datetime(2026, 9, 6, 8, 0, tzinfo=BAHIA)

pytestmark = pytest.mark.django_db


def _run(
    *,
    status: str = "succeeded",
    intent: str = "census_extraction",
    finished_at: datetime | None = None,
) -> IngestionRun:
    return IngestionRun.objects.create(status=status, intent=intent, finished_at=finished_at)


def _row(
    run: IngestionRun | None,
    captured_at: datetime,
    *,
    prontuario: str = "0000001",
    nome: str = "PACIENTE EXEMPLO",
    setor: str = "SETOR EXEMPLO",
    setor_codigo: str = "640",
    leito: str = "I10CA",
) -> CensusSnapshot:
    return CensusSnapshot.objects.create(
        ingestion_run=run,
        captured_at=captured_at,
        setor=setor,
        setor_codigo=setor_codigo,
        leito=leito,
        prontuario=prontuario,
        nome=nome,
        bed_status=BedStatus.OCCUPIED,
    )


def _photo_prontuarios() -> set[str]:
    photo = build_current_photo()
    assert photo is not None
    return {row.prontuario for row in photo[1]}


def test_no_eligible_run_yields_no_photo():
    assert build_current_photo() is None

    _run(status="running")
    _run(status="queued")
    _run(status="failed", finished_at=BASE_CAPTURED_AT)

    assert build_current_photo() is None


def test_newest_capture_wins():
    older = _run(finished_at=BASE_CAPTURED_AT + timedelta(hours=1))
    _row(older, BASE_CAPTURED_AT, prontuario="0000001")
    newer = _run(finished_at=BASE_CAPTURED_AT + timedelta(hours=7))
    _row(newer, BASE_CAPTURED_AT + timedelta(hours=6), prontuario="0000002")

    photo = build_current_photo()

    assert photo is not None
    assert photo[0] == BASE_CAPTURED_AT + timedelta(hours=6)
    assert {row.prontuario for row in photo[1]} == {"0000002"}


def test_running_and_failed_cycles_never_surface():
    succeeded = _run(finished_at=BASE_CAPTURED_AT + timedelta(hours=1))
    _row(succeeded, BASE_CAPTURED_AT, prontuario="0000001")
    running = _run(status="running")
    _row(running, BASE_CAPTURED_AT + timedelta(hours=6), prontuario="0000002")
    failed = _run(status="failed", finished_at=BASE_CAPTURED_AT + timedelta(hours=8))
    _row(failed, BASE_CAPTURED_AT + timedelta(hours=7), prontuario="0000003")

    photo = build_current_photo()

    assert photo is not None
    assert photo[0] == BASE_CAPTURED_AT
    assert {row.prontuario for row in photo[1]} == {"0000001"}


def test_succeeded_run_without_rows_is_not_eligible():
    older = _run()
    _row(older, BASE_CAPTURED_AT, prontuario="0000001")
    _run(finished_at=BASE_CAPTURED_AT + timedelta(hours=12))

    assert _photo_prontuarios() == {"0000001"}


def test_rows_without_a_run_never_surface():
    eligible = _run()
    _row(eligible, BASE_CAPTURED_AT, prontuario="0000001")
    _row(None, BASE_CAPTURED_AT + timedelta(hours=6), prontuario="0000002")

    assert _photo_prontuarios() == {"0000001"}


def test_capture_order_wins_over_finish_order():
    captured_earlier = _run(finished_at=BASE_CAPTURED_AT + timedelta(hours=10))
    _row(captured_earlier, BASE_CAPTURED_AT, prontuario="0000001")
    captured_later = _run(finished_at=BASE_CAPTURED_AT + timedelta(hours=7))
    _row(captured_later, BASE_CAPTURED_AT + timedelta(hours=6), prontuario="0000002")

    assert _photo_prontuarios() == {"0000002"}


def test_shared_captured_at_resolves_by_run_primary_key_without_mixing_rows():
    first = _run()
    _row(first, BASE_CAPTURED_AT, prontuario="0000001")
    second = _run()
    _row(second, BASE_CAPTURED_AT, prontuario="0000002")
    assert second.pk > first.pk

    photo = build_current_photo()

    assert photo is not None
    assert [row.ingestion_run_id for row in photo[1]] == [second.pk]
    assert [row.prontuario for row in photo[1]] == ["0000002"]


def test_non_census_intents_are_not_eligible():
    census = _run()
    _row(census, BASE_CAPTURED_AT, prontuario="0000001")
    other_intent = _run(intent="admissions_only")
    _row(other_intent, BASE_CAPTURED_AT + timedelta(hours=6), prontuario="0000002")

    assert _photo_prontuarios() == {"0000001"}
