"""HTTP integration coverage for RPSA-S6 reconciliation review.

Covers the permission-protected review surface (queue, case/evidence
detail and the ephemeral streamed CSV export), the safe-admin
registrations for audit/evidence models, and the identity-safety rules:
patient name and record number appear only in the authorized UI/CSV —
never in logs, never persisted to disk.

SCPED-S3: also proves the protected aggregate quality comparison on the
queue page — captured exits (``saida_em``), canonical reconciled hospital
exits and medical summaries (``alta_em``) per consecutive ``America/Bahia``
day over an explicit ``?dias=N`` period, with the same review permission,
no patient identity in the aggregate payload/logs and a strictly read-only
view.

All identities are synthetic. Authorization contract: anonymous requests
keep the login redirect; authenticated users without
``patients.review_reconciliation_cases`` get 403 with no disclosure of
case existence or identity.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import tempfile
from datetime import date, datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Any, Iterator, Sequence, cast
from zoneinfo import ZoneInfo

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import Permission, User
from django.core.paginator import Page
from django.test import Client, RequestFactory
from django.urls import reverse
from django.utils import timezone

from apps.deaths.models import DeathRecord
from apps.discharges.models import DischargeRecord
from apps.ingestion.models import IngestionRun
from apps.patients.models import (
    EXIT_DEATH,
    EXIT_HOSPITAL_DISCHARGE,
    RECONCILIATION_STATUS_ADMISSION_NOT_FOUND,
    RECONCILIATION_STATUS_AMBIGUOUS,
    RECONCILIATION_STATUS_CONFLICT,
    RECONCILIATION_STATUS_PATIENT_NOT_FOUND,
    RECONCILIATION_STATUS_PENDING,
    RECONCILIATION_STATUS_RECONCILED,
    Admission,
    Patient,
    ReconciliationEvent,
    StaleAdmissionCase,
)

TZ_LOCAL = ZoneInfo("America/Bahia")

T0 = datetime(2026, 3, 10, 9, 0, 0, tzinfo=TZ_LOCAL)

SYNTH_NAME = "MARIA SINTETICA DA REVISAO"
SYNTH_PRONT = "PRNT-REV-001"

CSV_HEADERS = ["Tipo", "Status", "Prontuario", "Nome", "Referencia", "Detalhe"]


def queue_url() -> str:
    return reverse("services_portal:reconciliation_queue")


def export_url() -> str:
    return reverse("services_portal:reconciliation_export_csv")


def case_detail_url(case: StaleAdmissionCase) -> str:
    return reverse("services_portal:reconciliation_case_detail", args=[case.pk])


def evidence_detail_url(kind: str, record: DischargeRecord | DeathRecord) -> str:
    return reverse("services_portal:reconciliation_evidence_detail", args=[kind, record.pk])


# ── Fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def client() -> Client:
    return Client()


@pytest.fixture
def reviewer(db: None) -> User:
    user = User.objects.create_user(username="revisor", password="testpass123")
    permission = Permission.objects.get(
        codename="review_reconciliation_cases",
        content_type__app_label="patients",
    )
    user.user_permissions.add(permission)
    return user


@pytest.fixture
def reviewer_client(reviewer: User, client: Client) -> Client:
    client.login(username="revisor", password="testpass123")
    return client


@pytest.fixture
def plain_client(db: None) -> Client:
    """A separate client logged in as a user WITHOUT the permission."""
    User.objects.create_user(username="comum", password="testpass123")
    client = Client()
    client.login(username="comum", password="testpass123")
    return client


@pytest.fixture
def admin_user(db: None) -> User:
    return User.objects.create_superuser(
        username="admin",
        password="admin123",
        email="admin@example.com",
    )


@pytest.fixture
def admin_client(admin_user: User, client: Client) -> Client:
    client.login(username="admin", password="admin123")
    return client


# ── Synthetic data helpers ───────────────────────────────────────


def _make_patient(pront: str, name: str = SYNTH_NAME) -> Patient:
    return Patient.objects.create(
        patient_source_key=pront,
        source_system="tasy",
        name=name,
    )


def _make_open_admission(patient: Patient, key: str) -> Admission:
    return Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=key,
        admission_date=T0 - timedelta(days=3),
    )


def _census_run(captured_at: datetime) -> IngestionRun:
    return IngestionRun.objects.create(
        status="succeeded",
        intent="census_extraction",
        queued_at=captured_at,
        finished_at=captured_at,
    )


def _make_case(
    pront: str,
    *,
    name: str = SYNTH_NAME,
    first_absence_at: datetime | None = None,
    last_absence_at: datetime | None = None,
) -> StaleAdmissionCase:
    """One open stale-admission case in eligible shape (two absences)."""
    patient = _make_patient(pront, name=name)
    admission = _make_open_admission(patient, f"ADM_{pront}")
    first_absence_at = first_absence_at or (T0 - timedelta(days=2))
    last_absence_at = last_absence_at or (T0 - timedelta(days=1))
    return StaleAdmissionCase.objects.create(
        admission=admission,
        first_absence_run=_census_run(first_absence_at),
        first_absence_at=first_absence_at,
        last_absence_run=_census_run(last_absence_at),
        last_absence_at=last_absence_at,
    )


def _resolve_case(
    case: StaleAdmissionCase,
    reason: str,
    *,
    when: datetime | None = None,
) -> StaleAdmissionCase:
    case.resolved_at = when or timezone.now()
    case.resolution_reason = reason
    case.save(update_fields=["resolved_at", "resolution_reason", "updated_at"])
    return case


def _make_discharge_evidence(
    pront: str,
    *,
    status: str = RECONCILIATION_STATUS_PENDING,
    nome: str = SYNTH_NAME,
    saida_em: datetime | None = None,
    admission: Admission | None = None,
) -> DischargeRecord:
    return DischargeRecord.objects.create(
        prontuario=pront,
        nome=nome,
        data_internacao="01/01/2026",
        saida_em=saida_em or T0,
        reconciliation_status=status,
        admission=admission,
    )


def _make_death_evidence(
    pront: str,
    *,
    status: str = RECONCILIATION_STATUS_PENDING,
    nome: str = SYNTH_NAME,
    admission: Admission | None = None,
) -> DeathRecord:
    return DeathRecord.objects.create(
        date=T0.date(),
        prontuario=pront,
        nome=nome,
        obito_em=T0,
        reconciliation_status=status,
        admission=admission,
    )


def _make_event(
    admission: Admission | None,
    source_kind: str,
    source_id: int,
    **kwargs: object,
) -> ReconciliationEvent:
    defaults: dict[str, object] = {
        "source_kind": source_kind,
        "source_id": source_id,
        "admission": admission,
        "status": RECONCILIATION_STATUS_RECONCILED,
        "exit_type": "hospital_discharge",
        "reason_code": "UNIQUE_MATCH",
        "prior_discharge_date": None,
        "new_discharge_date": T0,
    }
    defaults.update(kwargs)
    return ReconciliationEvent.objects.create(**defaults)  # type: ignore[arg-type]


# ── SCPED-S3 aggregate quality comparison helpers ────────────────
#
# The aggregate payload only carries dates and counts. Synthetic
# identity strings still appear on the protected queue rows/detail
# pages on purpose (RPSA-S6), never inside the comparison payload.

COMPARISON_TITLE = "Comparativo de qualidade da reconciliação"
COMPARISON_JSON_ID = "quality-comparison-data"
QUALITY_NAMES = ("JOSE SINTETICO QUALIDADE", "ANA SINTETICA QUALIDADE")


def _day_dt(offset_days: int, hour: int = 10, minute: int = 0) -> datetime:
    """Wall-clock datetime ``offset_days`` before today in America/Bahia."""
    day = timezone.localdate(timezone=TZ_LOCAL) - timedelta(days=offset_days)
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=TZ_LOCAL)


def _quality_captured(
    pront: str,
    when: datetime,
    *,
    status: str = RECONCILIATION_STATUS_PENDING,
    name: str = SYNTH_NAME,
) -> DischargeRecord:
    """One captured exit (``saida_em``) at ``when`` (any status)."""
    return _make_discharge_evidence(pront, status=status, saida_em=when, nome=name)


def _quality_summary(pront: str, when: datetime, *, name: str = SYNTH_NAME) -> DischargeRecord:
    """One medical summary (``alta_em``) at ``when`` without exit time."""
    return DischargeRecord.objects.create(
        prontuario=pront,
        nome=name,
        data_internacao=f"INT-{pront}",
        alta_em=when,
    )


def _quality_canonical_exit(
    pront: str,
    when: datetime,
    *,
    exit_type: str = EXIT_HOSPITAL_DISCHARGE,
    name: str = SYNTH_NAME,
    merged_into: Admission | None = None,
    reconciled: bool = True,
) -> Admission:
    """Admission closed at ``when`` with a (reconciled) audit event."""
    patient = _make_patient(pront, name=name)
    admission = Admission.objects.create(
        patient=patient,
        source_system="tasy",
        source_admission_key=f"ADM-{pront}",
        admission_date=when - timedelta(days=6),
        discharge_date=when,
    )
    if merged_into is not None:
        admission.merged_into = merged_into
        admission.save(update_fields=["merged_into"])
    if reconciled:
        _make_event(
            admission,
            "discharge_record",
            admission.pk,
            exit_type=exit_type,
            new_discharge_date=when,
        )
    else:
        _make_event(
            admission,
            "discharge_record",
            admission.pk,
            status=RECONCILIATION_STATUS_PENDING,
            reason_code="NO_CANDIDATE",
            new_discharge_date=None,
        )
    return admission


def _comparison_labels(cmp: dict[str, Any]) -> list[date]:
    """Parse the ``dd/mm/yyyy`` labels back into dates."""
    return [datetime.strptime(label, "%d/%m/%Y").date() for label in cmp["labels"]]


def _quality_json_block(content: str) -> str:
    """Slice the chart payload JSON <script> region out of the HTML."""
    marker = f'<script id="{COMPARISON_JSON_ID}"'
    start = content.index(marker)
    return content[start : content.index("</script>", start)]


# ── Anonymous behavior ───────────────────────────────────────────


@pytest.mark.django_db
class TestAnonymousAccess:
    def test_anonymous_queue_redirects_to_login_without_disclosure(
        self, client: Client
    ) -> None:
        _make_case(SYNTH_PRONT)
        response = client.get(queue_url())
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]
        assert "next=" in response.url  # type: ignore[attr-defined]
        assert SYNTH_NAME not in response.content.decode()
        assert SYNTH_PRONT not in response.content.decode()

    def test_anonymous_export_redirects_to_login(self, client: Client) -> None:
        response = client.get(export_url())
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]

    def test_anonymous_case_detail_redirects_to_login(
        self, client: Client
    ) -> None:
        case = _make_case(SYNTH_PRONT)
        response = client.get(case_detail_url(case))
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]

    def test_anonymous_evidence_detail_redirects_to_login(
        self, client: Client
    ) -> None:
        record = _make_discharge_evidence(SYNTH_PRONT)
        response = client.get(evidence_detail_url("alta", record))
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]


# ── Permission denial without disclosure ─────────────────────────


@pytest.mark.django_db
class TestPermissionDeniedWithoutDisclosure:
    def test_queue_denies_user_without_permission(
        self, plain_client: Client
    ) -> None:
        _make_case(SYNTH_PRONT)
        response = plain_client.get(queue_url())
        assert response.status_code == 403
        content = response.content.decode()
        assert SYNTH_NAME not in content
        assert SYNTH_PRONT not in content

    def test_case_detail_denies_user_without_permission(
        self, plain_client: Client
    ) -> None:
        case = _make_case(SYNTH_PRONT)
        response = plain_client.get(case_detail_url(case))
        assert response.status_code == 403
        content = response.content.decode()
        assert SYNTH_NAME not in content
        assert SYNTH_PRONT not in content

    def test_evidence_detail_denies_user_without_permission(
        self, plain_client: Client
    ) -> None:
        record = _make_discharge_evidence(SYNTH_PRONT)
        response = plain_client.get(evidence_detail_url("alta", record))
        assert response.status_code == 403
        content = response.content.decode()
        assert SYNTH_NAME not in content
        assert SYNTH_PRONT not in content

    def test_export_denies_user_without_permission(
        self, plain_client: Client
    ) -> None:
        _make_case(SYNTH_PRONT)
        response = plain_client.get(export_url())
        assert response.status_code == 403
        content = response.content.decode()
        assert SYNTH_NAME not in content
        assert SYNTH_PRONT not in content


# ── Authorized queue: union, filters, pagination ─────────────────


@pytest.mark.django_db
class TestAuthorizedQueue:
    def test_reviewer_sees_synthetic_name_and_record(
        self, reviewer_client: Client
    ) -> None:
        _make_case(SYNTH_PRONT)
        response = reviewer_client.get(queue_url())
        assert response.status_code == 200
        content = response.content.decode()
        assert SYNTH_NAME in content
        assert SYNTH_PRONT in content

    def test_queue_union_covers_cases_and_review_evidence(
        self, reviewer_client: Client
    ) -> None:
        """Open cases plus pending/ambiguous/conflict evidence form the
        queue; resolved cases and patient/admission-not-found rows do not."""
        _make_case("PRNT-U-OPEN")
        _make_discharge_evidence("PRNT-U-PEND", status=RECONCILIATION_STATUS_PENDING)
        _make_discharge_evidence("PRNT-U-AMBG", status=RECONCILIATION_STATUS_AMBIGUOUS)
        _make_death_evidence("PRNT-U-CONF", status=RECONCILIATION_STATUS_CONFLICT)
        _resolve_case(
            _make_case("PRNT-U-RES"),
            StaleAdmissionCase.ResolutionReason.REAPPEARED,
        )
        _make_discharge_evidence(
            "PRNT-U-PNF", status=RECONCILIATION_STATUS_PATIENT_NOT_FOUND
        )
        _make_death_evidence(
            "PRNT-U-ANF", status=RECONCILIATION_STATUS_ADMISSION_NOT_FOUND
        )

        content = reviewer_client.get(queue_url()).content.decode()

        for pront in ("PRNT-U-OPEN", "PRNT-U-PEND", "PRNT-U-AMBG", "PRNT-U-CONF"):
            assert pront in content
        for pront in ("PRNT-U-RES", "PRNT-U-PNF", "PRNT-U-ANF"):
            assert pront not in content

    def test_status_filter_shows_resolved_cases_on_request(
        self, reviewer_client: Client
    ) -> None:
        _resolve_case(
            _make_case("PRNT-F-RES"),
            StaleAdmissionCase.ResolutionReason.REAPPEARED,
        )

        default = reviewer_client.get(queue_url()).content.decode()
        assert "PRNT-F-RES" not in default

        filtered = reviewer_client.get(
            queue_url(), {"status": "reappeared"}
        ).content.decode()
        assert "PRNT-F-RES" in filtered

    def test_filters_narrow_status_type_and_age(
        self, reviewer_client: Client
    ) -> None:
        recent = timezone.now() - timedelta(days=2)
        conflict = _make_discharge_evidence(
            "PRNT-N-CONF",
            status=RECONCILIATION_STATUS_CONFLICT,
            saida_em=recent,
        )
        del conflict
        _make_discharge_evidence(
            "PRNT-N-OLD",
            status=RECONCILIATION_STATUS_PENDING,
            saida_em=timezone.now() - timedelta(days=40),
        )
        _make_death_evidence(
            "PRNT-N-DEATH",
            status=RECONCILIATION_STATUS_PENDING,
        )
        _make_case("PRNT-N-CASE")

        by_status = reviewer_client.get(
            queue_url(), {"status": "conflict"}
        ).content.decode()
        assert "PRNT-N-CONF" in by_status
        assert "PRNT-N-OLD" not in by_status
        assert "PRNT-N-DEATH" not in by_status
        assert "PRNT-N-CASE" not in by_status

        by_type = reviewer_client.get(queue_url(), {"tipo": "death"}).content.decode()
        assert "PRNT-N-DEATH" in by_type
        assert "PRNT-N-CONF" not in by_type
        assert "PRNT-N-CASE" not in by_type

        by_age = reviewer_client.get(queue_url(), {"idade": "7"}).content.decode()
        assert "PRNT-N-CONF" in by_age
        assert "PRNT-N-OLD" not in by_age

    def test_queue_is_paginated(self, reviewer_client: Client) -> None:
        for index in range(30):
            _make_case(f"PRNT-PG-{index:02d}")

        first = reviewer_client.get(queue_url())
        assert first.status_code == 200
        page: Page = first.context["page_obj"]  # type: ignore[assignment]
        assert page.paginator.count == 30
        assert page.paginator.num_pages == 2
        assert len(page.object_list) == 25

        second = reviewer_client.get(queue_url(), {"page": 2})
        second_page: Page = second.context["page_obj"]  # type: ignore[assignment]
        assert len(second_page.object_list) == 5

    def test_pagination_preserves_active_filters(
        self, reviewer_client: Client
    ) -> None:
        for index in range(30):
            _make_death_evidence(
                f"PRNT-PD-{index:02d}",
                status=RECONCILIATION_STATUS_PENDING,
            )
        _make_case("PRNT-PD-CASE")

        response = reviewer_client.get(queue_url(), {"tipo": "death", "page": "2"})
        assert response.status_code == 200
        page: Page = response.context["page_obj"]  # type: ignore[assignment]
        assert len(page.object_list) == 5
        content = response.content.decode()
        assert "PRNT-PD-CASE" not in content
        # The rendered pagination links carry the active filter.
        assert "tipo=death" in content


# ── Authorized detail: identity, audit trail, merged state ───────


@pytest.mark.django_db
class TestAuthorizedDetail:
    def test_case_detail_shows_identity_and_structural_audit(
        self, reviewer_client: Client
    ) -> None:
        case = _make_case(SYNTH_PRONT)
        admission = case.admission
        _make_event(
            admission,
            "discharge_record",
            101,
            status=RECONCILIATION_STATUS_PENDING,
            reason_code="NO_CANDIDATE",
        )
        _make_event(
            admission,
            "discharge_record",
            101,
            status=RECONCILIATION_STATUS_RECONCILED,
            reason_code="UNIQUE_MATCH",
            prior_discharge_date=None,
            new_discharge_date=T0,
        )

        response = reviewer_client.get(case_detail_url(case))

        assert response.status_code == 200
        content = response.content.decode()
        assert SYNTH_NAME in content
        assert SYNTH_PRONT in content
        assert "UNIQUE_MATCH" in content
        assert "NO_CANDIDATE" in content
        assert str(admission.source_admission_key) in content
        events = response.context["events"]  # type: ignore[index]
        assert len(events) == 2

    def test_case_detail_shows_merged_and_canonical_state(
        self, reviewer_client: Client
    ) -> None:
        patient = _make_patient("PRNT-M-CASE")
        canonical = _make_open_admission(patient, "ADM-CANONICAL")
        merged = _make_open_admission(patient, "ADM-DUPLICATE")
        merged.merged_into = canonical
        merged.save(update_fields=["merged_into"])
        case_on_merged = StaleAdmissionCase.objects.create(
            admission=merged,
            first_absence_run=_census_run(T0 - timedelta(days=2)),
            first_absence_at=T0 - timedelta(days=2),
            last_absence_run=_census_run(T0 - timedelta(days=1)),
            last_absence_at=T0 - timedelta(days=1),
        )

        response = reviewer_client.get(case_detail_url(case_on_merged))

        assert response.status_code == 200
        content = response.content.decode()
        assert "ADM-CANONICAL" in content
        assert "Mesclada" in content

    def test_canonical_detail_lists_merged_duplicates(
        self, reviewer_client: Client
    ) -> None:
        patient = _make_patient("PRNT-M-CAN")
        canonical = _make_open_admission(patient, "ADM-CANON-2")
        merged = _make_open_admission(patient, "ADM-DUP-2")
        merged.merged_into = canonical
        merged.save(update_fields=["merged_into"])
        case_on_canonical = StaleAdmissionCase.objects.create(
            admission=canonical,
            first_absence_run=_census_run(T0 - timedelta(days=2)),
            first_absence_at=T0 - timedelta(days=2),
            last_absence_run=_census_run(T0 - timedelta(days=1)),
            last_absence_at=T0 - timedelta(days=1),
        )

        response = reviewer_client.get(case_detail_url(case_on_canonical))

        assert response.status_code == 200
        content = response.content.decode()
        assert "ADM-DUP-2" in content

    def test_discharge_evidence_detail_shows_linkage_and_events(
        self, reviewer_client: Client
    ) -> None:
        patient = _make_patient("PRNT-EV-ALTA")
        admission = _make_open_admission(patient, "ADM-EV-ALTA")
        record = _make_discharge_evidence(
            "PRNT-EV-ALTA",
            status=RECONCILIATION_STATUS_RECONCILED,
            admission=admission,
        )
        _make_event(
            admission,
            "discharge_record",
            record.pk,
            status=RECONCILIATION_STATUS_RECONCILED,
            reason_code="UNIQUE_MATCH",
        )
        # Unrelated event (different evidence row) must not leak in.
        _make_event(admission, "discharge_record", 999999)

        response = reviewer_client.get(evidence_detail_url("alta", record))

        assert response.status_code == 200
        content = response.content.decode()
        assert SYNTH_NAME in content
        assert "PRNT-EV-ALTA" in content
        assert "UNIQUE_MATCH" in content
        events = response.context["events"]  # type: ignore[index]
        assert len(events) == 1

    def test_death_evidence_detail_shows_linkage_and_events(
        self, reviewer_client: Client
    ) -> None:
        patient = _make_patient("PRNT-EV-OBITO")
        admission = _make_open_admission(patient, "ADM-EV-OBITO")
        record = _make_death_evidence(
            "PRNT-EV-OBITO",
            status=RECONCILIATION_STATUS_CONFLICT,
            admission=admission,
        )
        _make_event(
            admission,
            "death_record",
            record.pk,
            status=RECONCILIATION_STATUS_CONFLICT,
            reason_code="CONTRADICTORY_IDS",
            exit_type="death",
        )

        response = reviewer_client.get(evidence_detail_url("obito", record))

        assert response.status_code == 200
        content = response.content.decode()
        assert "PRNT-EV-OBITO" in content
        assert "CONTRADICTORY_IDS" in content
        events = response.context["events"]  # type: ignore[index]
        assert len(events) == 1


# ── Ephemeral streamed CSV export ────────────────────────────────


def _consume(response: Any) -> str:
    """Drain a streaming response body (test client response)."""
    stream = cast("Iterator[bytes]", response.streaming_content)
    return b"".join(stream).decode()


@pytest.mark.django_db
class TestEphemeralCsvExport:
    def test_csv_requires_same_permission(
        self, client: Client, plain_client: Client
    ) -> None:
        _make_case(SYNTH_PRONT)
        assert client.get(export_url()).status_code == 302
        assert plain_client.get(export_url()).status_code == 403

    def test_csv_streams_filtered_rows_with_proper_escaping(
        self, reviewer_client: Client
    ) -> None:
        tricky_name = 'MARIA "COMMA, TESTE'
        _make_case("PRNT-CSV-1", name=tricky_name)
        _make_discharge_evidence("PRNT-CSV-2", nome=SYNTH_NAME)

        response = reviewer_client.get(export_url())

        assert response.status_code == 200
        assert response.streaming
        assert response["Content-Type"] == "text/csv"
        assert "attachment" in response["Content-Disposition"]
        assert ".csv" in response["Content-Disposition"]
        assert "no-cache" in response["Cache-Control"]

        rows = list(csv.reader(io.StringIO(_consume(response))))
        assert rows[0] == CSV_HEADERS
        data = rows[1:]
        assert len(data) == 2
        by_pront = {row[2]: row for row in data}
        assert by_pront["PRNT-CSV-1"][3] == tricky_name
        assert by_pront["PRNT-CSV-2"][3] == SYNTH_NAME

    def test_csv_writes_no_file_to_disk(self, reviewer_client: Client) -> None:
        _make_case("PRNT-CSV-3")
        temp_dir = tempfile.gettempdir()
        before = {
            path for path in os.listdir(temp_dir) if "reconciliacao" in path
        }

        response = reviewer_client.get(export_url())
        _consume(response)

        after = {
            path for path in os.listdir(temp_dir) if "reconciliacao" in path
        }
        assert after == before
        assert not after

    def test_export_logs_aggregate_outcome_only(
        self, reviewer_client: Client, caplog: pytest.LogCaptureFixture
    ) -> None:
        _make_case("PRNT-CSV-4")
        with caplog.at_level(logging.INFO, logger="apps.services_portal.views"):
            response = reviewer_client.get(export_url(), {"status": "conflict"})
            _consume(response)

        assert "reconciliation export" in caplog.text
        assert SYNTH_NAME not in caplog.text
        assert "PRNT-CSV-4" not in caplog.text


# ── View logs never carry identity ───────────────────────────────


@pytest.mark.django_db
class TestViewLogsCarryNoIdentity:
    def test_queue_and_detail_logs_have_no_identity(
        self, reviewer_client: Client, caplog: pytest.LogCaptureFixture
    ) -> None:
        case = _make_case("PRNT-LOG-1")
        record = _make_discharge_evidence("PRNT-LOG-2")
        with caplog.at_level(logging.DEBUG):
            reviewer_client.get(queue_url())
            reviewer_client.get(case_detail_url(case))
            reviewer_client.get(evidence_detail_url("alta", record))

        assert SYNTH_NAME not in caplog.text
        assert "PRNT-LOG-1" not in caplog.text
        assert "PRNT-LOG-2" not in caplog.text


# ── SCPED-S3 protected aggregate quality comparison ─────────────


@pytest.mark.django_db
class TestProtectedQualityComparison:
    """Aggregate quality comparison on the protected reconciliation page.

    R1: only ``patients.review_reconciliation_cases`` users reach the
    comparison (same permission as the queue).
    R2: the payload carries per-day counts of captured exits
    (``saida_em``), canonical reconciled hospital exits and medical
    summaries (``alta_em``) over the explicit period.
    R3: every date is an ``America/Bahia`` local day on a consecutive
    axis over the explicit ``?dias=N`` window.
    R4: the payload and chart JSON embed no name, record number,
    admission key or clinical text; page logs stay aggregate-only.
    R5: reading the comparison never mutates rules, statuses, events or
    admissions.
    """

    # ── R1: permission ──────────────────────────────────────────

    def test_anonymous_user_never_reaches_the_comparison(self, client: Client) -> None:
        response = client.get(queue_url())
        assert response.status_code == 302
        assert response.url.startswith("/login/")  # type: ignore[attr-defined]
        assert COMPARISON_TITLE not in response.content.decode()

    def test_user_without_permission_is_denied_without_disclosure(
        self, plain_client: Client
    ) -> None:
        response = plain_client.get(queue_url())
        assert response.status_code == 403
        content = response.content.decode()
        assert COMPARISON_TITLE not in content
        assert COMPARISON_JSON_ID not in content
        assert SYNTH_NAME not in content

    def test_reviewer_sees_the_comparison_on_the_queue_page(
        self, reviewer_client: Client
    ) -> None:
        response = reviewer_client.get(queue_url())
        assert response.status_code == 200
        assert "quality_comparison" in response.context  # type: ignore[operator]
        content = response.content.decode()
        assert COMPARISON_TITLE in content
        assert COMPARISON_JSON_ID in content

    # ── R2/R3: aggregate series over a consecutive Bahia axis ────

    def test_payload_counts_the_three_series_per_day_in_the_window(
        self, reviewer_client: Client
    ) -> None:
        """Per-day captured/reconciled/summary counts over ?dias=5."""
        d = _day_dt(2, 9, 0)  # offset 2 -> label index 3
        e = _day_dt(1, 10, 0)  # offset 1 -> label index 4
        old = _day_dt(6, 10, 0)  # outside a 5-day window

        # Captured exits on D: pending and ambiguous still count.
        _quality_captured("QLT-C1", d, status=RECONCILIATION_STATUS_PENDING)
        _quality_captured("QLT-C2", d, status=RECONCILIATION_STATUS_AMBIGUOUS)
        # Captured exit on E with conflict status.
        _quality_captured("QLT-C3", e, status=RECONCILIATION_STATUS_CONFLICT)
        # Captured exit outside the window must stay out.
        _quality_captured("QLT-C4", old)

        # Canonical reconciled hospital exits: R1 and R5 on D only. Death,
        # unresolved and merged duplicates never join this series.
        _quality_canonical_exit("QLT-R1", d)
        _quality_canonical_exit("QLT-R2", e, exit_type=EXIT_DEATH)
        _quality_canonical_exit("QLT-R3", old)
        _quality_canonical_exit("QLT-R4", d, reconciled=False)
        canonical = _quality_canonical_exit("QLT-R5", d)
        merged = _quality_canonical_exit("QLT-R6", d)
        merged.merged_into = canonical
        merged.save(update_fields=["merged_into"])

        # Medical summaries: one on D, one outside the window.
        _quality_summary("QLT-S1", d)
        _quality_summary("QLT-S2", old)

        response = reviewer_client.get(queue_url(), {"dias": "5"})
        assert response.status_code == 200
        cmp = response.context["quality_comparison"]  # type: ignore[index]

        assert cmp["dias"] == 5
        captured = cmp["captured_counts"]
        reconciled = cmp["reconciled_counts"]
        summaries = cmp["summary_counts"]
        assert captured == [0, 0, 0, 2, 1]
        assert reconciled == [0, 0, 0, 2, 0]
        assert summaries == [0, 0, 0, 1, 0]
        assert cmp["has_data"] is True

    def test_consecutive_bahia_axis_and_zero_fill(self, reviewer_client: Client) -> None:
        """The payload axis is exactly the consecutive explicit window."""
        response = reviewer_client.get(queue_url(), {"dias": "5"})
        cmp = response.context["quality_comparison"]  # type: ignore[index]
        start = date.fromisoformat(cmp["period_start"])
        end = date.fromisoformat(cmp["period_end"])
        assert (end - start).days + 1 == 5
        expected = [
            (start + timedelta(days=i)).strftime("%d/%m/%Y")
            for i in range(5)
        ]
        assert cmp["labels"] == expected
        # Empty days inside the window stay on the axis as zero.
        assert cmp["captured_counts"] == [0] * 5
        assert cmp["has_data"] is False

    def test_default_window_is_90_consecutive_bahia_days_ending_yesterday(
        self, reviewer_client: Client
    ) -> None:
        response = reviewer_client.get(queue_url())
        cmp = response.context["quality_comparison"]  # type: ignore[index]
        assert cmp["dias"] == 90
        start = date.fromisoformat(cmp["period_start"])
        end = date.fromisoformat(cmp["period_end"])
        assert (end - start).days + 1 == 90
        assert cmp["labels"] == [
            (start + timedelta(days=i)).strftime("%d/%m/%Y")
            for i in range(90)
        ]
        assert cmp["period_end"] == (end).isoformat()

    def test_dias_above_365_falls_back_to_90(self, reviewer_client: Client) -> None:
        """The documented 365-day cap is enforced: over-cap values fall
        back to the 90-day default instead of building an unbounded axis.
        """
        response = reviewer_client.get(queue_url(), {"dias": "400"})
        assert response.status_code == 200
        cmp = response.context["quality_comparison"]  # type: ignore[index]
        assert cmp["dias"] == 90
        start = date.fromisoformat(cmp["period_start"])
        end = date.fromisoformat(cmp["period_end"])
        assert (end - start).days + 1 == 90
        assert len(cmp["labels"]) == 90
        assert len(cmp["captured_counts"]) == 90
        assert len(cmp["reconciled_counts"]) == 90
        assert len(cmp["summary_counts"]) == 90

    def test_dias_365_is_the_accepted_maximum(self, reviewer_client: Client) -> None:
        """?dias=365 remains the accepted upper boundary."""
        response = reviewer_client.get(queue_url(), {"dias": "365"})
        assert response.status_code == 200
        cmp = response.context["quality_comparison"]  # type: ignore[index]
        assert cmp["dias"] == 365
        start = date.fromisoformat(cmp["period_start"])
        end = date.fromisoformat(cmp["period_end"])
        assert (end - start).days + 1 == 365
        assert len(cmp["labels"]) == 365

    def test_cross_midnight_events_use_the_bahia_local_day(
        self, reviewer_client: Client
    ) -> None:
        """02:00 UTC == 23:00 America/Bahia of the previous local day."""
        yesterday = timezone.localdate(timezone=TZ_LOCAL) - timedelta(days=1)
        utc_today = yesterday + timedelta(days=1)
        stored_utc = datetime(
            utc_today.year, utc_today.month, utc_today.day, 2, 0,
            tzinfo=dt_timezone.utc,
        )
        _quality_captured("QLT-TZ1", stored_utc, status=RECONCILIATION_STATUS_PENDING)
        _quality_canonical_exit("QLT-TZ2", stored_utc)
        _quality_summary(
            "QLT-TZ3",
            datetime(
                yesterday.year, yesterday.month, yesterday.day, 23, 0,
                tzinfo=TZ_LOCAL,
            ),
        )

        response = reviewer_client.get(queue_url(), {"dias": "3"})
        cmp = response.context["quality_comparison"]  # type: ignore[index]
        labels = _comparison_labels(cmp)
        assert labels == [yesterday - timedelta(days=2), yesterday - timedelta(days=1), yesterday]
        yesterday_index = labels.index(yesterday)
        assert cmp["captured_counts"][yesterday_index] == 1
        assert cmp["reconciled_counts"][yesterday_index] == 1
        assert cmp["summary_counts"][yesterday_index] == 1
        assert cmp["captured_counts"][:yesterday_index] == [0, 0]

    # ── R4: aggregate-only, no identity anywhere new ─────────────

    def test_comparison_payload_and_chart_json_carry_no_identity(
        self, reviewer_client: Client
    ) -> None:
        when = _day_dt(1, 11, 30)
        _quality_captured(
            SYNTH_PRONT, when, name=QUALITY_NAMES[0],
            status=RECONCILIATION_STATUS_CONFLICT,
        )
        _quality_summary("QLT-PRV-1", when, name=QUALITY_NAMES[1])
        _quality_canonical_exit("QLT-PRV-2", when, name=QUALITY_NAMES[0])

        response = reviewer_client.get(queue_url(), {"dias": "3"})
        assert response.status_code == 200
        cmp = response.context["quality_comparison"]  # type: ignore[index]
        assert set(cmp) == {
            "labels",
            "captured_counts",
            "reconciled_counts",
            "summary_counts",
            "has_data",
            "dias",
            "period_start",
            "period_end",
        }
        assert all(
            "PRNT" not in label and "ADM" not in label
            for label in cmp["labels"]
        )
        for value in cmp["captured_counts"] + cmp["reconciled_counts"] + cmp["summary_counts"]:
            assert isinstance(value, int)

        content = response.content.decode()
        json_block = _quality_json_block(content)
        for token in (SYNTH_NAME, SYNTH_PRONT, *QUALITY_NAMES, "ADM-", "01/01/2026"):
            assert token not in json_block

    def test_comparison_page_logs_carry_no_identity(
        self, reviewer_client: Client, caplog: pytest.LogCaptureFixture
    ) -> None:
        when = _day_dt(1, 11, 30)
        _quality_captured(SYNTH_PRONT, when, name=QUALITY_NAMES[0])
        _quality_summary("QLT-LOG-1", when, name=QUALITY_NAMES[1])
        _quality_canonical_exit("QLT-LOG-2", when, name=QUALITY_NAMES[0])

        with caplog.at_level(logging.DEBUG):
            reviewer_client.get(queue_url(), {"dias": "3"})

        for token in (SYNTH_NAME, SYNTH_PRONT, *QUALITY_NAMES, "ADM-"):
            assert token not in caplog.text

    # ── R5: strictly read-only ───────────────────────────────────

    @staticmethod
    def _domain_snapshot() -> dict[str, object]:
        return {
            "discharges": list(
                DischargeRecord.objects.values_list(
                    "pk", "reconciliation_status", "reconciled_at"
                ).order_by("pk")
            ),
            "admissions": list(
                Admission.all_objects.values_list(
                    "pk", "discharge_date", "merged_into_id"
                ).order_by("pk")
            ),
            "events": list(
                ReconciliationEvent.objects.values_list(
                    "pk", "status", "exit_type", "new_discharge_date"
                ).order_by("pk")
            ),
            "cases": list(
                StaleAdmissionCase.objects.values_list(
                    "pk", "resolved_at", "resolution_reason"
                ).order_by("pk")
            ),
        }

    def test_reading_the_comparison_never_mutates_domain_state(
        self, reviewer_client: Client
    ) -> None:
        when = _day_dt(1, 11, 30)
        _make_case("QLT-RO-1")
        _quality_captured(SYNTH_PRONT, when, status=RECONCILIATION_STATUS_PENDING)
        _quality_summary("QLT-RO-2", when)
        _quality_canonical_exit("QLT-RO-3", when, reconciled=False)

        before = self._domain_snapshot()
        for _ in range(2):
            response = reviewer_client.get(queue_url(), {"dias": "3"})
            assert response.status_code == 200
        after = self._domain_snapshot()
        assert after == before


# ── Safe admin registrations (audit + evidence, read-only) ───────


@pytest.mark.django_db
class TestReviewAdmins:
    def test_new_model_admins_are_registered(self) -> None:
        from django.contrib import admin

        for model in (ReconciliationEvent, StaleAdmissionCase, DischargeRecord, DeathRecord):
            assert admin.site.is_registered(model)

    def test_audit_and_case_admins_are_read_only(self) -> None:
        from apps.patients.admin import (
            ReconciliationEventAdmin,
            StaleAdmissionCaseAdmin,
        )

        for model_admin_class, model in (
            (ReconciliationEventAdmin, ReconciliationEvent),
            (StaleAdmissionCaseAdmin, StaleAdmissionCase),
        ):
            admin_instance = model_admin_class(model, AdminSite())
            request = RequestFactory().get("/")
            assert admin_instance.has_add_permission(request) is False
            assert admin_instance.has_change_permission(request) is False
            assert admin_instance.has_delete_permission(request) is False
            assert (
                admin_instance.has_delete_permission(request, obj=model())
                is False
            )

    def test_discharge_and_death_admins_are_read_only(self) -> None:
        from apps.deaths.admin import DeathRecordAdmin
        from apps.discharges.admin import DischargeRecordAdmin

        for model_admin_class, model in (
            (DischargeRecordAdmin, DischargeRecord),
            (DeathRecordAdmin, DeathRecord),
        ):
            admin_instance = model_admin_class(model, AdminSite())
            request = RequestFactory().get("/")
            assert admin_instance.has_add_permission(request) is False
            assert admin_instance.has_change_permission(request) is False
            assert admin_instance.has_delete_permission(request) is False

    def test_evidence_admin_changelists_render_for_staff(
        self, admin_client: Client
    ) -> None:
        changelist_urls: Sequence[str] = (
            "/admin/patients/reconciliationevent/",
            "/admin/patients/staleadmissioncase/",
            "/admin/discharges/dischargerecord/",
            "/admin/deaths/deathrecord/",
        )
        for url in changelist_urls:
            response = admin_client.get(url)
            assert response.status_code == 200, url

    def test_audit_and_case_admins_reject_add_and_change(
        self, admin_client: Client
    ) -> None:
        case = _make_case(SYNTH_PRONT)
        assert (
            admin_client.get("/admin/patients/staleadmissioncase/add/").status_code
            == 403
        )
        assert (
            admin_client.get("/admin/patients/reconciliationevent/add/").status_code
            == 403
        )
        # Audit rows may be VIEWED (view-only mode) but not edited: the
        # change page renders without change permission and without any
        # save/delete action buttons.
        change = admin_client.get(
            f"/admin/patients/staleadmissioncase/{case.pk}/change/"
        )
        assert change.status_code == 200
        assert change.context["has_change_permission"] is False
        assert change.context["has_delete_permission"] is False
        assert "_save" not in change.content.decode()

    def test_evidence_admin_shows_linkage_columns(
        self, admin_client: Client
    ) -> None:
        record = _make_discharge_evidence(
            SYNTH_PRONT, status=RECONCILIATION_STATUS_PENDING
        )
        response = admin_client.get("/admin/discharges/dischargerecord/")
        assert response.status_code == 200
        assert SYNTH_PRONT in response.content.decode()
        del record
