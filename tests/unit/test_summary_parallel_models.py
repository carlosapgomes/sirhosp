"""Tests for parallel summary pipeline models (APS-P-S1 RED phase).

Tests for pipeline_type field on SummaryRun.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

import pytest
from django.core.exceptions import ValidationError

from apps.patients.models import Admission, Patient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_patient():
    return Patient.objects.create(
        patient_source_key="P001",
        source_system="tasy",
        name="TEST PATIENT",
    )


def _make_admission(patient=None):
    if patient is None:
        patient = _make_patient()
    return Admission.objects.create(
        patient=patient,
        source_admission_key="ADM001",
        source_system="tasy",
        admission_date=datetime(2025, 1, 1, 10, 0, tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# SummaryRun.pipeline_type
# ---------------------------------------------------------------------------


@pytest.mark.django_db
class TestSummaryRunPipelineType:
    def test_default_pipeline_type_is_serial(self):
        """SummaryRun created without explicit pipeline_type defaults to "serial"."""
        from apps.summaries.models import SummaryRun

        admission = _make_admission()
        run = SummaryRun.objects.create(
            admission=admission,
            mode="generate",
            target_end_date=date(2025, 1, 10),
        )
        assert run.pipeline_type == "serial"

    def test_create_with_explicit_parallel_pipeline_type(self):
        """SummaryRun can be created with pipeline_type="parallel"."""
        from apps.summaries.models import SummaryRun

        admission = _make_admission()
        run = SummaryRun.objects.create(
            admission=admission,
            mode="generate",
            target_end_date=date(2025, 1, 10),
            pipeline_type="parallel",
        )
        assert run.pipeline_type == "parallel"

    def test_create_with_explicit_serial_pipeline_type(self):
        """SummaryRun can be created with explicit pipeline_type="serial"."""
        from apps.summaries.models import SummaryRun

        admission = _make_admission()
        run = SummaryRun.objects.create(
            admission=admission,
            mode="generate",
            target_end_date=date(2025, 1, 10),
            pipeline_type="serial",
        )
        assert run.pipeline_type == "serial"

    def test_invalid_pipeline_type_raises_error(self):
        """Invalid pipeline_type value raises ValidationError."""
        from apps.summaries.models import SummaryRun

        admission = _make_admission()
        run = SummaryRun(
            admission=admission,
            mode="generate",
            target_end_date=date(2025, 1, 10),
            pipeline_type="invalid_mode",
        )
        with pytest.raises(ValidationError):
            run.full_clean()

    def test_choices_contain_serial_and_parallel(self):
        """pipeline_type choices include only "serial" and "parallel"."""
        from apps.summaries.models import SummaryRun

        choices = dict(SummaryRun.PipelineType.choices)
        assert set(choices.keys()) == {"serial", "parallel"}
        assert choices["serial"] == "Serial"
        assert choices["parallel"] == "Parallel"

    def test_field_is_indexed(self):
        """pipeline_type field has a database index."""
        from apps.summaries.models import SummaryRun

        field = SummaryRun._meta.get_field("pipeline_type")
        assert field.db_index is True
