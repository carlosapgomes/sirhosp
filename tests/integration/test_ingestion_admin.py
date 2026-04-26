"""Integration tests for ingestion admin (Slice S5).

Tests IngestionRun changelist (list_display, filters, search) and
IngestionRunStageMetric inline visibility in detail view.
"""

from datetime import timedelta

import pytest
from django.contrib.admin.sites import AdminSite
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.ingestion.admin import (
    IngestionRunAdmin,
    IngestionRunStageMetricInline,
)
from apps.ingestion.models import (
    IngestionRun,
    IngestionRunStageMetric,
)

# ── Fixtures ────────────────────────────────────────────────────


@pytest.fixture
def admin_user(db: None) -> User:
    """Create a staff user with admin access."""
    return User.objects.create_superuser(
        username="admin",
        password="admin123",
        email="admin@example.com",
    )


@pytest.fixture
def admin_client(admin_user: User) -> Client:
    """Create a pre-authenticated admin client."""
    client = Client()
    client.login(username="admin", password="admin123")
    return client


def _make_run(**kwargs) -> IngestionRun:
    """Create an IngestionRun with sensible defaults."""
    now = timezone.now()
    defaults = {
        "status": "queued",
        "intent": "full_sync",
        "queued_at": now - timedelta(hours=1),
        "processing_started_at": None,
        "finished_at": None,
        "failure_reason": "",
        "timed_out": False,
        "parameters_json": {"patient_record": "12345"},
    }
    defaults.update(kwargs)
    return IngestionRun.objects.create(**defaults)


def _make_stage(run: IngestionRun, **kwargs) -> IngestionRunStageMetric:
    """Create an IngestionRunStageMetric for a run."""
    now = timezone.now()
    defaults = {
        "run": run,
        "stage_name": "admissions_capture",
        "started_at": now - timedelta(seconds=120),
        "finished_at": now,
        "status": "succeeded",
        "details_json": {},
    }
    defaults.update(kwargs)
    return IngestionRunStageMetric.objects.create(**defaults)


# ── AdminConfig tests (no client required) ──────────────────────


@pytest.mark.django_db
class TestIngestionRunAdminConfig:
    """Verify admin configuration attributes."""

    def test_list_display_includes_operational_columns(self):
        """list_display covers status, intent, timestamps, durations, failure info."""
        admin_instance = IngestionRunAdmin(IngestionRun, AdminSite())
        columns = admin_instance.get_list_display(None)
        for col in [
            "status",
            "intent",
            "queued_at",
            "processing_started_at",
            "finished_at",
            "queue_latency_seconds_display",
            "processing_duration_seconds_display",
            "total_duration_seconds_display",
            "timed_out",
            "failure_reason",
        ]:
            assert col in columns, f"{col} missing from list_display"

    def test_list_filter_includes_diagnostic_fields(self):
        """list_filter covers status, intent, timed_out, failure_reason."""
        admin_instance = IngestionRunAdmin(IngestionRun, AdminSite())
        filters = admin_instance.get_list_filter(None)
        filter_names = [f if isinstance(f, str) else f.__class__.__name__ for f in filters]
        for fname in ["status", "intent", "timed_out", "failure_reason"]:
            assert fname in filter_names, f"{fname} missing from list_filter"

    def test_search_fields_include_id_and_parameters(self):
        """search_fields includes id and parameters_json."""
        admin_instance = IngestionRunAdmin(IngestionRun, AdminSite())
        search = admin_instance.get_search_fields(None)
        assert "id" in search, "id missing from search_fields"
        assert "parameters_json" in search, "parameters_json missing from search_fields"

    def test_ordering_by_started_at_desc(self):
        """Default ordering is by started_at descending."""
        admin_instance = IngestionRunAdmin(IngestionRun, AdminSite())
        ordering = admin_instance.get_ordering(None)
        assert ordering == ["-started_at"], f"Expected ['-started_at'], got {ordering}"

    def test_stage_metric_fields_are_readonly(self):
        """Operational metric fields are read-only in admin."""
        admin_instance = IngestionRunAdmin(IngestionRun, AdminSite())
        readonly = admin_instance.get_readonly_fields(None)
        for field in [
            "status",
            "intent",
            "queued_at",
            "processing_started_at",
            "finished_at",
            "queue_latency_seconds_display",
            "processing_duration_seconds_display",
            "total_duration_seconds_display",
            "timed_out",
            "failure_reason",
            "events_processed",
            "events_created",
            "events_skipped",
            "events_revised",
            "admissions_seen",
            "admissions_created",
            "admissions_updated",
        ]:
            assert field in readonly, f"{field} should be read-only"

    def test_inlines_include_stage_metric(self):
        """IngestionRunAdmin has IngestionRunStageMetricInline."""
        admin_instance = IngestionRunAdmin(IngestionRun, AdminSite())
        # get_inlines requires request + obj; None obj returns base inlines
        inlines = admin_instance.get_inlines(None, obj=None)
        assert (
            IngestionRunStageMetricInline in inlines
        ), "IngestionRunStageMetricInline missing from inlines"


# ── Changelist tests ────────────────────────────────────────────


@pytest.mark.django_db
class TestIngestionRunChangelist:
    """Verify changelist renders with data and filtering."""

    def test_changelist_renders_for_authenticated_admin(
        self, admin_client: Client
    ):
        """Admin can access ingestion run changelist."""
        url = reverse("admin:ingestion_ingestionrun_changelist")
        resp = admin_client.get(url)
        assert resp.status_code == 200

    def test_changelist_requires_authentication(self):
        """Anonymous users are redirected to login."""
        client = Client()
        url = reverse("admin:ingestion_ingestionrun_changelist")
        resp = client.get(url)
        assert resp.status_code == 302

    def test_changelist_shows_runs(self, admin_client: Client):
        """Changelist displays created runs."""
        _make_run(status="succeeded")
        _make_run(status="failed", failure_reason="timeout", timed_out=True)

        url = reverse("admin:ingestion_ingestionrun_changelist")
        resp = admin_client.get(url)
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "succeeded" in content.lower()
        assert "failed" in content.lower()

    def test_filter_by_status(self, admin_client: Client):
        """Filtering by status returns only matching runs."""
        _make_run(status="succeeded")
        _make_run(status="failed")

        url = reverse("admin:ingestion_ingestionrun_changelist")
        resp = admin_client.get(url, {"status__exact": "succeeded"})
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "succeeded" in content.lower()
        # The failed run should not appear
        assert 'value="failed"' not in content

    def test_filter_by_intent(self, admin_client: Client):
        """Filtering by intent returns only matching runs."""
        _make_run(intent="full_sync", status="succeeded")
        _make_run(intent="admissions_only", status="succeeded")

        url = reverse("admin:ingestion_ingestionrun_changelist")
        resp = admin_client.get(url, {"intent__exact": "full_sync"})
        assert resp.status_code == 200
        # Should show full_sync but not admissions_only
        content = resp.content.decode()
        assert "full_sync" in content

    def test_filter_by_timed_out(self, admin_client: Client):
        """Filtering by timed_out returns only timeout runs."""
        _make_run(status="failed", timed_out=True, failure_reason="timeout")
        _make_run(status="succeeded", timed_out=False)

        url = reverse("admin:ingestion_ingestionrun_changelist")
        resp = admin_client.get(url, {"timed_out__exact": "1"})
        assert resp.status_code == 200
        content = resp.content.decode()
        # Timed-out run should be visible
        assert "timeout" in content.lower()

    def test_filter_by_failure_reason(self, admin_client: Client):
        """Filtering by failure_reason returns only matching failures."""
        _make_run(status="failed", failure_reason="timeout", timed_out=True)
        _make_run(status="failed", failure_reason="source_unavailable")
        _make_run(status="succeeded")

        url = reverse("admin:ingestion_ingestionrun_changelist")
        resp = admin_client.get(url, {"failure_reason__exact": "timeout"})
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "timeout" in content.lower()

    def test_search_by_id(self, admin_client: Client):
        """Search by run ID finds the matching run."""
        run = _make_run(status="succeeded")

        url = reverse("admin:ingestion_ingestionrun_changelist")
        resp = admin_client.get(url, {"q": str(run.pk)})
        assert resp.status_code == 200
        content = resp.content.decode()
        assert str(run.pk) in content

    def test_search_by_parameters_json(self, admin_client: Client):
        """Search by content in parameters_json finds matching runs."""
        _make_run(
            status="succeeded",
            parameters_json={"patient_record": "99999", "source": "tasy"},
        )
        _make_run(
            status="succeeded",
            parameters_json={"patient_record": "11111", "source": "other"},
        )

        url = reverse("admin:ingestion_ingestionrun_changelist")
        resp = admin_client.get(url, {"q": "99999"})
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "99999" in content


# ── Detail / Inline tests ───────────────────────────────────────


@pytest.mark.django_db
class TestIngestionRunDetail:
    """Verify detail view shows stage metrics inline."""

    def test_detail_renders_for_admin(self, admin_client: Client):
        """Admin can access ingestion run detail page."""
        run = _make_run(status="succeeded")
        url = reverse(
            "admin:ingestion_ingestionrun_change", args=[run.pk]
        )
        resp = admin_client.get(url)
        assert resp.status_code == 200

    def test_detail_shows_stage_metrics_inline(self, admin_client: Client):
        """Detail page displays persisted stage metrics inline."""
        run = _make_run(status="succeeded")
        _make_stage(
            run,
            stage_name="admissions_capture",
            status="succeeded",
        )
        _make_stage(
            run,
            stage_name="gap_planning",
            status="succeeded",
        )
        _make_stage(
            run,
            stage_name="evolution_extraction",
            status="failed",
            details_json={"error": "Extraction timeout"},
        )

        url = reverse(
            "admin:ingestion_ingestionrun_change", args=[run.pk]
        )
        resp = admin_client.get(url)
        assert resp.status_code == 200
        content = resp.content.decode()

        # Stages appear in detail
        assert "admissions_capture" in content
        assert "gap_planning" in content
        assert "evolution_extraction" in content
        # Inline shows duration column for stage metrics
        assert "Duration (s)" in content
        # Failed stage shows error context
        assert "Extraction timeout" in content

    def test_detail_with_no_stages_renders_gracefully(
        self, admin_client: Client
    ):
        """Detail page without stage metrics renders without error."""
        run = _make_run(status="queued")
        url = reverse(
            "admin:ingestion_ingestionrun_change", args=[run.pk]
        )
        resp = admin_client.get(url)
        assert resp.status_code == 200
        content = resp.content.decode()
        assert "IngestionRunStageMetric" in content or "Stage" in content


# ── Inline configuration tests ─────────────────────────────────


@pytest.mark.django_db
class TestStageMetricInline:
    """Verify inline configuration prevents accidental edits."""

    def test_inline_has_extra_zero(self):
        """Inline should not allow adding extra form rows."""
        inline = IngestionRunStageMetricInline(
            IngestionRun, AdminSite()
        )
        assert inline.extra == 0, "inline.extra should be 0 to prevent edits"

    def test_inline_readonly_fields(self):
        """Stage metric fields are read-only in the inline."""
        inline = IngestionRunStageMetricInline(
            IngestionRun, AdminSite()
        )
        readonly = inline.get_readonly_fields(None)
        for field in [
            "stage_name",
            "started_at",
            "finished_at",
            "duration_seconds",
            "status",
            "details_json",
        ]:
            assert field in readonly, f"{field} should be read-only in inline"
