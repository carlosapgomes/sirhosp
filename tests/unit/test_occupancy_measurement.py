"""SCOH-S2 tests for immutable run-scoped occupancy measurements."""

from __future__ import annotations

import importlib
import importlib.util
import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.census.capacity_catalog import validate_catalog_document
from apps.census.models import (
    BedStatus,
    CalculationPolicy,
    CapacityCatalogVersion,
    CapacityGroupDefinition,
    CapacitySectorMembership,
    CensusSnapshot,
)
from apps.ingestion.models import IngestionRun

INITIAL_CATALOG = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "census"
    / "data"
    / "initial_sector_capacity_catalog.json"
)
CORRECTED_CATALOG = (
    Path(__file__).resolve().parents[2]
    / "apps"
    / "census"
    / "data"
    / "corrected_sector_capacity_catalog.json"
)


def _domain():
    if importlib.util.find_spec("apps.census.occupancy") is None:
        pytest.fail("occupancy measurement behavior is missing")
    return importlib.import_module("apps.census.occupancy")


def _measurement_models():
    models_module = importlib.import_module("apps.census.models")
    parent = getattr(models_module, "OccupancyMeasurement", None)
    child = getattr(models_module, "OccupancyGroupMeasurement", None)
    if parent is None or child is None:
        pytest.fail("occupancy measurement schema is missing")
    return parent, child


def _at(local_date: date, hour: int = 12) -> datetime:
    return timezone.make_aware(
        datetime.combine(local_date, time(hour=hour)),
        timezone.get_current_timezone(),
    )


def _run(*, intent: str = "census_extraction", status: str = "succeeded"):
    return IngestionRun.objects.create(intent=intent, status=status)


def _snapshot(
    run: IngestionRun,
    *,
    captured_at: datetime,
    code: str,
    sector: str,
    status: str = BedStatus.EMPTY,
    index: int = 0,
    patient_marker: str = "",
    age_band: str | None = None,
    bed: str | None = None,
) -> CensusSnapshot:
    return CensusSnapshot.objects.create(
        ingestion_run=run,
        captured_at=captured_at,
        setor_codigo=code,
        setor=sector,
        leito=(
            bed
            if bed is not None
            else f"BED-{code or 'BLANK'}-{index:03d}"
        ),
        prontuario=patient_marker if status == BedStatus.OCCUPIED else "",
        nome=(
            f"Synthetic Patient {patient_marker}"
            if status == BedStatus.OCCUPIED
            else status.upper()
        ),
        especialidade="SYN",
        bed_status=status,
        age_band=(
            age_band
            if age_band is not None
            else ("not_applicable" if status != BedStatus.OCCUPIED else "unknown")
        ),
    )


def _catalog(
    effective_from: date,
    groups: list[dict],
    *,
    algorithm_version: str | None = None,
) -> CapacityCatalogVersion:
    catalog = CapacityCatalogVersion.objects.create(
        effective_from=effective_from,
        source_reference="synthetic occupancy test catalog",
        source_sha256=(f"{effective_from:%Y%m%d}" + "a" * 64)[:64],
        schema_version="1.0",
        algorithm_version=algorithm_version,
    )
    for raw_group in groups:
        group = CapacityGroupDefinition.objects.create(
            catalog=catalog,
            stable_key=raw_group["stable_key"],
            display_name=raw_group.get("display_name", raw_group["stable_key"]),
            official_capacity=raw_group.get("capacity"),
            calculation_policy=raw_group["policy"],
        )
        for member in raw_group["members"]:
            code = member[0]
            configured_name = member[1]
            selector = member[2] if len(member) > 2 else "all"
            CapacitySectorMembership.objects.create(
                catalog=catalog,
                group=group,
                source_code=code,
                configured_source_name=configured_name,
                age_selector=selector,
            )
    return catalog


def _standard_group(
    *,
    key: str = "A",
    capacity: int = 10,
    members: tuple[tuple[str, ...], ...] = (("100", "Sector A"),),
) -> dict:
    return {
        "stable_key": key,
        "display_name": f"Group {key}",
        "capacity": capacity,
        "policy": CalculationPolicy.STANDARD,
        "members": members,
    }


def _materialize(run_id: int):
    return _domain().materialize_occupancy_measurement(run_id=run_id)


@pytest.mark.django_db
class TestMaterializationBoundary:
    def test_missing_behavior_is_a_real_assertion_red(self):
        assert importlib.util.find_spec("apps.census.occupancy") is not None, (
            "run-scoped occupancy materialization is not implemented"
        )

    def test_pre_activation_run_creates_no_measurement(self):
        parent_model, _ = _measurement_models()
        capture_date = timezone.localdate()
        _catalog(capture_date + timedelta(days=1), [_standard_group()])
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="100",
            sector="Sector A",
        )

        result = _materialize(run.pk)

        assert result.status == "pre_activation"
        assert result.measurement is None
        assert parent_model.objects.count() == 0

    def test_applicable_run_creates_parent_and_all_catalog_children(self):
        parent_model, child_model = _measurement_models()
        capture_date = timezone.localdate()
        catalog = _catalog(
            capture_date,
            [
                _standard_group(),
                {
                    "stable_key": "PENDING",
                    "display_name": "Pending",
                    "capacity": 32,
                    "policy": CalculationPolicy.LINKED_SLOTS_PENDING,
                    "members": (("200", "Pending Sector"),),
                },
            ],
        )
        run = _run()
        captured_at = _at(capture_date)
        _snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-001",
        )

        result = _materialize(run.pk)

        assert result.status == "created"
        assert result.created is True
        measurement = result.measurement
        assert measurement.census_run_id == run.pk
        assert measurement.catalog_id == catalog.pk
        assert measurement.captured_at == captured_at
        assert measurement.local_date == capture_date
        assert measurement.algorithm_version == "occupancy-v1"
        assert parent_model.objects.count() == 1
        assert child_model.objects.filter(measurement=measurement).count() == 2

    def test_repeated_run_returns_same_immutable_values_without_recalculation(self):
        _, child_model = _measurement_models()
        capture_date = timezone.localdate()
        _catalog(capture_date, [_standard_group()])
        run = _run()
        captured_at = _at(capture_date)
        _snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-001",
        )
        first = _materialize(run.pk)
        child = child_model.objects.get(measurement=first.measurement)
        original = (
            child.occupied_count,
            child.occupancy_percentage,
            child.status_counts_json,
            child.components_json,
        )
        _snapshot(
            run,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=2,
            patient_marker="SYN-002",
        )

        second = _materialize(run.pk)
        child.refresh_from_db()

        assert second.status == "existing"
        assert second.created is False
        assert second.measurement.pk == first.measurement.pk
        assert (
            child.occupied_count,
            child.occupancy_percentage,
            child.status_counts_json,
            child.components_json,
        ) == original

    def test_later_catalog_cannot_change_earlier_measurement(self):
        _, child_model = _measurement_models()
        capture_date = timezone.localdate()
        _catalog(capture_date, [_standard_group(capacity=10)])
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-001",
        )
        first = _materialize(run.pk)
        _catalog(capture_date + timedelta(days=1), [_standard_group(capacity=99)])

        second = _materialize(run.pk)
        child = child_model.objects.get(measurement=second.measurement)

        assert second.measurement.pk == first.measurement.pk
        assert child.official_capacity == 10

    def test_rejects_non_census_run_and_run_without_snapshots(self):
        domain = _domain()
        wrong = _run(intent="admissions_only")
        empty = _run()
        with pytest.raises(domain.OccupancyMaterializationError):
            domain.materialize_occupancy_measurement(run_id=wrong.pk)
        with pytest.raises(domain.OccupancyMaterializationError):
            domain.materialize_occupancy_measurement(run_id=empty.pk)

    def test_rows_from_another_run_are_never_scanned(self):
        capture_date = timezone.localdate()
        _catalog(capture_date, [_standard_group()])
        selected = _run()
        other = _run()
        captured_at = _at(capture_date)
        _snapshot(
            selected,
            captured_at=captured_at,
            code="100",
            sector="Sector A",
        )
        _snapshot(
            other,
            captured_at=captured_at,
            code="999",
            sector="Other Run Sector",
            status=BedStatus.OCCUPIED,
            patient_marker="OTHER-RUN",
        )

        result = _materialize(selected.pk)

        assert result.measurement.observed_sector_count == 1
        assert result.measurement.captured_at == captured_at
        assert all(
            component.get("observed_code") != "999"
            for child in result.measurement.groups.all()
            for component in child.components_json
        )


@pytest.mark.django_db
class TestCalculations:
    def test_simple_calculation_rounding_and_nonoccupied_statuses(self):
        _, child_model = _measurement_models()
        capture_date = timezone.localdate()
        _catalog(capture_date, [_standard_group(capacity=10)])
        run = _run()
        captured_at = _at(capture_date)
        statuses = [
            *([BedStatus.OCCUPIED] * 8),
            BedStatus.EMPTY,
            BedStatus.RESERVED,
            BedStatus.MAINTENANCE,
            BedStatus.ISOLATION,
        ]
        for index, status in enumerate(statuses):
            _snapshot(
                run,
                captured_at=captured_at,
                code="100",
                sector="Sector A",
                status=status,
                index=index,
                patient_marker=f"SYN-{index:03d}",
            )

        result = _materialize(run.pk)
        child = child_model.objects.get(measurement=result.measurement)

        assert child.occupied_count == 8
        assert child.occupancy_percentage == Decimal("80.00")
        assert child.exceeded_by == 0
        assert child.status_counts_json == {
            "occupied": 8,
            "empty": 1,
            "reserved": 1,
            "maintenance": 1,
            "isolation": 1,
        }
        assert result.measurement.occupied_for_rate == 8
        assert result.measurement.occupancy_percentage == Decimal("80.00")

    def test_percentage_uses_decimal_round_half_up(self):
        _, child_model = _measurement_models()
        capture_date = timezone.localdate()
        _catalog(capture_date, [_standard_group(capacity=6)])
        run = _run()
        for index in range(4):
            _snapshot(
                run,
                captured_at=_at(capture_date),
                code="100",
                sector="Sector A",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"SYN-{index:03d}",
            )

        result = _materialize(run.pk)
        child = child_model.objects.get(measurement=result.measurement)

        assert child.occupancy_percentage == Decimal("66.67")

    def test_shared_cardio_capacity_is_applied_once(self):
        _, child_model = _measurement_models()
        capture_date = timezone.localdate()
        _catalog(
            capture_date,
            [
                _standard_group(
                    key="ENF-2B-CARD",
                    capacity=15,
                    members=(("719", "Cardio A"), ("2156", "Cardio B")),
                )
            ],
        )
        run = _run()
        for index, code in enumerate(["719"] * 7 + ["2156"] * 5):
            _snapshot(
                run,
                captured_at=_at(capture_date),
                code=code,
                sector="Cardio A" if code == "719" else "Cardio B",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"SYN-{index:03d}",
            )

        result = _materialize(run.pk)
        child = child_model.objects.get(measurement=result.measurement)

        assert child.stable_key == "ENF-2B-CARD"
        assert child.official_capacity == 15
        assert child.occupied_count == 12
        assert child.occupancy_percentage == Decimal("80.00")

    def test_co_54_of_8_is_675_percent_and_exceeded_by_46(self):
        _, child_model = _measurement_models()
        capture_date = timezone.localdate()
        codes = ("20", "1110", "1112", "1114", "1116")
        _catalog(
            capture_date,
            [
                _standard_group(
                    key="CO",
                    capacity=8,
                    members=tuple((code, f"CO {code}") for code in codes),
                )
            ],
        )
        run = _run()
        for index in range(54):
            code = codes[index % len(codes)]
            _snapshot(
                run,
                captured_at=_at(capture_date),
                code=code,
                sector=f"CO {code}",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"STALE-{index:03d}",
            )

        result = _materialize(run.pk)
        child = child_model.objects.get(measurement=result.measurement)

        assert child.occupied_count == 54
        assert child.official_capacity == 8
        assert child.occupancy_percentage == Decimal("675.00")
        assert child.exceeded_by == 46
        assert result.measurement.occupied_for_rate == 54


@pytest.mark.django_db
class TestNonCalculableCoverageAndPrivacy:
    def test_pending_unrated_unknown_and_blank_states_remain_explicit(self):
        _, child_model = _measurement_models()
        capture_date = timezone.localdate()
        _catalog(
            capture_date,
            [
                {
                    "stable_key": "OBST-3A",
                    "display_name": "Obstetricia 3A",
                    "capacity": 32,
                    "policy": CalculationPolicy.LINKED_SLOTS_PENDING,
                    "members": (("654", "3A Source"),),
                },
                {
                    "stable_key": "UNRATED-MED-PED",
                    "display_name": "Unrated",
                    "capacity": None,
                    "policy": CalculationPolicy.UNRATED,
                    "members": (("1002", "Unrated Source"),),
                },
            ],
        )
        run = _run()
        scenarios = [
            ("654", "3A Source"),
            ("1002", "Unrated Source"),
            ("007", "Unknown Leading Zero"),
            ("", "Blank Code Sector"),
        ]
        for index, (code, sector) in enumerate(scenarios):
            _snapshot(
                run,
                captured_at=_at(capture_date),
                code=code,
                sector=sector,
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"SYN-{index:03d}",
            )

        result = _materialize(run.pk)
        children = {
            child.stable_key: child
            for child in child_model.objects.filter(measurement=result.measurement)
        }
        pending = children["OBST-3A"]
        unrated = children["UNRATED-MED-PED"]
        unmapped = [
            child for child in children.values() if child.calculation_status == "unmapped"
        ]

        assert pending.official_capacity == 32
        assert pending.calculation_status == "linked_slots_pending"
        assert pending.status_counts_json["occupied"] == 1
        assert pending.occupied_count is None
        assert pending.occupancy_percentage is None
        assert pending.exceeded_by is None
        assert unrated.official_capacity is None
        assert unrated.calculation_status == "unrated"
        assert unrated.status_counts_json["occupied"] == 1
        assert unrated.occupancy_percentage is None
        assert len(unmapped) == 2
        assert result.measurement.known_capacity == 32
        assert result.measurement.calculable_capacity == 0
        assert result.measurement.occupied_for_rate == 0
        assert result.measurement.occupancy_percentage is None
        assert all(child.official_capacity is None for child in unmapped)
        assert all(child.occupancy_percentage is None for child in unmapped)
        observed_codes = {
            component["observed_code"]
            for child in unmapped
            for component in child.components_json
        }
        assert observed_codes == {"007", ""}
        blank = next(
            child
            for child in unmapped
            if child.components_json[0]["observed_code"] == ""
        )
        assert blank.display_name == "Blank Code Sector"

    def test_all_initial_codes_produce_approved_totals_and_dual_coverage(self):
        parent_model, child_model = _measurement_models()
        capture_date = timezone.localdate()
        document = json.loads(INITIAL_CATALOG.read_text(encoding="utf-8"))
        validated = validate_catalog_document(document)
        groups = [
            {
                "stable_key": group.stable_key,
                "display_name": group.display_name,
                "capacity": group.official_capacity,
                "policy": group.calculation_policy,
                "members": tuple(
                    (member.source_code, member.configured_source_name)
                    for member in group.memberships
                ),
            }
            for group in validated.groups
        ]
        _catalog(capture_date, groups)
        run = _run()
        index = 0
        for group in validated.groups:
            for member in group.memberships:
                _snapshot(
                    run,
                    captured_at=_at(capture_date),
                    code=member.source_code,
                    sector=member.configured_source_name,
                    index=index,
                )
                index += 1

        result = _materialize(run.pk)
        measurement = parent_model.objects.get(pk=result.measurement.pk)

        assert measurement.observed_sector_count == 47
        assert measurement.capacity_covered_sector_count == 44
        assert measurement.calculable_sector_count == 43
        assert measurement.known_capacity == 658
        assert measurement.calculable_capacity == 626
        assert child_model.objects.filter(measurement=measurement).count() == 42

    def test_unknown_code_lowers_coverage_without_blocking(self):
        capture_date = timezone.localdate()
        _catalog(capture_date, [_standard_group()])
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="100",
            sector="Sector A",
        )
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="999",
            sector="Unknown",
            index=1,
        )
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="",
            sector="Sector A",
            index=2,
        )

        result = _materialize(run.pk)
        measurement = result.measurement

        assert measurement.observed_sector_count == 3
        assert measurement.capacity_covered_sector_count == 1
        assert measurement.calculable_sector_count == 1
        assert measurement.groups.filter(calculation_status="unmapped").count() == 2

    def test_name_drift_records_mismatch_without_remapping(self):
        _, child_model = _measurement_models()
        capture_date = timezone.localdate()
        _catalog(capture_date, [_standard_group()])
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="100",
            sector="Renamed Source Sector",
        )

        result = _materialize(run.pk)
        child = child_model.objects.get(measurement=result.measurement)
        component = child.components_json[0]

        assert child.stable_key == "A"
        assert component["configured_code"] == "100"
        assert component["configured_name"] == "Sector A"
        assert component["observed_code"] == "100"
        assert component["observed_name"] == "Renamed Source Sector"
        assert component["source_name_mismatch"] is True

    def test_new_schema_and_json_never_store_patient_identifiers(self):
        parent_model, child_model = _measurement_models()
        parent_fields = {field.name for field in parent_model._meta.get_fields()}
        child_fields = {field.name for field in child_model._meta.get_fields()}
        run_delete = parent_model._meta.get_field("census_run").remote_field.on_delete
        catalog_delete = parent_model._meta.get_field("catalog").remote_field.on_delete
        assert run_delete.__name__ == "PROTECT"
        assert catalog_delete.__name__ == "PROTECT"
        forbidden_fields = {
            "nome",
            "prontuario",
            "patient_name",
            "patient_record",
            "clinical_text",
        }
        assert forbidden_fields.isdisjoint(parent_fields)
        assert forbidden_fields.isdisjoint(child_fields)

        capture_date = timezone.localdate()
        _catalog(capture_date, [_standard_group()])
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="PRIVATE-RECORD-XYZ",
        )
        result = _materialize(run.pk)
        serialized = json.dumps(
            [
                {
                    "counts": child.status_counts_json,
                    "components": child.components_json,
                }
                for child in child_model.objects.filter(measurement=result.measurement)
            ]
        )
        assert "PRIVATE-RECORD-XYZ" not in serialized
        assert "Synthetic Patient" not in serialized


@pytest.mark.django_db
class TestSchemaCommandAndAtomicity:
    def test_db_constraints_and_protected_history_references(self):
        parent_model, child_model = _measurement_models()
        capture_date = timezone.localdate()
        catalog = _catalog(capture_date, [_standard_group()])
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="100",
            sector="Sector A",
        )
        result = _materialize(run.pk)
        measurement = result.measurement

        with pytest.raises(IntegrityError):
            with transaction.atomic():
                parent_model.objects.create(
                    census_run=run,
                    catalog=catalog,
                    captured_at=_at(capture_date),
                    local_date=capture_date,
                    algorithm_version="occupancy-v1",
                    observed_sector_count=0,
                    capacity_covered_sector_count=0,
                    calculable_sector_count=0,
                    known_capacity=0,
                    calculable_capacity=0,
                    occupied_for_rate=0,
                    occupancy_percentage=Decimal("0.00"),
                    exceeded_by=0,
                )
        child = child_model.objects.get(measurement=measurement)
        with pytest.raises(IntegrityError):
            with transaction.atomic():
                child_model.objects.create(
                    measurement=measurement,
                    stable_key=child.stable_key,
                    display_name="Duplicate",
                    calculation_policy=CalculationPolicy.STANDARD,
                    calculation_status="calculated",
                    official_capacity=1,
                    occupied_count=0,
                    occupancy_percentage=Decimal("0.00"),
                    exceeded_by=0,
                    status_counts_json={},
                    components_json=[],
                )

    def test_command_requires_exactly_one_run_and_has_no_bulk_mode(self, capsys):
        domain = _domain()
        command_module = importlib.import_module(
            "apps.census.management.commands.materialize_occupancy_measurement"
        )
        parser = command_module.Command().create_parser("manage.py", "materialize")
        run_action = next(
            action for action in parser._actions if "--run-id" in action.option_strings
        )
        django_base_options = {
            "--help",
            "--version",
            "--verbosity",
            "--settings",
            "--pythonpath",
            "--traceback",
            "--no-color",
            "--force-color",
            "--skip-checks",
        }
        custom_long_options = {
            option
            for action in parser._actions
            for option in action.option_strings
            if option.startswith("--") and option not in django_base_options
        }
        assert run_action.required is True
        assert custom_long_options == {"--run-id"}

        with pytest.raises(CommandError):
            call_command("materialize_occupancy_measurement")

        capture_date = timezone.localdate()
        _catalog(capture_date, [_standard_group()])
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="100",
            sector="Sector A",
        )
        call_command("materialize_occupancy_measurement", "--run-id", run.pk)
        assert "created" in capsys.readouterr().out
        assert domain.materialize_occupancy_measurement(run_id=run.pk).status == "existing"

    def test_mid_transaction_failure_leaves_no_partial_parent_or_children(self):
        parent_model, child_model = _measurement_models()
        capture_date = timezone.localdate()
        _catalog(capture_date, [_standard_group()])
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="100",
            sector="Sector A",
        )

        with patch(
            "django.db.models.query.QuerySet.bulk_create",
            side_effect=RuntimeError("synthetic persistence failure"),
        ):
            with pytest.raises(RuntimeError, match="synthetic persistence failure"):
                _materialize(run.pk)

        assert parent_model.objects.count() == 0
        assert child_model.objects.count() == 0


@pytest.mark.django_db
class TestDailyOccupancySummary:
    """SCOH-S3 daily summary aggregation from immutable measurements."""

    def _daily_models(self):
        models_module = importlib.import_module("apps.census.models")
        parent = getattr(models_module, "DailyOccupancySummary", None)
        child = getattr(models_module, "DailyGroupOccupancySummary", None)
        if parent is None or child is None:
            pytest.fail("daily occupancy summary schema is missing")
        return parent, child

    def test_daily_behavior_is_a_real_assertion_red(self):
        self._daily_models()
        domain = _domain()
        assert hasattr(domain, "refresh_daily_occupancy_summary"), (
            "daily occupancy summary refresh behavior is not implemented"
        )

    def test_first_measurement_creates_one_parent_and_group_summaries(self):
        parent_model, child_model = self._daily_models()
        today = timezone.localdate()
        _catalog(today, [_standard_group(capacity=10)])
        run = _run()
        _snapshot(
            run,
            captured_at=_at(today, 8),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-001",
        )

        result = _materialize(run.pk)

        assert result.status == "created"
        assert parent_model.objects.count() == 1
        summary = parent_model.objects.get(local_date=today)
        assert summary.measurement_count == 1
        assert summary.first_captured_at == _at(today, 8)
        assert summary.last_captured_at == _at(today, 8)
        assert child_model.objects.filter(daily_summary=summary).count() == 1
        group = child_model.objects.get(daily_summary=summary, stable_key="A")
        assert group.measurement_count == 1

    def test_second_same_day_measurement_updates_instead_of_duplicates(self):
        parent_model, child_model = self._daily_models()
        today = timezone.localdate()
        _catalog(today, [_standard_group(capacity=10)])
        run_a = _run()
        run_b = _run()
        _snapshot(
            run_a,
            captured_at=_at(today, 8),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-001",
        )
        _snapshot(
            run_b,
            captured_at=_at(today, 20),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-002",
        )

        _materialize(run_a.pk)
        _materialize(run_b.pk)

        assert parent_model.objects.count() == 1
        summary = parent_model.objects.get(local_date=today)
        assert summary.measurement_count == 2
        assert summary.first_captured_at == _at(today, 8)
        assert summary.last_captured_at == _at(today, 20)
        assert child_model.objects.filter(daily_summary=summary).count() == 1
        group = child_model.objects.get(daily_summary=summary, stable_key="A")
        assert group.measurement_count == 2

    def test_arithmetic_mean_min_max_first_last_and_exceeded_by_are_exact(self):
        _, child_model = self._daily_models()
        today = timezone.localdate()
        _catalog(today, [_standard_group(capacity=8)])
        run_a = _run()
        run_b = _run()
        for index in range(5):
            _snapshot(
                run_a,
                captured_at=_at(today, 8),
                code="100",
                sector="Sector A",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"A-{index}",
            )
        for index in range(10):
            _snapshot(
                run_b,
                captured_at=_at(today, 20),
                code="100",
                sector="Sector A",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"B-{index}",
            )

        _materialize(run_a.pk)
        _materialize(run_b.pk)
        summary = self._daily_models()[0].objects.get(local_date=today)

        assert summary.measurement_count == 2
        assert summary.first_captured_at == _at(today, 8)
        assert summary.last_captured_at == _at(today, 20)
        assert summary.mean_occupied == Decimal("7.50")
        assert summary.min_occupied == 5
        assert summary.max_occupied == 10
        assert summary.mean_percentage == Decimal("93.75")
        assert summary.min_percentage == Decimal("62.50")
        assert summary.max_percentage == Decimal("125.00")
        assert summary.max_exceeded_by == 2
        group = child_model.objects.get(daily_summary=summary, stable_key="A")
        assert group.mean_occupied == Decimal("7.50")
        assert group.min_occupied == 5
        assert group.max_occupied == 10
        assert group.mean_percentage == Decimal("93.75")
        assert group.min_percentage == Decimal("62.50")
        assert group.max_percentage == Decimal("125.00")
        assert group.max_exceeded_by == 2

    def test_unequal_intervals_still_have_equal_weights(self):
        parent_model, _ = self._daily_models()
        today = timezone.localdate()
        _catalog(today, [_standard_group(capacity=6)])
        for hour, marker in [(8, "MORNING"), (9, "EARLY-NOON"), (23, "NIGHT")]:
            run = _run()
            for index in range(3):
                _snapshot(
                    run,
                    captured_at=_at(today, hour),
                    code="100",
                    sector="Sector A",
                    status=BedStatus.OCCUPIED,
                    index=index,
                    patient_marker=f"{marker}-{index}",
                )
            _materialize(run.pk)

        summary = parent_model.objects.get(local_date=today)

        assert summary.measurement_count == 3
        assert summary.mean_occupied == Decimal("3.00")
        assert summary.min_occupied == 3
        assert summary.max_occupied == 3
        assert summary.mean_percentage == Decimal("50.00")

    def test_mean_uses_exact_numerators_and_rounds_final_with_half_up(self):
        parent_model, child_model = self._daily_models()
        today = timezone.localdate()
        _catalog(today, [_standard_group(capacity=3)])
        run_a = _run()
        run_b = _run()
        _snapshot(
            run_a,
            captured_at=_at(today, 8),
            code="100",
            sector="Sector A",
        )
        for index in range(2):
            _snapshot(
                run_b,
                captured_at=_at(today, 20),
                code="100",
                sector="Sector A",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"B-{index}",
            )

        _materialize(run_a.pk)
        _materialize(run_b.pk)
        summary = parent_model.objects.get(local_date=today)
        group = child_model.objects.get(daily_summary=summary, stable_key="A")

        # Exact percentages are 0.000 and 66.666... -> exact mean 33.333...
        # rounds to 33.33. Averaging the stored 0.00/66.67 would give 33.34.
        assert summary.mean_percentage == Decimal("33.33")
        assert group.mean_percentage == Decimal("33.33")

    def test_delayed_measurement_updates_its_original_local_date(self):
        parent_model, _ = self._daily_models()
        yesterday = timezone.localdate() - timedelta(days=1)
        _catalog(yesterday, [_standard_group(capacity=6)])
        run_a = _run()
        run_b = _run()
        _snapshot(
            run_a,
            captured_at=_at(yesterday, 8),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-A",
        )
        for index in range(3):
            _snapshot(
                run_b,
                captured_at=_at(yesterday, 23),
                code="100",
                sector="Sector A",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"SYN-B-{index}",
            )

        # Materialized now (delayed): summary must belong to the capture date.
        _materialize(run_a.pk)
        _materialize(run_b.pk)

        assert parent_model.objects.count() == 1
        summary = parent_model.objects.get(local_date=yesterday)
        assert summary.measurement_count == 2
        assert summary.first_captured_at == _at(yesterday, 8)
        assert summary.last_captured_at == _at(yesterday, 23)
        assert summary.mean_occupied == Decimal("2.00")
        assert not parent_model.objects.filter(local_date=timezone.localdate()).exists()

    def test_repeated_existing_measurement_does_not_rewrite_summary(self):
        parent_model, _ = self._daily_models()
        today = timezone.localdate()
        _catalog(today, [_standard_group(capacity=6)])
        run = _run()
        _snapshot(
            run,
            captured_at=_at(today, 8),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-001",
        )

        first = _materialize(run.pk)
        summary = parent_model.objects.get(local_date=today)
        original = (summary.measurement_count, summary.mean_occupied)

        _snapshot(
            run,
            captured_at=_at(today, 8),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=2,
            patient_marker="SYN-002",
        )
        second = _materialize(run.pk)
        summary.refresh_from_db()

        assert first.status == "created"
        assert second.status == "existing"
        assert second.created is False
        assert (summary.measurement_count, summary.mean_occupied) == original

    def test_pending_unrated_and_unmapped_groups_keep_raw_statistics_and_null_rates(self):
        parent_model, child_model = self._daily_models()
        today = timezone.localdate()
        _catalog(
            today,
            [
                _standard_group(capacity=10),
                {
                    "stable_key": "PENDING",
                    "display_name": "Pending",
                    "capacity": 32,
                    "policy": CalculationPolicy.LINKED_SLOTS_PENDING,
                    "members": (("200", "Pending Sector"),),
                },
                {
                    "stable_key": "UNRATED",
                    "display_name": "Unrated",
                    "capacity": None,
                    "policy": CalculationPolicy.UNRATED,
                    "members": (("300", "Unrated Sector"),),
                },
            ],
        )
        runs = [_run(), _run()]
        for index, run in enumerate(runs):
            occupied_standard = 2 if index == 0 else 4
            occupied_pending = 1 if index == 0 else 3
            occupied_unrated = 1 if index == 0 else 2
            for i in range(occupied_standard):
                _snapshot(
                    run,
                    captured_at=_at(today, 8 + index * 12),
                    code="100",
                    sector="Sector A",
                    status=BedStatus.OCCUPIED,
                    index=i,
                    patient_marker=f"S-{index}-{i}",
                )
            for i in range(occupied_pending):
                _snapshot(
                    run,
                    captured_at=_at(today, 8 + index * 12),
                    code="200",
                    sector="Pending Sector",
                    status=BedStatus.OCCUPIED,
                    index=i,
                    patient_marker=f"P-{index}-{i}",
                )
            for i in range(occupied_unrated):
                _snapshot(
                    run,
                    captured_at=_at(today, 8 + index * 12),
                    code="300",
                    sector="Unrated Sector",
                    status=BedStatus.OCCUPIED,
                    index=i,
                    patient_marker=f"U-{index}-{i}",
                )
            _materialize(run.pk)

        summary = parent_model.objects.get(local_date=today)
        pending = child_model.objects.get(daily_summary=summary, stable_key="PENDING")
        unrated = child_model.objects.get(daily_summary=summary, stable_key="UNRATED")
        standard = child_model.objects.get(daily_summary=summary, stable_key="A")

        assert pending.measurement_count == 2
        assert pending.mean_occupied == Decimal("2.00")
        assert pending.min_occupied == 1
        assert pending.max_occupied == 3
        assert pending.mean_percentage is None
        assert pending.min_percentage is None
        assert pending.max_percentage is None
        assert pending.official_capacity == 32
        assert unrated.measurement_count == 2
        assert unrated.mean_occupied == Decimal("1.50")
        assert unrated.min_occupied == 1
        assert unrated.max_occupied == 2
        assert unrated.mean_percentage is None
        assert unrated.official_capacity is None
        assert standard.mean_percentage is not None
        assert summary.mean_percentage is not None

    def test_changing_intraday_coverage_preserves_min_max_evidence(self):
        parent_model, _ = self._daily_models()
        today = timezone.localdate()
        _catalog(today, [_standard_group()])
        run_a = _run()
        run_b = _run()
        _snapshot(
            run_a,
            captured_at=_at(today, 8),
            code="100",
            sector="Sector A",
        )
        _snapshot(
            run_a,
            captured_at=_at(today, 8),
            code="999",
            sector="Unknown",
            index=1,
        )
        _snapshot(
            run_b,
            captured_at=_at(today, 20),
            code="100",
            sector="Sector A",
        )

        _materialize(run_a.pk)
        _materialize(run_b.pk)
        summary = parent_model.objects.get(local_date=today)

        assert summary.min_observed_sector_count == 1
        assert summary.max_observed_sector_count == 2
        assert summary.min_capacity_covered_sector_count == 1
        assert summary.max_capacity_covered_sector_count == 1
        assert summary.min_calculable_sector_count == 1
        assert summary.max_calculable_sector_count == 1

    def test_day_without_measurement_has_no_fabricated_summary(self):
        parent_model, _ = self._daily_models()
        today = timezone.localdate()
        _catalog(today + timedelta(days=1), [_standard_group()])
        run = _run()
        _snapshot(
            run,
            captured_at=_at(today),
            code="100",
            sector="Sector A",
        )

        result = _materialize(run.pk)

        assert result.status == "pre_activation"
        assert parent_model.objects.count() == 0

    def test_later_catalog_does_not_rebuild_prior_summary(self):
        parent_model, _ = self._daily_models()
        today = timezone.localdate()
        first_catalog = _catalog(today, [_standard_group(capacity=10)])
        run_a = _run()
        _snapshot(
            run_a,
            captured_at=_at(today, 8),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-A",
        )
        _materialize(run_a.pk)
        summary = parent_model.objects.get(local_date=today)

        second_catalog = _catalog(
            today + timedelta(days=1), [_standard_group(capacity=99)]
        )
        run_b = _run()
        _snapshot(
            run_b,
            captured_at=_at(today + timedelta(days=1), 8),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-B",
        )
        _materialize(run_b.pk)

        summary.refresh_from_db()
        assert summary.catalog_id == first_catalog.pk
        assert summary.known_capacity == 10
        assert summary.algorithm_version == "occupancy-v1"
        later = parent_model.objects.get(local_date=today + timedelta(days=1))
        assert later.catalog_id == second_catalog.pk
        assert later.known_capacity == 99


def _partitioned_3a_catalog() -> list[dict]:
    """Corrected-style catalog: 654 split exclusively into Adulto/Infantil."""
    return [
        _standard_group(
            key="OBST-3A-ADULTO",
            capacity=32,
            members=(("654", "3A Source", "age_12_or_over"),),
        ),
        _standard_group(
            key="OBST-3A-INFANTIL",
            capacity=16,
            members=(("654", "3A Source", "under_12"),),
        ),
    ]


@pytest.mark.django_db
class TestV1DispatchRegression:
    """R1: a catalog without age partitions keeps occupancy-v1 untouched."""

    def test_initial_catalog_remains_v1_with_658_626_and_calculated_co(self):
        parent_model, _ = _measurement_models()
        capture_date = timezone.localdate()
        document = json.loads(INITIAL_CATALOG.read_text(encoding="utf-8"))
        validated = validate_catalog_document(document)
        groups = [
            {
                "stable_key": group.stable_key,
                "display_name": group.display_name,
                "capacity": group.official_capacity,
                "policy": group.calculation_policy,
                "members": tuple(
                    (member.source_code, member.configured_source_name)
                    for member in group.memberships
                ),
            }
            for group in validated.groups
        ]
        _catalog(capture_date, groups)
        run = _run()
        for index, group in enumerate(validated.groups):
            for member in group.memberships:
                _snapshot(
                    run,
                    captured_at=_at(capture_date),
                    code=member.source_code,
                    sector=member.configured_source_name,
                    index=index,
                )

        result = _materialize(run.pk)
        measurement = parent_model.objects.get(pk=result.measurement.pk)

        assert measurement.algorithm_version == "occupancy-v1"
        assert measurement.observed_sector_count == 47
        assert measurement.capacity_covered_sector_count == 44
        assert measurement.calculable_sector_count == 43
        assert measurement.known_capacity == 658
        assert measurement.calculable_capacity == 626
        co = measurement.groups.get(stable_key="CO")
        assert co.calculation_status == "calculated"
        assert co.official_capacity == 8
        assert co.occupied_count == 0
        assert measurement.age_partial is False
        assert measurement.unknown_age_count == 0
        assert measurement.official_sector_count is None


@pytest.mark.django_db
class TestV2Materialization:
    """R2-R6, R9: corrected age-partitioned materialization."""

    def test_partitioned_catalog_dispatches_occupancy_v2(self):
        capture_date = timezone.localdate()
        _catalog(capture_date, _partitioned_3a_catalog())
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            patient_marker="SYN-001",
            age_band="age_12_or_over",
        )

        result = _materialize(run.pk)

        assert result.measurement.algorithm_version == "occupancy-v2"

    def test_adult_and_child_3a_sectors_use_own_capacities(self):
        capture_date = timezone.localdate()
        _catalog(capture_date, _partitioned_3a_catalog())
        run = _run()
        rows = [
            ("age_12_or_over", "A-ADULT-1"),
            ("age_12_or_over", "A-ADULT-2"),
            ("age_12_or_over", "A-ADULT-3"),
            ("age_12_or_over", "A-ADULT-4"),
            ("age_12_or_over", "A-ADULT-5"),
            ("under_12", "C-1"),
            ("under_12", "C-2"),
            ("under_12", "C-3"),
        ]
        for index, (band, marker) in enumerate(rows):
            _snapshot(
                run,
                captured_at=_at(capture_date),
                code="654",
                sector="3A Source",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=marker,
                age_band=band,
            )

        result = _materialize(run.pk)
        groups = {g.stable_key: g for g in result.measurement.groups.all()}
        adult = groups["OBST-3A-ADULTO"]
        child = groups["OBST-3A-INFANTIL"]

        assert adult.official_capacity == 32
        assert adult.occupied_count == 5
        assert adult.occupancy_percentage == Decimal("15.63")
        assert child.official_capacity == 16
        assert child.occupied_count == 3
        assert child.occupancy_percentage == Decimal("18.75")
        assert result.measurement.occupied_for_rate == 8
        assert result.measurement.calculable_capacity == 48
        assert result.measurement.occupancy_percentage == Decimal("16.67")

    def test_shared_record_number_counts_each_row_in_its_own_band(self):
        capture_date = timezone.localdate()
        _catalog(capture_date, _partitioned_3a_catalog())
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="SHARED-PRONT",
            age_band="under_12",
        )
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="SHARED-PRONT",
            age_band="age_12_or_over",
        )

        result = _materialize(run.pk)
        groups = {g.stable_key: g for g in result.measurement.groups.all()}

        assert groups["OBST-3A-ADULTO"].occupied_count == 1
        assert groups["OBST-3A-INFANTIL"].occupied_count == 1
        assert result.measurement.occupied_for_rate == 2

    def test_non_occupied_3a_rows_enter_neither_numerator(self):
        capture_date = timezone.localdate()
        _catalog(capture_date, _partitioned_3a_catalog())
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="ADULT-1",
            age_band="age_12_or_over",
        )
        for index, status in enumerate(
            [BedStatus.EMPTY, BedStatus.RESERVED, BedStatus.MAINTENANCE, BedStatus.ISOLATION],
            start=1,
        ):
            _snapshot(
                run,
                captured_at=_at(capture_date),
                code="654",
                sector="3A Source",
                status=status,
                index=index,
            )

        result = _materialize(run.pk)
        groups = {g.stable_key: g for g in result.measurement.groups.all()}

        assert groups["OBST-3A-ADULTO"].occupied_count == 1
        assert groups["OBST-3A-INFANTIL"].occupied_count == 0
        assert groups["OBST-3A-INFANTIL"].occupancy_percentage == Decimal("0.00")
        assert result.measurement.occupied_for_rate == 1

    def test_unknown_occupied_age_excludes_only_that_row_and_marks_partial(self):
        capture_date = timezone.localdate()
        _catalog(capture_date, _partitioned_3a_catalog())
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="ADULT-1",
            age_band="age_12_or_over",
        )
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="CHILD-1",
            age_band="under_12",
        )
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=2,
            patient_marker="UNKNOWN-1",
            age_band="unknown",
        )

        result = _materialize(run.pk)
        measurement = result.measurement

        assert measurement.unknown_age_count == 1
        assert measurement.age_partial is True
        groups = {g.stable_key: g for g in measurement.groups.all()}
        assert groups["OBST-3A-ADULTO"].occupied_count == 1
        assert groups["OBST-3A-INFANTIL"].occupied_count == 1
        assert measurement.occupied_for_rate == 2
        assert measurement.known_capacity == 48
        assert measurement.calculable_capacity == 48
        assert measurement.occupancy_percentage == Decimal("4.17")
        assert not measurement.groups.filter(calculation_status="unmapped").exists()

    def test_corrected_co_keeps_raw_counts_and_null_rate_fields(self):
        capture_date = timezone.localdate()
        codes = ("20", "1110", "1112", "1114", "1116")
        _catalog(
            capture_date,
            [
                *_partitioned_3a_catalog(),
                {
                    "stable_key": "CO",
                    "display_name": "Centro Obstetrico",
                    "capacity": None,
                    "policy": CalculationPolicy.UNRATED,
                    "members": tuple((code, f"CO {code}", "all") for code in codes),
                },
            ],
        )
        run = _run()
        for index in range(54):
            code = codes[index % len(codes)]
            _snapshot(
                run,
                captured_at=_at(capture_date),
                code=code,
                sector=f"CO {code}",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"SYN-{index:03d}",
            )

        result = _materialize(run.pk)
        measurement = result.measurement

        assert measurement.algorithm_version == "occupancy-v2"
        co = measurement.groups.get(stable_key="CO")
        assert co.calculation_policy == "unrated"
        assert co.calculation_status == "unrated"
        assert co.official_capacity is None
        assert co.occupied_count is None
        assert co.occupancy_percentage is None
        assert co.exceeded_by is None
        assert co.status_counts_json["occupied"] == 54
        assert measurement.occupied_for_rate == 0
        assert measurement.unknown_age_count == 0
        assert measurement.age_partial is False

    def test_full_corrected_catalog_reports_official_coverage_and_666(self):
        capture_date = timezone.localdate()
        document = json.loads(CORRECTED_CATALOG.read_text(encoding="utf-8"))
        validated = validate_catalog_document(document)
        groups = [
            {
                "stable_key": group.stable_key,
                "display_name": group.display_name,
                "capacity": group.official_capacity,
                "policy": group.calculation_policy,
                "members": tuple(
                    (
                        member.source_code,
                        member.configured_source_name,
                        member.age_selector,
                    )
                    for member in group.memberships
                ),
            }
            for group in validated.groups
        ]
        _catalog(capture_date, groups)
        run = _run()
        for index, group in enumerate(validated.groups):
            for member in group.memberships:
                _snapshot(
                    run,
                    captured_at=_at(capture_date),
                    code=member.source_code,
                    sector=member.configured_source_name,
                    index=index,
                )

        result = _materialize(run.pk)
        measurement = result.measurement

        assert measurement.algorithm_version == "occupancy-v2"
        assert measurement.official_sector_count == 43
        assert measurement.official_capacity_sector_count == 39
        assert measurement.official_calculable_sector_count == 39
        assert measurement.known_capacity == 666
        assert measurement.calculable_capacity == 666
        assert measurement.observed_sector_count == 47
        assert measurement.capacity_covered_sector_count == 39
        assert measurement.calculable_sector_count == 39
        assert measurement.unknown_age_count == 0
        assert measurement.age_partial is False

    def test_v2_3a_overcapacity_is_not_capped(self):
        capture_date = timezone.localdate()
        _catalog(capture_date, _partitioned_3a_catalog())
        run = _run()
        for index in range(40):
            _snapshot(
                run,
                captured_at=_at(capture_date),
                code="654",
                sector="3A Source",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=f"ADULT-{index:03d}",
                age_band="age_12_or_over",
            )

        result = _materialize(run.pk)
        groups = {g.stable_key: g for g in result.measurement.groups.all()}
        adult = groups["OBST-3A-ADULTO"]

        assert adult.occupied_count == 40
        assert adult.occupancy_percentage == Decimal("125.00")
        assert adult.exceeded_by == 8
        assert result.measurement.occupied_for_rate == 40
        assert result.measurement.exceeded_by == 0

    def test_unknown_sector_does_not_change_official_coverage(self):
        capture_date = timezone.localdate()
        _catalog(
            capture_date,
            [
                *_partitioned_3a_catalog(),
                {
                    "stable_key": "CO",
                    "display_name": "Centro Obstetrico",
                    "capacity": None,
                    "policy": CalculationPolicy.UNRATED,
                    "members": (("20", "CO Source", "all"),),
                },
            ],
        )
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="ADULT-1",
            age_band="age_12_or_over",
        )
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="20",
            sector="CO Source",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="CO-1",
        )
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="999",
            sector="Unknown Sector",
            status=BedStatus.OCCUPIED,
            index=2,
            patient_marker="UNMAPPED-1",
        )

        result = _materialize(run.pk)
        measurement = result.measurement

        assert measurement.official_sector_count == 3
        assert measurement.official_capacity_sector_count == 2
        assert measurement.official_calculable_sector_count == 2
        assert measurement.observed_sector_count == 3
        assert measurement.capacity_covered_sector_count == 1
        assert measurement.calculable_sector_count == 1
        assert measurement.groups.filter(calculation_status="unmapped").count() == 1
        assert measurement.occupied_for_rate == 1

    def test_v2_reexecution_is_idempotent_and_never_persists_identifiers(self):
        capture_date = timezone.localdate()
        _catalog(capture_date, _partitioned_3a_catalog())
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="PRIVATE-RECORD-XYZ",
            age_band="age_12_or_over",
        )

        first = _materialize(run.pk)
        first_groups = {
            g.stable_key: (g.occupied_count, g.components_json)
            for g in first.measurement.groups.all()
        }
        second = _materialize(run.pk)
        second_groups = {
            g.stable_key: (g.occupied_count, g.components_json)
            for g in second.measurement.groups.all()
        }

        assert second.status == "existing"
        assert second.measurement.pk == first.measurement.pk
        assert second_groups == first_groups
        serialized = json.dumps(
            [
                {"counts": g.status_counts_json, "components": g.components_json}
                for g in second.measurement.groups.all()
            ]
        )
        assert "PRIVATE-RECORD-XYZ" not in serialized
        assert "Synthetic Patient" not in serialized
        adult = second.measurement.groups.get(stable_key="OBST-3A-ADULTO")
        assert adult.components_json[0]["age_selector"] == "age_12_or_over"


@pytest.mark.django_db
class TestV2DailyEligibility:
    """R7: age-partial v2 measurements never enter official daily statistics."""

    def _daily_models(self):
        models_module = importlib.import_module("apps.census.models")
        parent = getattr(models_module, "DailyOccupancySummary", None)
        child = getattr(models_module, "DailyGroupOccupancySummary", None)
        if parent is None or child is None:
            pytest.fail("daily occupancy summary schema is missing")
        return parent, child

    def test_v1_daily_summary_counts_all_measurements_eligible(self):
        parent_model, _ = self._daily_models()
        today = timezone.localdate()
        _catalog(today, [_standard_group(capacity=10)])
        runs = [_run(), _run()]
        for index, run in enumerate(runs):
            _snapshot(
                run,
                captured_at=_at(today, 8 + index * 12),
                code="100",
                sector="Sector A",
                status=BedStatus.OCCUPIED,
                patient_marker=f"SYN-{index}",
            )
            _materialize(run.pk)

        summary = parent_model.objects.get(local_date=today)

        assert summary.measurement_count == 2
        assert summary.eligible_measurement_count == 2
        assert summary.age_excluded_measurement_count == 0
        assert summary.mean_occupied == Decimal("1.00")

    def test_complete_v2_measurement_is_daily_eligible(self):
        parent_model, _ = self._daily_models()
        today = timezone.localdate()
        _catalog(today, _partitioned_3a_catalog())
        run = _run()
        _snapshot(
            run,
            captured_at=_at(today, 8),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            patient_marker="ADULT-1",
            age_band="age_12_or_over",
        )
        _materialize(run.pk)

        summary = parent_model.objects.get(local_date=today)

        assert summary.measurement_count == 1
        assert summary.eligible_measurement_count == 1
        assert summary.age_excluded_measurement_count == 0
        assert summary.mean_occupied == Decimal("1.00")
        assert summary.mean_percentage == Decimal("2.08")

    def test_mixed_day_uses_only_eligible_measurements(self):
        parent_model, child_model = self._daily_models()
        today = timezone.localdate()
        _catalog(today, _partitioned_3a_catalog())
        complete = _run()
        partial = _run()
        _snapshot(
            complete,
            captured_at=_at(today, 8),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            patient_marker="ADULT-1",
            age_band="age_12_or_over",
        )
        _snapshot(
            complete,
            captured_at=_at(today, 8),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="ADULT-2",
            age_band="age_12_or_over",
        )
        _snapshot(
            partial,
            captured_at=_at(today, 20),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            patient_marker="UNKNOWN-1",
            age_band="unknown",
        )
        _materialize(complete.pk)
        _materialize(partial.pk)

        summary = parent_model.objects.get(local_date=today)

        assert summary.measurement_count == 2
        assert summary.eligible_measurement_count == 1
        assert summary.age_excluded_measurement_count == 1
        assert summary.first_captured_at == _at(today, 8)
        assert summary.last_captured_at == _at(today, 20)
        assert summary.mean_occupied == Decimal("2.00")
        assert summary.min_occupied == 2
        assert summary.max_occupied == 2
        assert summary.mean_percentage == Decimal("4.17")
        assert summary.max_exceeded_by == 0
        adult = child_model.objects.get(
            daily_summary=summary, stable_key="OBST-3A-ADULTO"
        )
        assert adult.measurement_count == 1
        assert adult.mean_occupied == Decimal("2.00")
        assert adult.mean_percentage == Decimal("6.25")
        infant = child_model.objects.get(
            daily_summary=summary, stable_key="OBST-3A-INFANTIL"
        )
        assert infant.measurement_count == 1
        assert infant.mean_occupied == Decimal("0.00")
        assert infant.mean_percentage == Decimal("0.00")

    def test_day_with_only_partial_measurements_has_null_official_stats(self):
        parent_model, child_model = self._daily_models()
        today = timezone.localdate()
        _catalog(today, _partitioned_3a_catalog())
        run = _run()
        _snapshot(
            run,
            captured_at=_at(today, 8),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            patient_marker="UNKNOWN-1",
            age_band="unknown",
        )
        _materialize(run.pk)

        summary = parent_model.objects.get(local_date=today)

        assert summary.measurement_count == 1
        assert summary.eligible_measurement_count == 0
        assert summary.age_excluded_measurement_count == 1
        assert summary.mean_occupied is None
        assert summary.min_occupied is None
        assert summary.max_occupied is None
        assert summary.mean_percentage is None
        assert summary.min_percentage is None
        assert summary.max_percentage is None
        assert summary.max_exceeded_by is None
        assert child_model.objects.filter(daily_summary=summary).count() == 0


@pytest.mark.django_db
class TestV3PhysicalNormalization:
    """SOPBR-S1 R1-R7: occupancy-v3 normalized physical positions.

    Only catalogs declaring ``occupancy-v3`` dispatch the physical
    normalization; legacy catalogs keep structural v1/v2 dispatch (covered by
    ``TestV1DispatchRegression`` and ``TestV2Materialization``).
    """

    def test_exact_duplicate_same_bed_counts_one_position_and_one_extra_row(self):
        capture_date = timezone.localdate()
        _catalog(
            capture_date,
            [_standard_group(capacity=10)],
            algorithm_version="occupancy-v3",
        )
        run = _run()
        for i in range(2):
            _snapshot(
                run,
                captured_at=_at(capture_date),
                code="100",
                sector="Sector A",
                status=BedStatus.OCCUPIED,
                index=i,
                patient_marker="SYN-DUP",
                age_band="age_12_or_over",
                bed="BED-01",
            )

        result = _materialize(run.pk)
        measurement = result.measurement

        assert measurement.algorithm_version == "occupancy-v3"
        child = measurement.groups.get(stable_key="A")
        assert child.occupied_count == 1
        assert measurement.occupied_for_rate == 1
        reconciliation = measurement.physical_reconciliation_json
        assert reconciliation["duplicate_extra_rows"] == 1
        assert reconciliation["duplicate_occupied_rows"] == 1
        assert reconciliation["raw_occupied_rows"] == 2
        assert reconciliation["official_numerator"] == 1
        assert reconciliation["positions_by_status"]["occupied"] == 1
        assert measurement.position_partial is False

    def test_shared_record_in_distinct_beds_counts_two_positions(self):
        capture_date = timezone.localdate()
        _catalog(
            capture_date,
            [_standard_group(capacity=10)],
            algorithm_version="occupancy-v3",
        )
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="SHARED-REC",
            age_band="age_12_or_over",
            bed="BED-01",
        )
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="SHARED-REC",
            age_band="age_12_or_over",
            bed="BED-02",
        )

        result = _materialize(run.pk)
        measurement = result.measurement

        child = measurement.groups.get(stable_key="A")
        assert child.occupied_count == 2
        assert measurement.occupied_for_rate == 2
        assert measurement.physical_reconciliation_json["duplicate_extra_rows"] == 0

    def test_same_bed_with_divergent_records_is_conflict_and_partial(self):
        capture_date = timezone.localdate()
        _catalog(
            capture_date,
            [_standard_group(capacity=10)],
            algorithm_version="occupancy-v3",
        )
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="REC-1",
            age_band="age_12_or_over",
            bed="BED-01",
        )
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="REC-2",
            age_band="age_12_or_over",
            bed="BED-01",
        )

        result = _materialize(run.pk)
        measurement = result.measurement

        assert measurement.position_partial is True
        assert measurement.groups.get(stable_key="A").occupied_count == 0
        assert measurement.occupied_for_rate == 0
        reconciliation = measurement.physical_reconciliation_json
        assert reconciliation["conflict_positions"] == 1
        assert reconciliation["conflict_occupied_rows"] == 2
        assert reconciliation["official_numerator"] == 0

    def test_same_bed_with_divergent_statuses_is_conflict_and_partial(self):
        capture_date = timezone.localdate()
        _catalog(
            capture_date,
            [_standard_group(capacity=10)],
            algorithm_version="occupancy-v3",
        )
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="REC-1",
            age_band="age_12_or_over",
            bed="BED-01",
        )
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="100",
            sector="Sector A",
            status=BedStatus.EMPTY,
            index=1,
            bed="BED-01",
        )

        result = _materialize(run.pk)
        measurement = result.measurement

        assert measurement.position_partial is True
        assert measurement.groups.get(stable_key="A").occupied_count == 0
        assert measurement.occupied_for_rate == 0
        assert measurement.physical_reconciliation_json["conflict_positions"] == 1

    def test_occupied_without_bed_is_outside_numerator_and_partial(self):
        capture_date = timezone.localdate()
        _catalog(
            capture_date,
            [_standard_group(capacity=10)],
            algorithm_version="occupancy-v3",
        )
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="NO-BED",
            age_band="age_12_or_over",
            bed="",
        )

        result = _materialize(run.pk)
        measurement = result.measurement

        assert measurement.position_partial is True
        assert measurement.groups.get(stable_key="A").occupied_count == 0
        assert measurement.occupied_for_rate == 0
        reconciliation = measurement.physical_reconciliation_json
        assert reconciliation["unidentified_rows"] == 1
        assert reconciliation["unidentified_occupied_rows"] == 1

    def test_duplicate_outside_3a_proves_transversal_scope(self):
        capture_date = timezone.localdate()
        _catalog(
            capture_date,
            [
                _standard_group(
                    key="X",
                    capacity=10,
                    members=(("777", "Sector X"),),
                )
            ],
            algorithm_version="occupancy-v3",
        )
        run = _run()
        for i in range(2):
            _snapshot(
                run,
                captured_at=_at(capture_date),
                code="777",
                sector="Sector X",
                status=BedStatus.OCCUPIED,
                index=i,
                patient_marker="SYN-X",
                age_band="age_12_or_over",
                bed="X-01",
            )

        result = _materialize(run.pk)

        assert result.measurement.groups.get(stable_key="X").occupied_count == 1
        assert result.measurement.physical_reconciliation_json[
            "duplicate_extra_rows"
        ] == 1

    def test_3a_v3_preserves_age_partition_after_normalization(self):
        capture_date = timezone.localdate()
        _catalog(
            capture_date,
            _partitioned_3a_catalog(),
            algorithm_version="occupancy-v3",
        )
        run = _run()
        rows = [
            ("age_12_or_over", "A-1", "3A-01"),
            ("age_12_or_over", "A-1", "3A-01"),
            ("age_12_or_over", "A-2", "3A-02"),
            ("under_12", "C-1", "3A-03"),
        ]
        for index, (band, marker, bed) in enumerate(rows):
            _snapshot(
                run,
                captured_at=_at(capture_date),
                code="654",
                sector="3A Source",
                status=BedStatus.OCCUPIED,
                index=index,
                patient_marker=marker,
                age_band=band,
                bed=bed,
            )

        result = _materialize(run.pk)
        measurement = result.measurement
        groups = {g.stable_key: g for g in measurement.groups.all()}

        assert groups["OBST-3A-ADULTO"].occupied_count == 2
        assert groups["OBST-3A-INFANTIL"].occupied_count == 1
        assert measurement.occupied_for_rate == 3
        assert measurement.physical_reconciliation_json[
            "duplicate_occupied_rows"
        ] == 1
        assert measurement.physical_reconciliation_json["official_numerator"] == 3

    def test_reconciliation_bridge_closes_and_stays_private(self):
        capture_date = timezone.localdate()
        _catalog(
            capture_date,
            [
                _standard_group(
                    key="A", capacity=10, members=(("100", "Sector A"),)
                ),
                _standard_group(
                    key="B", capacity=10, members=(("200", "Sector B"),)
                ),
                *_partitioned_3a_catalog(),
                {
                    "stable_key": "CO",
                    "display_name": "Centro Obstetrico",
                    "capacity": None,
                    "policy": CalculationPolicy.UNRATED,
                    "members": (("20", "CO Source"),),
                },
            ],
            algorithm_version="occupancy-v3",
        )
        run = _run()
        captured_at = _at(capture_date)
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="REC-A1",
            age_band="age_12_or_over", bed="BED-A1",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=1, patient_marker="REC-A1",
            age_band="age_12_or_over", bed="BED-A1",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=2, patient_marker="REC-A2",
            age_band="age_12_or_over", bed="BED-A2",
        )
        _snapshot(
            run, captured_at=captured_at, code="200", sector="Sector B",
            status=BedStatus.OCCUPIED, index=3, patient_marker="REC-B1",
            age_band="age_12_or_over", bed="BED-B1",
        )
        _snapshot(
            run, captured_at=captured_at, code="200", sector="Sector B",
            status=BedStatus.OCCUPIED, index=4, patient_marker="REC-B2",
            age_band="age_12_or_over", bed="BED-B1",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=5, patient_marker="REC-NOBED",
            age_band="age_12_or_over", bed="",
        )
        _snapshot(
            run, captured_at=captured_at, code="654", sector="3A Source",
            status=BedStatus.OCCUPIED, index=6, patient_marker="REC-3A",
            age_band="unknown", bed="3A-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="20", sector="CO Source",
            status=BedStatus.OCCUPIED, index=7, patient_marker="REC-CO",
            age_band="age_12_or_over", bed="CO-01",
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        reconciliation = measurement.physical_reconciliation_json

        raw = reconciliation["raw_occupied_rows"]
        bridge = (
            reconciliation["duplicate_occupied_rows"]
            + reconciliation["conflict_occupied_rows"]
            + reconciliation["unidentified_occupied_rows"]
            + reconciliation["unknown_age_3a_rows"]
            + reconciliation["unambiguous_occupied_outside_calculable"]
            + reconciliation["official_numerator"]
        )
        assert raw == 8
        assert bridge == raw
        assert reconciliation["duplicate_occupied_rows"] == 1
        assert reconciliation["conflict_occupied_rows"] == 2
        assert reconciliation["unidentified_occupied_rows"] == 1
        assert reconciliation["unknown_age_3a_rows"] == 1
        assert reconciliation["unambiguous_occupied_outside_calculable"] == 1
        assert reconciliation["official_numerator"] == 2
        assert reconciliation["positions_by_status"]["occupied"] == 4
        assert measurement.position_partial is True
        assert measurement.unknown_age_count == 1
        assert measurement.age_partial is True

        serialized = json.dumps(reconciliation)
        for marker in ("REC-", "BED-", "3A-01", "CO-01", "Sector"):
            assert marker not in serialized

    def test_hospital_availability_sums_positive_balances_without_compensation(self):
        capture_date = timezone.localdate()
        _catalog(
            capture_date,
            [
                _standard_group(
                    key="A", capacity=10, members=(("100", "Sector A"),)
                ),
                _standard_group(
                    key="B", capacity=10, members=(("200", "Sector B"),)
                ),
            ],
            algorithm_version="occupancy-v3",
        )
        run = _run()
        captured_at = _at(capture_date)
        for i in range(12):
            _snapshot(
                run, captured_at=captured_at, code="100", sector="Sector A",
                status=BedStatus.OCCUPIED, index=i, patient_marker=f"A-{i:02d}",
                age_band="age_12_or_over", bed=f"BED-A-{i:02d}",
            )
        for i in range(5):
            _snapshot(
                run, captured_at=captured_at, code="200", sector="Sector B",
                status=BedStatus.OCCUPIED, index=100 + i, patient_marker=f"B-{i:02d}",
                age_band="age_12_or_over", bed=f"BED-B-{i:02d}",
            )

        result = _materialize(run.pk)
        measurement = result.measurement
        groups = {g.stable_key: g for g in measurement.groups.all()}

        assert groups["A"].official_availability == 0
        assert groups["A"].exceeded_by == 2
        assert groups["B"].official_availability == 5
        assert groups["B"].exceeded_by == 0
        assert measurement.official_availability == 5
        assert measurement.exceeded_by == 2
        assert measurement.occupied_for_rate == 17

    def test_v3_catalog_dispatches_v3_without_hardcoded_dates(self):
        capture_date = timezone.localdate()
        _catalog(
            capture_date,
            [_standard_group()],
            algorithm_version="occupancy-v3",
        )
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="100",
            sector="Sector A",
        )

        result = _materialize(run.pk)

        assert result.measurement.algorithm_version == "occupancy-v3"
        assert result.measurement.position_partial is False
        assert result.measurement.physical_reconciliation_json[
            "official_numerator"
        ] == 0

    def test_v3_reexecution_is_idempotent_and_preserves_reconciliation(self):
        capture_date = timezone.localdate()
        _catalog(
            capture_date,
            [_standard_group(capacity=10)],
            algorithm_version="occupancy-v3",
        )
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="SYN-DUP",
            age_band="age_12_or_over",
            bed="BED-01",
        )
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="SYN-DUP",
            age_band="age_12_or_over",
            bed="BED-01",
        )

        first = _materialize(run.pk)
        first_json = dict(first.measurement.physical_reconciliation_json)
        first_occupied = first.measurement.groups.get(stable_key="A").occupied_count

        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=2,
            patient_marker="SYN-DUP",
            age_band="age_12_or_over",
            bed="BED-01",
        )
        second = _materialize(run.pk)
        second_occupied = second.measurement.groups.get(stable_key="A").occupied_count

        assert second.status == "existing"
        assert second.measurement.pk == first.measurement.pk
        assert second.measurement.physical_reconciliation_json == first_json
        assert second_occupied == first_occupied


@pytest.mark.django_db
class TestV3DailyEligibility:
    """R8: physically partial v3 measurements never enter official daily stats."""

    def _daily_models(self):
        models_module = importlib.import_module("apps.census.models")
        parent = getattr(models_module, "DailyOccupancySummary", None)
        child = getattr(models_module, "DailyGroupOccupancySummary", None)
        if parent is None or child is None:
            pytest.fail("daily occupancy summary schema is missing")
        return parent, child

    def test_physically_partial_v3_measurement_is_excluded_from_daily_stats(self):
        parent_model, child_model = self._daily_models()
        today = timezone.localdate()
        _catalog(
            today,
            [_standard_group(capacity=10)],
            algorithm_version="occupancy-v3",
        )
        run = _run()
        _snapshot(
            run,
            captured_at=_at(today, 8),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="REC-1",
            age_band="age_12_or_over",
            bed="BED-01",
        )
        _snapshot(
            run,
            captured_at=_at(today, 8),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="REC-2",
            age_band="age_12_or_over",
            bed="BED-01",
        )

        result = _materialize(run.pk)

        assert result.measurement.position_partial is True
        summary = parent_model.objects.get(local_date=today)
        assert summary.measurement_count == 1
        assert summary.eligible_measurement_count == 0
        assert summary.position_excluded_measurement_count == 1
        assert summary.age_excluded_measurement_count == 0
        assert summary.mean_occupied is None
        assert summary.min_occupied is None
        assert summary.max_occupied is None
        assert summary.mean_percentage is None
        assert summary.max_exceeded_by is None
        assert child_model.objects.filter(daily_summary=summary).count() == 0

    def test_mixed_day_keeps_position_reason_separate_from_age_reason(self):
        parent_model, _ = self._daily_models()
        today = timezone.localdate()
        _catalog(
            today,
            [_standard_group(capacity=10)],
            algorithm_version="occupancy-v3",
        )
        complete = _run()
        partial = _run()
        _snapshot(
            complete,
            captured_at=_at(today, 8),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="REC-OK",
            age_band="age_12_or_over",
            bed="BED-01",
        )
        _snapshot(
            partial,
            captured_at=_at(today, 20),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=1,
            patient_marker="REC-1",
            age_band="age_12_or_over",
            bed="BED-02",
        )
        _snapshot(
            partial,
            captured_at=_at(today, 20),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=2,
            patient_marker="REC-2",
            age_band="age_12_or_over",
            bed="BED-02",
        )
        _materialize(complete.pk)
        _materialize(partial.pk)

        summary = parent_model.objects.get(local_date=today)

        assert summary.measurement_count == 2
        assert summary.eligible_measurement_count == 1
        assert summary.position_excluded_measurement_count == 1
        assert summary.age_excluded_measurement_count == 0
        assert summary.mean_occupied == Decimal("1.00")
        assert summary.max_exceeded_by == 0


@pytest.mark.django_db
class TestV4TypedConflicts:
    """MOQA-S1 R1-R4: occupancy-v4 dispatched by catalog with typed conflicts.

    A synthetic catalog persisted directly in the test declares
    ``occupancy-v4``; materialization must apply position normalization with
    typed conflict classification instead of legacy row counting.
    """

    def _v4_catalog(self, groups=None, capture_date=None):
        return _catalog(
            capture_date or timezone.localdate(),
            groups or [_standard_group(capacity=10)],
            algorithm_version="occupancy-v4",
        )

    def test_v4_exact_duplicate_counts_one_position_before_typing(self):
        self._v4_catalog()
        run = _run()
        for i in range(2):
            _snapshot(
                run,
                captured_at=_at(timezone.localdate()),
                code="100",
                sector="Sector A",
                status=BedStatus.OCCUPIED,
                index=i,
                patient_marker="SYN-DUP",
                age_band="age_12_or_over",
                bed="BED-01",
            )

        result = _materialize(run.pk)
        measurement = result.measurement

        assert measurement.algorithm_version == "occupancy-v4"
        assert measurement.groups.get(stable_key="A").occupied_count == 1
        assert measurement.occupied_for_rate == 1
        reconciliation = measurement.physical_reconciliation_json
        assert reconciliation["schema_version"] == 2
        assert reconciliation["duplicate_occupied_extra_rows"] == 1
        assert reconciliation["counted_occupied_positions"] == 1
        assert reconciliation["official_numerator"] == 1
        assert measurement.quality_warning is False

    def test_v4_occupant_conflict_counts_one_position_without_winner(self):
        self._v4_catalog()
        run = _run()
        captured_at = _at(timezone.localdate())
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="REC-1",
            age_band="age_12_or_over", bed="BED-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=1, patient_marker="REC-2",
            age_band="age_12_or_over", bed="BED-01",
        )

        result = _materialize(run.pk)
        measurement = result.measurement

        assert measurement.groups.get(stable_key="A").occupied_count == 1
        assert measurement.occupied_for_rate == 1
        reconciliation = measurement.physical_reconciliation_json
        assert reconciliation["occupant_conflict_positions"] == 1
        assert reconciliation["occupant_conflict_extra_occupied_rows"] == 1
        assert reconciliation["counted_occupied_positions"] == 1
        assert measurement.quality_warning is True

    def test_v4_status_conflict_never_counts_and_has_no_winner(self):
        self._v4_catalog()
        run = _run()
        captured_at = _at(timezone.localdate())
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="REC-1",
            age_band="age_12_or_over", bed="BED-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.EMPTY, index=1, bed="BED-01",
        )

        result = _materialize(run.pk)
        measurement = result.measurement

        assert measurement.groups.get(stable_key="A").occupied_count == 0
        assert measurement.occupied_for_rate == 0
        reconciliation = measurement.physical_reconciliation_json
        assert reconciliation["status_conflict_positions"] == 1
        assert reconciliation["status_conflict_occupied_rows"] == 1
        assert reconciliation["counted_occupied_positions"] == 0
        assert measurement.quality_warning is True

    def test_v4_non_occupied_status_conflict_remains_warning_without_numerator_effect(self):
        self._v4_catalog()
        run = _run()
        captured_at = _at(timezone.localdate())
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.EMPTY, index=0, bed="BED-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.MAINTENANCE, index=1, bed="BED-01",
        )

        result = _materialize(run.pk)
        measurement = result.measurement

        assert measurement.occupied_for_rate == 0
        reconciliation = measurement.physical_reconciliation_json
        assert reconciliation["status_conflict_positions"] == 1
        assert reconciliation["status_conflict_occupied_rows"] == 0
        assert measurement.quality_warning is True

    def test_v4_age_conflict_in_partitioned_source_is_not_assigned(self):
        self._v4_catalog(_partitioned_3a_catalog())
        run = _run()
        captured_at = _at(timezone.localdate())
        _snapshot(
            run, captured_at=captured_at, code="654", sector="3A Source",
            status=BedStatus.OCCUPIED, index=0, patient_marker="ADULT",
            age_band="age_12_or_over", bed="3A-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="654", sector="3A Source",
            status=BedStatus.OCCUPIED, index=1, patient_marker="CHILD",
            age_band="under_12", bed="3A-01",
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        groups = {g.stable_key: g for g in measurement.groups.all()}

        assert groups["OBST-3A-ADULTO"].occupied_count == 0
        assert groups["OBST-3A-INFANTIL"].occupied_count == 0
        assert measurement.occupied_for_rate == 0
        reconciliation = measurement.physical_reconciliation_json
        assert reconciliation["age_conflict_positions"] == 1
        assert reconciliation["age_conflict_occupied_rows"] == 2
        assert measurement.quality_warning is True

    def test_v4_unknown_partition_position_is_not_assigned(self):
        self._v4_catalog(_partitioned_3a_catalog())
        run = _run()
        _snapshot(
            run,
            captured_at=_at(timezone.localdate()),
            code="654",
            sector="3A Source",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="UNK",
            age_band="unknown",
            bed="3A-01",
        )

        result = _materialize(run.pk)
        measurement = result.measurement

        assert measurement.occupied_for_rate == 0
        reconciliation = measurement.physical_reconciliation_json
        assert reconciliation["unknown_age_partition_positions"] == 1
        assert reconciliation["counted_occupied_positions"] == 0
        assert measurement.quality_warning is True

    def test_v4_non_partitioned_age_drift_keeps_occupancy_with_warning(self):
        self._v4_catalog()
        run = _run()
        captured_at = _at(timezone.localdate())
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="SAME",
            age_band="age_12_or_over", bed="BED-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=1, patient_marker="SAME",
            age_band="under_12", bed="BED-01",
        )

        result = _materialize(run.pk)
        measurement = result.measurement

        assert measurement.groups.get(stable_key="A").occupied_count == 1
        assert measurement.occupied_for_rate == 1
        reconciliation = measurement.physical_reconciliation_json
        assert reconciliation["age_metadata_drift_positions"] == 1
        assert measurement.quality_warning is True

    def test_v4_shared_record_in_distinct_beds_counts_two_positions(self):
        self._v4_catalog()
        run = _run()
        captured_at = _at(timezone.localdate())
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="SHARED",
            age_band="age_12_or_over", bed="BED-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=1, patient_marker="SHARED",
            age_band="age_12_or_over", bed="BED-02",
        )

        result = _materialize(run.pk)
        measurement = result.measurement

        assert measurement.groups.get(stable_key="A").occupied_count == 2
        assert measurement.physical_reconciliation_json["duplicate_extra_rows"] == 0

    def test_v4_occupied_without_bed_is_warning_and_out_of_numerator(self):
        self._v4_catalog()
        run = _run()
        _snapshot(
            run,
            captured_at=_at(timezone.localdate()),
            code="100",
            sector="Sector A",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="NO-BED",
            age_band="age_12_or_over",
            bed="",
        )

        result = _materialize(run.pk)
        measurement = result.measurement

        assert measurement.groups.get(stable_key="A").occupied_count == 0
        reconciliation = measurement.physical_reconciliation_json
        assert reconciliation["unidentified_occupied_rows"] == 1
        assert reconciliation["counted_occupied_positions"] == 0
        assert measurement.quality_warning is True


@pytest.mark.django_db
class TestV4ReconciliationSchema2:
    """MOQA-S1 R5: schema 2 closes both bridges and stays private."""

    def test_both_bridges_close_with_mixed_categories(self):
        capture_date = timezone.localdate()
        _catalog(
            capture_date,
            [
                _standard_group(
                    key="A", capacity=10, members=(("100", "Sector A"),)
                ),
                _standard_group(
                    key="B", capacity=10, members=(("200", "Sector B"),)
                ),
                *_partitioned_3a_catalog(),
                {
                    "stable_key": "PENDING",
                    "display_name": "Pending",
                    "capacity": 32,
                    "policy": CalculationPolicy.LINKED_SLOTS_PENDING,
                    "members": (("300", "Sector P"),),
                },
                {
                    "stable_key": "CO",
                    "display_name": "Centro Obstetrico",
                    "capacity": None,
                    "policy": CalculationPolicy.UNRATED,
                    "members": (("20", "CO Source"),),
                },
            ],
            algorithm_version="occupancy-v4",
        )
        run = _run()
        captured_at = _at(capture_date)
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="REC-A1",
            age_band="age_12_or_over", bed="BED-A1",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=1, patient_marker="REC-A1",
            age_band="age_12_or_over", bed="BED-A1",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=2, patient_marker="REC-A2",
            age_band="age_12_or_over", bed="BED-A2",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=3, patient_marker="REC-A3",
            age_band="age_12_or_over", bed="BED-A3",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=4, patient_marker="REC-A4",
            age_band="age_12_or_over", bed="BED-A3",
        )
        _snapshot(
            run, captured_at=captured_at, code="200", sector="Sector B",
            status=BedStatus.OCCUPIED, index=5, patient_marker="REC-B1",
            age_band="age_12_or_over", bed="BED-B1",
        )
        _snapshot(
            run, captured_at=captured_at, code="200", sector="Sector B",
            status=BedStatus.EMPTY, index=6, bed="BED-B1",
        )
        _snapshot(
            run, captured_at=captured_at, code="654", sector="3A Source",
            status=BedStatus.OCCUPIED, index=7, patient_marker="REC-3A-1",
            age_band="under_12", bed="3A-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="654", sector="3A Source",
            status=BedStatus.OCCUPIED, index=8, patient_marker="REC-3A-2",
            age_band="age_12_or_over", bed="3A-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="654", sector="3A Source",
            status=BedStatus.OCCUPIED, index=9, patient_marker="REC-3A-3",
            age_band="unknown", bed="3A-02",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=10, patient_marker="REC-NOBED",
            age_band="age_12_or_over", bed="",
        )
        _snapshot(
            run, captured_at=captured_at, code="20", sector="CO Source",
            status=BedStatus.OCCUPIED, index=11, patient_marker="REC-CO",
            age_band="age_12_or_over", bed="CO-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="300", sector="Sector P",
            status=BedStatus.OCCUPIED, index=12, patient_marker="REC-P",
            age_band="age_12_or_over", bed="P-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="999", sector="Unknown X",
            status=BedStatus.OCCUPIED, index=13, patient_marker="REC-X",
            age_band="age_12_or_over", bed="X-01",
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        reconciliation = measurement.physical_reconciliation_json

        assert reconciliation["schema_version"] == 2
        raw = reconciliation["raw_occupied_rows"]
        bridge1 = (
            reconciliation["duplicate_occupied_extra_rows"]
            + reconciliation["occupant_conflict_extra_occupied_rows"]
            + reconciliation["status_conflict_occupied_rows"]
            + reconciliation["age_conflict_occupied_rows"]
            + reconciliation["unidentified_occupied_rows"]
            + reconciliation["unknown_age_partition_positions"]
            + reconciliation["counted_occupied_positions"]
        )
        assert raw == 13
        assert bridge1 == raw
        bridge2 = (
            reconciliation["official_numerator"]
            + reconciliation["occupied_unrated_positions"]
            + reconciliation["occupied_unmapped_positions"]
            + reconciliation["occupied_linked_pending_positions"]
        )
        assert bridge2 == reconciliation["counted_occupied_positions"]
        assert reconciliation["counted_occupied_positions"] == 6
        assert reconciliation["official_numerator"] == 3
        assert reconciliation["occupied_unrated_positions"] == 1
        assert reconciliation["occupied_unmapped_positions"] == 1
        assert reconciliation["occupied_linked_pending_positions"] == 1
        assert reconciliation["age_conflict_positions"] == 1
        assert reconciliation["status_conflict_positions"] == 1
        assert measurement.quality_warning is True

        serialized = json.dumps(reconciliation)
        for marker in ("REC-", "BED-", "3A-", "CO-", "P-", "X-", "Sector"):
            assert marker not in serialized

    def test_v4_reconciliation_allowlist_and_recursive_privacy(self):
        capture_date = timezone.localdate()
        _catalog(
            capture_date,
            [_standard_group(capacity=10)],
            algorithm_version="occupancy-v4",
        )
        run = _run()
        captured_at = _at(capture_date)
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="PRIV-1",
            age_band="age_12_or_over", bed="PRIV-BED-1",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=1, patient_marker="PRIV-2",
            age_band="age_12_or_over", bed="PRIV-BED-1",
        )
        result = _materialize(run.pk)
        reconciliation = result.measurement.physical_reconciliation_json

        allowlist = _domain()._V4_RECONCILIATION_ALLOWLIST
        assert set(reconciliation) == set(allowlist)

        def walk(value):
            if isinstance(value, dict):
                for item in value.values():
                    walk(item)
            elif isinstance(value, str):
                for marker in ("PRIV-", "BED-", "Sector A", "100"):
                    assert marker not in value

        walk(reconciliation)
        assert all(
            isinstance(value, (int, bool))
            for value in reconciliation.values()
            if not isinstance(value, dict)
        )
        assert all(
            isinstance(value, int)
            for counts in reconciliation["positions_by_status"].values()
            for value in [counts]
        )

    def test_v4_unrated_policy_is_not_a_quality_warning(self):
        capture_date = timezone.localdate()
        _catalog(
            capture_date,
            [
                {
                    "stable_key": "CO",
                    "display_name": "Centro Obstetrico",
                    "capacity": None,
                    "policy": CalculationPolicy.UNRATED,
                    "members": (("20", "CO Source"),),
                },
            ],
            algorithm_version="occupancy-v4",
        )
        run = _run()
        _snapshot(
            run,
            captured_at=_at(capture_date),
            code="20",
            sector="CO Source",
            status=BedStatus.OCCUPIED,
            index=0,
            patient_marker="REC-CO",
            age_band="age_12_or_over",
            bed="CO-01",
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        reconciliation = measurement.physical_reconciliation_json

        assert reconciliation["occupied_unrated_positions"] == 1
        assert reconciliation["official_numerator"] == 0
        assert measurement.quality_warning is False

    def test_v4_unmapped_and_pending_stay_separate_and_unmapped_warns(self):
        capture_date = timezone.localdate()
        _catalog(
            capture_date,
            [
                {
                    "stable_key": "PENDING",
                    "display_name": "Pending",
                    "capacity": 32,
                    "policy": CalculationPolicy.LINKED_SLOTS_PENDING,
                    "members": (("300", "Sector P"),),
                },
            ],
            algorithm_version="occupancy-v4",
        )
        run = _run()
        captured_at = _at(capture_date)
        _snapshot(
            run, captured_at=captured_at, code="300", sector="Sector P",
            status=BedStatus.OCCUPIED, index=0, patient_marker="REC-P",
            age_band="age_12_or_over", bed="P-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="999", sector="Unknown X",
            status=BedStatus.OCCUPIED, index=1, patient_marker="REC-X",
            age_band="age_12_or_over", bed="X-01",
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        reconciliation = measurement.physical_reconciliation_json

        assert reconciliation["occupied_linked_pending_positions"] == 1
        assert reconciliation["occupied_unmapped_positions"] == 1
        assert reconciliation["official_numerator"] == 0
        assert measurement.quality_warning is True


@pytest.mark.django_db
class TestV4DailyEligibility:
    """MOQA-S1 R7-R8: every materialized v4 measurement is daily eligible."""

    def _daily_models(self):
        models_module = importlib.import_module("apps.census.models")
        parent = getattr(models_module, "DailyOccupancySummary", None)
        child = getattr(models_module, "DailyGroupOccupancySummary", None)
        if parent is None or child is None:
            pytest.fail("daily occupancy summary schema is missing")
        return parent, child

    def test_all_warning_v4_day_remains_eligible_and_statistical(self):
        parent_model, child_model = self._daily_models()
        today = timezone.localdate()
        _catalog(
            today,
            [_standard_group(capacity=10)],
            algorithm_version="occupancy-v4",
        )
        run = _run()
        captured_at = _at(today, 8)
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="REC-1",
            age_band="age_12_or_over", bed="BED-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=1, patient_marker="REC-2",
            age_band="age_12_or_over", bed="BED-01",
        )

        result = _materialize(run.pk)
        assert result.measurement.quality_warning is True

        summary = parent_model.objects.get(local_date=today)
        assert summary.measurement_count == 1
        assert summary.eligible_measurement_count == 1
        assert summary.quality_warning_measurement_count == 1
        assert summary.position_excluded_measurement_count == 0
        assert summary.age_excluded_measurement_count == 0
        assert summary.mean_occupied == Decimal("1.00")
        assert summary.min_occupied == 1
        assert summary.max_occupied == 1
        assert summary.max_exceeded_by == 0
        child = child_model.objects.get(daily_summary=summary, stable_key="A")
        assert child.mean_occupied == Decimal("1.00")
        assert child.measurement_count == 1

    def test_clean_and_warned_v4_measurements_both_contribute(self):
        parent_model, _ = self._daily_models()
        today = timezone.localdate()
        _catalog(
            today,
            [_standard_group(capacity=10)],
            algorithm_version="occupancy-v4",
        )
        clean = _run()
        warned = _run()
        _snapshot(
            clean, captured_at=_at(today, 8), code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="REC-CLEAN",
            age_band="age_12_or_over", bed="BED-01",
        )
        _snapshot(
            warned, captured_at=_at(today, 20), code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=1, patient_marker="REC-W1",
            age_band="age_12_or_over", bed="BED-02",
        )
        _snapshot(
            warned, captured_at=_at(today, 20), code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=2, patient_marker="REC-W2",
            age_band="age_12_or_over", bed="BED-02",
        )
        _materialize(clean.pk)
        _materialize(warned.pk)

        summary = parent_model.objects.get(local_date=today)
        assert summary.measurement_count == 2
        assert summary.eligible_measurement_count == 2
        assert summary.quality_warning_measurement_count == 1
        assert summary.mean_occupied == Decimal("1.00")
        assert summary.max_exceeded_by == 0

    def test_v3_partial_day_stays_excluded_without_new_counter(self):
        parent_model, _ = self._daily_models()
        today = timezone.localdate()
        _catalog(
            today,
            [_standard_group(capacity=10)],
            algorithm_version="occupancy-v3",
        )
        run = _run()
        captured_at = _at(today, 8)
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="REC-1",
            age_band="age_12_or_over", bed="BED-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=1, patient_marker="REC-2",
            age_band="age_12_or_over", bed="BED-01",
        )
        _materialize(run.pk)

        summary = parent_model.objects.get(local_date=today)
        assert summary.eligible_measurement_count == 0
        assert summary.position_excluded_measurement_count == 1
        assert summary.quality_warning_measurement_count == 0
        assert summary.mean_occupied is None

    def test_v4_availability_and_excess_remain_non_compensated(self):
        parent_model, _ = self._daily_models()
        today = timezone.localdate()
        _catalog(
            today,
            [
                _standard_group(
                    key="A", capacity=10, members=(("100", "Sector A"),)
                ),
                _standard_group(
                    key="B", capacity=10, members=(("200", "Sector B"),)
                ),
            ],
            algorithm_version="occupancy-v4",
        )
        run = _run()
        captured_at = _at(today, 8)
        for i in range(12):
            _snapshot(
                run, captured_at=captured_at, code="100", sector="Sector A",
                status=BedStatus.OCCUPIED, index=i, patient_marker=f"A-{i:02d}",
                age_band="age_12_or_over", bed=f"BED-A-{i:02d}",
            )
        for i in range(5):
            _snapshot(
                run, captured_at=captured_at, code="200", sector="Sector B",
                status=BedStatus.OCCUPIED, index=100 + i, patient_marker=f"B-{i:02d}",
                age_band="age_12_or_over", bed=f"BED-B-{i:02d}",
            )
        result = _materialize(run.pk)
        measurement = result.measurement
        groups = {g.stable_key: g for g in measurement.groups.all()}

        assert groups["A"].official_availability == 0
        assert groups["A"].exceeded_by == 2
        assert groups["B"].official_availability == 5
        assert groups["B"].exceeded_by == 0
        assert measurement.official_availability == 5
        assert measurement.exceeded_by == 2
        assert measurement.occupied_for_rate == 17
        assert measurement.occupancy_percentage == Decimal("85.00")
        assert measurement.quality_warning is False

    def test_v4_idempotent_reexecution_keeps_warning_and_summary(self):
        parent_model, _ = self._daily_models()
        today = timezone.localdate()
        _catalog(
            today,
            [_standard_group(capacity=10)],
            algorithm_version="occupancy-v4",
        )
        run = _run()
        captured_at = _at(today, 8)
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="REC-1",
            age_band="age_12_or_over", bed="BED-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=1, patient_marker="REC-2",
            age_band="age_12_or_over", bed="BED-01",
        )
        first = _materialize(run.pk)
        first_json = dict(first.measurement.physical_reconciliation_json)

        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=2, patient_marker="REC-3",
            age_band="age_12_or_over", bed="BED-01",
        )
        second = _materialize(run.pk)

        assert second.status == "existing"
        assert second.measurement.pk == first.measurement.pk
        assert second.measurement.physical_reconciliation_json == first_json
        assert second.measurement.quality_warning is True
        summary = parent_model.objects.get(local_date=today)
        assert summary.measurement_count == 1
        assert summary.quality_warning_measurement_count == 1

    def test_v4_warning_never_increments_historical_exclusion_counters(self):
        parent_model, _ = self._daily_models()
        today = timezone.localdate()
        _catalog(
            today,
            [_standard_group(capacity=10)],
            algorithm_version="occupancy-v4",
        )
        run = _run()
        captured_at = _at(today, 8)
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="REC-1",
            age_band="age_12_or_over", bed="BED-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=1, patient_marker="REC-2",
            age_band="age_12_or_over", bed="BED-01",
        )
        _materialize(run.pk)

        summary = parent_model.objects.get(local_date=today)
        assert summary.quality_warning_measurement_count == 1
        assert summary.age_excluded_measurement_count == 0
        assert summary.position_excluded_measurement_count == 0
        assert summary.eligible_measurement_count == 1


# ---------------------------------------------------------------------------
# CIPOO-S1: occupancy-v5 identified-patient counting.
#
# V5 ignores bed identity for the official numerator, deduplicates the
# normalized textual record within each official group, keeps leading zeros
# significant and classifies every occupied row as an identified patient,
# incomplete identity or operational state. The 3A partition deduplicates
# before choosing Adulto/Infantil with a literal ``RN`` prefix fallback.
# Reconciliation schema 3 is closed, aggregate and private.
# ---------------------------------------------------------------------------


def _v5_catalog(capture_date=None, groups=None):
    """Synthetic catalog declaring ``occupancy-v5`` patient semantics."""
    return _catalog(
        capture_date or timezone.localdate(),
        groups or [_standard_group(capacity=10)],
        algorithm_version="occupancy-v5",
    )


def _raw_snapshot(
    run: IngestionRun,
    *,
    code: str,
    sector: str,
    status: str = BedStatus.OCCUPIED,
    record: str = "",
    nome: str = "",
    bed: str = "BED-01",
    age_band: str = "unknown",
    index: int = 0,
    captured_at: datetime | None = None,
) -> CensusSnapshot:
    """Create one census row with full control over identity fields."""
    return CensusSnapshot.objects.create(
        ingestion_run=run,
        captured_at=captured_at or _at(timezone.localdate()),
        setor_codigo=code,
        setor=sector,
        leito=bed,
        prontuario=record,
        nome=nome,
        especialidade="SYN",
        bed_status=status,
        age_band=age_band,
    )


@pytest.mark.django_db
class TestV5Identity:
    """CIPOO-S1 R1/R2: valid textual identity and group-scoped dedup."""

    def test_v5_leading_zeros_are_textual_and_trimmed(self):
        _, child_model = _measurement_models()
        _v5_catalog()
        run = _run()
        captured_at = _at(timezone.localdate())
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="  0012345  ",
            age_band="age_12_or_over", bed="BED-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=1, patient_marker="  0012345  ",
            age_band="age_12_or_over", bed="BED-02",
        )
        # A second textual record that an integer conversion would merge.
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=2, patient_marker="12345",
            age_band="age_12_or_over", bed="BED-03",
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        reconciliation = measurement.physical_reconciliation_json

        assert measurement.algorithm_version == "occupancy-v5"
        assert reconciliation["schema_version"] == 3
        assert child_model.objects.get(
            measurement=measurement
        ).occupied_count == 2
        assert measurement.occupied_for_rate == 2
        assert reconciliation["valid_identity_rows"] == 3
        assert reconciliation["duplicate_identity_rows_within_group"] == 1

    def test_v5_incomplete_identity_rows_are_aggregate_only(self):
        _v5_catalog()
        run = _run()
        captured_at = _at(timezone.localdate())
        _raw_snapshot(
            run, code="100", sector="Sector A", record="A12345",
            nome="PACIENTE ALFA", bed="BED-01", captured_at=captured_at,
        )
        _raw_snapshot(
            run, code="100", sector="Sector A", record="12345",
            nome="", bed="BED-02", captured_at=captured_at,
        )
        _raw_snapshot(
            run, code="100", sector="Sector A", record="",
            nome="PACIENTE SEM RECORD", bed="BED-03", captured_at=captured_at,
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        reconciliation = measurement.physical_reconciliation_json

        assert reconciliation["schema_version"] == 3
        assert reconciliation["valid_identity_rows"] == 0
        assert reconciliation["incomplete_identity_rows"] == 3
        assert measurement.groups.get(stable_key="A").occupied_count == 0
        assert measurement.occupied_for_rate == 0

    def test_v5_operational_markers_are_not_patients(self):
        _v5_catalog()
        run = _run()
        captured_at = _at(timezone.localdate())
        markers = ["DESOCUPADO", "VAZIO", "LIMPEZA", "RESERVA INTERNA", "ISOLAMENTO"]
        for index, marker in enumerate(markers):
            _raw_snapshot(
                run, code="100", sector="Sector A", record=f"9{index:04d}",
                nome=marker, bed=f"BED-{index:02d}", captured_at=captured_at,
            )

        result = _materialize(run.pk)
        measurement = result.measurement
        reconciliation = measurement.physical_reconciliation_json

        assert reconciliation["schema_version"] == 3
        assert reconciliation["valid_identity_rows"] == 0
        assert reconciliation["operational_rows_by_status"] == {
            "occupied": 0,
            "empty": 2,
            "maintenance": 1,
            "reserved": 1,
            "isolation": 1,
        }
        assert measurement.groups.get(stable_key="A").occupied_count == 0

    def test_v5_patient_without_bed_counts(self):
        _v5_catalog()
        run = _run()
        _snapshot(
            run, captured_at=_at(timezone.localdate()), code="100",
            sector="Sector A", status=BedStatus.OCCUPIED, index=0,
            patient_marker="12345", age_band="age_12_or_over", bed="",
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        reconciliation = measurement.physical_reconciliation_json

        assert reconciliation["schema_version"] == 3
        assert measurement.groups.get(stable_key="A").occupied_count == 1
        assert reconciliation["patients_without_bed_count"] == 1
        assert measurement.quality_warning is False

    def test_v5_two_patients_sharing_one_bed_count_two(self):
        _v5_catalog()
        run = _run()
        captured_at = _at(timezone.localdate())
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="11111",
            age_band="age_12_or_over", bed="BED-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=1, patient_marker="22222",
            age_band="age_12_or_over", bed="BED-01",
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        reconciliation = measurement.physical_reconciliation_json

        assert reconciliation["schema_version"] == 3
        assert measurement.groups.get(stable_key="A").occupied_count == 2
        assert reconciliation["duplicate_identity_rows_within_group"] == 0

    def test_v5_shared_group_deduplicates_across_source_codes(self):
        _v5_catalog(
            groups=[
                _standard_group(
                    key="ENF-2B-CARD",
                    capacity=15,
                    members=(("719", "Cardio A"), ("2156", "Cardio B")),
                )
            ]
        )
        run = _run()
        captured_at = _at(timezone.localdate())
        _snapshot(
            run, captured_at=captured_at, code="719", sector="Cardio A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="50001",
            age_band="age_12_or_over", bed="CARD-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="2156", sector="Cardio B",
            status=BedStatus.OCCUPIED, index=1, patient_marker="50001",
            age_band="age_12_or_over", bed="CARD-02",
        )
        _snapshot(
            run, captured_at=captured_at, code="2156", sector="Cardio B",
            status=BedStatus.OCCUPIED, index=2, patient_marker="50002",
            age_band="age_12_or_over", bed="CARD-03",
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        reconciliation = measurement.physical_reconciliation_json

        assert reconciliation["schema_version"] == 3
        child = measurement.groups.get(stable_key="ENF-2B-CARD")
        assert child.occupied_count == 2
        assert reconciliation["valid_identity_rows"] == 3
        assert reconciliation["duplicate_identity_rows_within_group"] == 1
        assert measurement.occupied_for_rate == 2

    def test_v5_same_record_in_different_groups_counts_in_each(self):
        _v5_catalog(
            groups=[
                _standard_group(
                    key="A", capacity=10, members=(("100", "Sector A"),)
                ),
                _standard_group(
                    key="B", capacity=10, members=(("200", "Sector B"),)
                ),
            ]
        )
        run = _run()
        captured_at = _at(timezone.localdate())
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="70001",
            age_band="age_12_or_over", bed="A-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="200", sector="Sector B",
            status=BedStatus.OCCUPIED, index=1, patient_marker="70001",
            age_band="age_12_or_over", bed="B-01",
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        reconciliation = measurement.physical_reconciliation_json

        assert reconciliation["schema_version"] == 3
        groups = {g.stable_key: g for g in measurement.groups.all()}
        assert groups["A"].occupied_count == 1
        assert groups["B"].occupied_count == 1
        assert measurement.occupied_for_rate == 2
        assert reconciliation["cross_group_record_count"] == 1
        assert measurement.quality_warning is True

    def test_v5_name_variants_count_one_patient(self):
        _v5_catalog()
        run = _run()
        captured_at = _at(timezone.localdate())
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="80001",
            age_band="age_12_or_over", bed="BED-01",
        )
        _raw_snapshot(
            run, code="100", sector="Sector A", record="80001",
            nome="Maria Silva", bed="BED-02", captured_at=captured_at,
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        reconciliation = measurement.physical_reconciliation_json

        assert reconciliation["schema_version"] == 3
        assert measurement.groups.get(stable_key="A").occupied_count == 1
        assert reconciliation["name_variant_patient_count"] == 1
        assert measurement.quality_warning is True


@pytest.mark.django_db
class TestV5AgePartition3A:
    """CIPOO-S1 R3: 3A deduplicates before partition with RN fallback."""

    def test_v5_reliable_child_band_wins_over_unknown_lines(self):
        _v5_catalog(groups=_partitioned_3a_catalog())
        run = _run()
        captured_at = _at(timezone.localdate())
        _snapshot(
            run, captured_at=captured_at, code="654", sector="3A Source",
            status=BedStatus.OCCUPIED, index=0, patient_marker="30001",
            age_band="under_12", bed="3A-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="654", sector="3A Source",
            status=BedStatus.OCCUPIED, index=1, patient_marker="30001",
            age_band="unknown", bed="3A-02",
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        groups = {g.stable_key: g for g in measurement.groups.all()}
        reconciliation = measurement.physical_reconciliation_json

        assert reconciliation["schema_version"] == 3
        assert groups["OBST-3A-INFANTIL"].occupied_count == 1
        assert groups["OBST-3A-ADULTO"].occupied_count == 0
        assert reconciliation["rn_fallback_patient_count"] == 0
        assert reconciliation["non_rn_fallback_patient_count"] == 0

    def test_v5_reliable_adult_band_wins(self):
        _v5_catalog(groups=_partitioned_3a_catalog())
        run = _run()
        _snapshot(
            run, captured_at=_at(timezone.localdate()), code="654",
            sector="3A Source", status=BedStatus.OCCUPIED, index=0,
            patient_marker="30002", age_band="age_12_or_over", bed="3A-01",
        )
        _snapshot(
            run, captured_at=_at(timezone.localdate()), code="654",
            sector="3A Source", status=BedStatus.OCCUPIED, index=1,
            patient_marker="30002", age_band="unknown", bed="3A-02",
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        groups = {g.stable_key: g for g in measurement.groups.all()}
        reconciliation = measurement.physical_reconciliation_json

        assert reconciliation["schema_version"] == 3
        assert groups["OBST-3A-ADULTO"].occupied_count == 1
        assert groups["OBST-3A-INFANTIL"].occupied_count == 0
        assert reconciliation["rn_fallback_patient_count"] == 0
        assert reconciliation["non_rn_fallback_patient_count"] == 0

    def test_v5_unknown_age_with_rn_prefix_is_infantil(self):
        _v5_catalog(groups=_partitioned_3a_catalog())
        run = _run()
        _raw_snapshot(
            run, code="654", sector="3A Source", record="31001",
            nome="RN DE MARIA", bed="3A-01",
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        groups = {g.stable_key: g for g in measurement.groups.all()}
        reconciliation = measurement.physical_reconciliation_json

        assert reconciliation["schema_version"] == 3
        assert groups["OBST-3A-INFANTIL"].occupied_count == 1
        assert groups["OBST-3A-ADULTO"].occupied_count == 0
        assert reconciliation["rn_fallback_patient_count"] == 1
        assert reconciliation["non_rn_fallback_patient_count"] == 0
        assert measurement.quality_warning is True

    def test_v5_unknown_age_without_rn_prefix_is_adulto(self):
        _v5_catalog(groups=_partitioned_3a_catalog())
        run = _run()
        _raw_snapshot(
            run, code="654", sector="3A Source", record="31002",
            nome="JOAO PEREIRA", bed="3A-01",
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        groups = {g.stable_key: g for g in measurement.groups.all()}
        reconciliation = measurement.physical_reconciliation_json

        assert reconciliation["schema_version"] == 3
        assert groups["OBST-3A-ADULTO"].occupied_count == 1
        assert groups["OBST-3A-INFANTIL"].occupied_count == 0
        assert reconciliation["rn_fallback_patient_count"] == 0
        assert reconciliation["non_rn_fallback_patient_count"] == 1
        assert measurement.quality_warning is True

    def test_v5_conflicting_reliable_bands_fallback_by_literal_prefix(self):
        _v5_catalog(groups=_partitioned_3a_catalog())
        run = _run()
        captured_at = _at(timezone.localdate())
        # Record 32001: one under_12 row and one age_12_or_over row; name RN.
        _raw_snapshot(
            run, code="654", sector="3A Source", record="32001",
            nome="RN BEBE", age_band="under_12", bed="3A-01",
            captured_at=captured_at,
        )
        _raw_snapshot(
            run, code="654", sector="3A Source", record="32001",
            nome="RN BEBE", age_band="age_12_or_over", bed="3A-02",
            captured_at=captured_at,
        )
        # Record 32002: same conflict but a non-RN name goes to Adulto.
        _raw_snapshot(
            run, code="654", sector="3A Source", record="32002",
            nome="PAI DO BEBE", age_band="under_12", bed="3A-03",
            captured_at=captured_at,
        )
        _raw_snapshot(
            run, code="654", sector="3A Source", record="32002",
            nome="PAI DO BEBE", age_band="age_12_or_over", bed="3A-04",
            captured_at=captured_at,
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        groups = {g.stable_key: g for g in measurement.groups.all()}
        reconciliation = measurement.physical_reconciliation_json

        assert reconciliation["schema_version"] == 3
        assert groups["OBST-3A-INFANTIL"].occupied_count == 1
        assert groups["OBST-3A-ADULTO"].occupied_count == 1
        assert reconciliation["age_conflict_fallback_patient_count"] == 2
        assert reconciliation["rn_fallback_patient_count"] == 0
        assert reconciliation["non_rn_fallback_patient_count"] == 0
        assert measurement.quality_warning is True

    def test_v5_rn_dot_is_not_the_literal_rn_prefix(self):
        _v5_catalog(groups=_partitioned_3a_catalog())
        run = _run()
        _raw_snapshot(
            run, code="654", sector="3A Source", record="31003",
            nome="R.N. DA SILVA", bed="3A-01",
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        groups = {g.stable_key: g for g in measurement.groups.all()}
        reconciliation = measurement.physical_reconciliation_json

        assert reconciliation["schema_version"] == 3
        assert groups["OBST-3A-ADULTO"].occupied_count == 1
        assert groups["OBST-3A-INFANTIL"].occupied_count == 0
        assert reconciliation["non_rn_fallback_patient_count"] == 1

    def test_v5_deduplicates_before_partition(self):
        _v5_catalog(groups=_partitioned_3a_catalog())
        run = _run()
        captured_at = _at(timezone.localdate())
        for index in range(2):
            _snapshot(
                run, captured_at=captured_at, code="654", sector="3A Source",
                status=BedStatus.OCCUPIED, index=index,
                patient_marker="33001", age_band="unknown", bed=f"3A-{index:02d}",
            )
        _snapshot(
            run, captured_at=captured_at, code="654", sector="3A Source",
            status=BedStatus.OCCUPIED, index=2, patient_marker="33001",
            age_band="under_12", bed="3A-10",
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        groups = {g.stable_key: g for g in measurement.groups.all()}
        reconciliation = measurement.physical_reconciliation_json

        assert reconciliation["schema_version"] == 3
        assert groups["OBST-3A-INFANTIL"].occupied_count == 1
        assert groups["OBST-3A-ADULTO"].occupied_count == 0
        assert reconciliation["valid_identity_rows"] == 3
        assert reconciliation["duplicate_identity_rows_within_group"] == 2
        assert measurement.occupied_for_rate == 1


@pytest.mark.django_db
class TestV5PolicyAndArithmetic:
    """CIPOO-S1 R4: unrated, balance/excess and uncapped percentage."""

    def test_v5_unrated_co_lists_patients_without_official_rate(self):
        _v5_catalog(
            groups=[
                _standard_group(
                    key="A", capacity=10, members=(("100", "Sector A"),)
                ),
                {
                    "stable_key": "CO",
                    "display_name": "Centro Obstetrico",
                    "capacity": None,
                    "policy": CalculationPolicy.UNRATED,
                    "members": (("20", "CO Source"), ("1110", "CO 2")),
                },
            ]
        )
        run = _run()
        captured_at = _at(timezone.localdate())
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="61001",
            age_band="age_12_or_over", bed="A-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="20", sector="CO Source",
            status=BedStatus.OCCUPIED, index=1, patient_marker="62001",
            age_band="age_12_or_over", bed="CO-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="1110", sector="CO 2",
            status=BedStatus.OCCUPIED, index=2, patient_marker="62001",
            age_band="age_12_or_over", bed="CO-02",
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        reconciliation = measurement.physical_reconciliation_json

        assert reconciliation["schema_version"] == 3
        co = measurement.groups.get(stable_key="CO")
        assert co.calculation_policy == "unrated"
        assert co.calculation_status == "unrated"
        assert co.official_capacity is None
        assert co.occupied_count is None
        assert co.occupancy_percentage is None
        assert co.exceeded_by is None
        assert co.status_counts_json["occupied"] == 1
        assert measurement.groups.get(stable_key="A").occupied_count == 1
        assert measurement.occupied_for_rate == 1
        assert reconciliation["unrated_identified_patients"] == 1

    def test_v5_balance_excess_and_percentage_over_100(self):
        _v5_catalog(
            groups=[
                _standard_group(
                    key="A", capacity=8, members=(("100", "Sector A"),)
                ),
                _standard_group(
                    key="B", capacity=10, members=(("200", "Sector B"),)
                ),
            ]
        )
        run = _run()
        captured_at = _at(timezone.localdate())
        for index in range(10):
            _snapshot(
                run, captured_at=captured_at, code="100", sector="Sector A",
                status=BedStatus.OCCUPIED, index=index,
                patient_marker=f"7{index:04d}", age_band="age_12_or_over",
                bed=f"A-{index:02d}",
            )
        for index in range(4):
            _snapshot(
                run, captured_at=captured_at, code="200", sector="Sector B",
                status=BedStatus.OCCUPIED, index=100 + index,
                patient_marker=f"8{index:04d}", age_band="age_12_or_over",
                bed=f"B-{index:02d}",
            )

        result = _materialize(run.pk)
        measurement = result.measurement
        groups = {g.stable_key: g for g in measurement.groups.all()}

        assert groups["A"].occupied_count == 10
        assert groups["A"].occupancy_percentage == Decimal("125.00")
        assert groups["A"].exceeded_by == 2
        assert groups["A"].official_availability == 0
        assert groups["B"].occupied_count == 4
        assert groups["B"].official_availability == 6
        assert groups["B"].exceeded_by == 0
        assert measurement.occupied_for_rate == 14
        assert measurement.occupancy_percentage == Decimal("77.78")
        assert measurement.official_availability == 6
        assert measurement.exceeded_by == 2

    def test_v5_operational_states_do_not_alter_rate_or_capacity(self):
        _v5_catalog()
        run = _run()
        captured_at = _at(timezone.localdate())
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="91001",
            age_band="age_12_or_over", bed="BED-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=1, patient_marker="91002",
            age_band="age_12_or_over", bed="BED-02",
        )
        for index, status in enumerate(
            [BedStatus.EMPTY, BedStatus.MAINTENANCE, BedStatus.RESERVED, BedStatus.ISOLATION],
            start=2,
        ):
            _snapshot(
                run, captured_at=captured_at, code="100", sector="Sector A",
                status=status, index=index,
            )

        result = _materialize(run.pk)
        measurement = result.measurement
        reconciliation = measurement.physical_reconciliation_json
        child = measurement.groups.get(stable_key="A")

        assert reconciliation["schema_version"] == 3
        assert child.occupied_count == 2
        assert child.occupancy_percentage == Decimal("20.00")
        assert child.official_availability == 8
        assert child.exceeded_by == 0
        assert child.status_counts_json == {
            "occupied": 2,
            "empty": 1,
            "maintenance": 1,
            "reserved": 1,
            "isolation": 1,
        }
        assert reconciliation["operational_rows_by_status"] == {
            "occupied": 0,
            "empty": 1,
            "maintenance": 1,
            "reserved": 1,
            "isolation": 1,
        }
        assert measurement.quality_warning is False


@pytest.mark.django_db
class TestV5ReconciliationAndPrivacy:
    """CIPOO-S1 R5: closed schema 3 bridge without row-level identity."""

    def test_v5_bridge_closes_with_mixed_categories(self):
        _v5_catalog(
            groups=[
                _standard_group(
                    key="A", capacity=10, members=(("100", "Sector A"),)
                ),
                _standard_group(
                    key="B", capacity=10, members=(("200", "Sector B"),)
                ),
                *_partitioned_3a_catalog(),
                {
                    "stable_key": "PENDING",
                    "display_name": "Pending",
                    "capacity": 32,
                    "policy": CalculationPolicy.LINKED_SLOTS_PENDING,
                    "members": (("300", "Sector P"),),
                },
                {
                    "stable_key": "CO",
                    "display_name": "Centro Obstetrico",
                    "capacity": None,
                    "policy": CalculationPolicy.UNRATED,
                    "members": (("20", "CO Source"),),
                },
            ]
        )
        run = _run()
        captured_at = _at(timezone.localdate())
        rows = [
            ("100", "Sector A", "10001", "MARIA A", "BED-A1"),
            ("100", "Sector A", "10001", "MARIA A VARIANTE", "BED-A1"),
            ("100", "Sector A", "10002", "MARIA B", "BED-A2"),
            ("100", "Sector A", "10003", "SEM LEITO", ""),
            ("100", "Sector A", "10004", "MARIA X", "BED-A3"),
            ("100", "Sector A", "", "", "BED-A4"),
            ("200", "Sector B", "20001", "JOAO B", "BED-B1"),
            ("200", "Sector B", "20001", "JOAO B", "BED-B2"),
            ("654", "3A Source", "30001", "RN BEBE", "3A-01"),
            ("654", "3A Source", "30002", "PAI DO BEBE", "3A-02"),
            ("20", "CO Source", "40001", "MAE CO", "CO-01"),
            ("300", "Sector P", "50001", "PENDENTE", "P-01"),
            ("999", "Unknown X", "10004", "MARIA X", "X-01"),
            ("100", "Sector A", "X123", "PARCIAL", "BED-A5"),
        ]
        for index, (code, sector, record, nome, bed) in enumerate(rows):
            status = BedStatus.EMPTY if record == "" else BedStatus.OCCUPIED
            band = (
                "unknown"
                if record == "30001"
                else "age_12_or_over"
            )
            _raw_snapshot(
                run, code=code, sector=sector, status=status, record=record,
                nome=nome, bed=bed, age_band=band, index=index,
                captured_at=captured_at,
            )

        result = _materialize(run.pk)
        measurement = result.measurement
        reconciliation = measurement.physical_reconciliation_json

        assert reconciliation["schema_version"] == 3
        valid = reconciliation["valid_identity_rows"]
        bridge = (
            reconciliation["duplicate_identity_rows_within_group"]
            + reconciliation["standard_identified_patients"]
            + reconciliation["unrated_identified_patients"]
            + reconciliation["linked_pending_identified_patients"]
            + reconciliation["unmapped_identified_patients"]
        )
        assert valid == 12
        assert bridge == valid
        assert reconciliation["duplicate_identity_rows_within_group"] == 2
        assert reconciliation["standard_identified_patients"] == 7
        assert reconciliation["unrated_identified_patients"] == 1
        assert reconciliation["linked_pending_identified_patients"] == 1
        assert reconciliation["unmapped_identified_patients"] == 1
        assert reconciliation["incomplete_identity_rows"] == 1
        assert reconciliation["cross_group_record_count"] == 1
        assert reconciliation["name_variant_patient_count"] == 1
        assert reconciliation["rn_fallback_patient_count"] == 1
        assert reconciliation["non_rn_fallback_patient_count"] == 0
        assert reconciliation["age_conflict_fallback_patient_count"] == 0
        assert reconciliation["patients_without_bed_count"] == 1
        assert reconciliation["operational_rows_by_status"]["empty"] == 1
        assert measurement.quality_warning is True

        groups = {g.stable_key: g for g in measurement.groups.all()}
        assert groups["A"].occupied_count == 4
        assert groups["B"].occupied_count == 1
        assert groups["OBST-3A-INFANTIL"].occupied_count == 1
        assert groups["OBST-3A-ADULTO"].occupied_count == 1
        assert measurement.occupied_for_rate == 7
        assert measurement.known_capacity == 100
        assert measurement.calculable_capacity == 68

    def test_v5_reconciliation_allowlist_and_recursive_privacy(self):
        _v5_catalog()
        run = _run()
        captured_at = _at(timezone.localdate())
        _raw_snapshot(
            run, code="100", sector="Sector A", record="99991",
            nome="PRIV NOME", bed="PRIV-BED-1", captured_at=captured_at,
        )
        _raw_snapshot(
            run, code="100", sector="Sector A", record="99992",
            nome="PRIV NOME 2", bed="PRIV-BED-1", captured_at=captured_at,
        )
        result = _materialize(run.pk)
        reconciliation = result.measurement.physical_reconciliation_json

        allowlist = _domain()._V5_RECONCILIATION_ALLOWLIST
        assert set(reconciliation) == set(allowlist)

        def walk(value):
            if isinstance(value, dict):
                for item in value.values():
                    walk(item)
            elif isinstance(value, str):
                for marker in ("PRIV", "BED", "Sector A", "100", "9999"):
                    assert marker not in value

        walk(reconciliation)
        assert all(
            isinstance(value, (int, bool))
            for value in reconciliation.values()
            if not isinstance(value, dict)
        )
        assert all(
            isinstance(value, int)
            for value in reconciliation["operational_rows_by_status"].values()
        )


@pytest.mark.django_db
class TestV5DailyEligibility:
    """CIPOO-S1 R6: every materialized v5 measurement is daily-eligible."""

    def _daily_models(self):
        models_module = importlib.import_module("apps.census.models")
        parent = getattr(models_module, "DailyOccupancySummary", None)
        child = getattr(models_module, "DailyGroupOccupancySummary", None)
        if parent is None or child is None:
            pytest.fail("daily occupancy summary schema is missing")
        return parent, child

    def test_v5_clean_and_warned_measurements_both_contribute(self):
        parent_model, _ = self._daily_models()
        today = timezone.localdate()
        _v5_catalog(capture_date=today)
        clean = _run()
        warned = _run()
        _snapshot(
            clean, captured_at=_at(today, 8), code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="10001",
            age_band="age_12_or_over", bed="BED-01",
        )
        _snapshot(
            warned, captured_at=_at(today, 20), code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=1, patient_marker="10002",
            age_band="age_12_or_over", bed="BED-02",
        )
        _raw_snapshot(
            warned, code="100", sector="Sector A", record="X123",
            nome="PARCIAL", bed="BED-03", captured_at=_at(today, 20),
        )
        _materialize(clean.pk)
        _materialize(warned.pk)

        summary = parent_model.objects.get(local_date=today)
        assert summary.measurement_count == 2
        assert summary.eligible_measurement_count == 2
        assert summary.quality_warning_measurement_count == 1
        assert summary.age_excluded_measurement_count == 0
        assert summary.position_excluded_measurement_count == 0
        assert summary.mean_occupied == Decimal("1.00")
        assert summary.min_occupied == 1
        assert summary.max_occupied == 1
        assert summary.max_exceeded_by == 0

    def test_v5_all_warning_day_remains_observable(self):
        parent_model, _ = self._daily_models()
        today = timezone.localdate()
        _v5_catalog(capture_date=today)
        run = _run()
        _snapshot(
            run, captured_at=_at(today, 8), code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="10003",
            age_band="age_12_or_over", bed="BED-01",
        )
        _raw_snapshot(
            run, code="100", sector="Sector A", record="X999",
            nome="PARCIAL", bed="BED-02", captured_at=_at(today, 8),
        )
        result = _materialize(run.pk)
        assert result.measurement.quality_warning is True

        summary = parent_model.objects.get(local_date=today)
        assert summary.measurement_count == 1
        assert summary.eligible_measurement_count == 1
        assert summary.quality_warning_measurement_count == 1
        assert summary.mean_occupied == Decimal("1.00")
        assert summary.mean_percentage == Decimal("10.00")

    def test_v5_idempotent_reexecution_does_not_double_count_warning(self):
        parent_model, _ = self._daily_models()
        today = timezone.localdate()
        _v5_catalog(capture_date=today)
        run = _run()
        _snapshot(
            run, captured_at=_at(today, 8), code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="10004",
            age_band="age_12_or_over", bed="BED-01",
        )
        _raw_snapshot(
            run, code="100", sector="Sector A", record="X777",
            nome="PARCIAL", bed="BED-02", captured_at=_at(today, 8),
        )
        first = _materialize(run.pk)
        summary = parent_model.objects.get(local_date=today)
        original = (summary.measurement_count, summary.quality_warning_measurement_count)

        second = _materialize(run.pk)
        summary.refresh_from_db()

        assert first.status == "created"
        assert second.status == "existing"
        assert second.measurement.pk == first.measurement.pk
        assert (
            summary.measurement_count,
            summary.quality_warning_measurement_count,
        ) == original


@pytest.mark.django_db
class TestV5RegressionAndClinicalFlow:
    """CIPOO-S1 R7: v4 and clinical processing remain untouched."""

    def test_v4_semantics_remain_unchanged_with_v5_support(self):
        capture_date = timezone.localdate()
        _catalog(
            capture_date,
            [_standard_group(capacity=10)],
            algorithm_version="occupancy-v4",
        )
        run = _run()
        captured_at = _at(capture_date)
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="REC-1",
            age_band="age_12_or_over", bed="BED-01",
        )
        _snapshot(
            run, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=1, patient_marker="REC-2",
            age_band="age_12_or_over", bed="BED-01",
        )

        result = _materialize(run.pk)
        measurement = result.measurement
        reconciliation = measurement.physical_reconciliation_json

        assert measurement.algorithm_version == "occupancy-v4"
        assert reconciliation["schema_version"] == 2
        assert measurement.groups.get(stable_key="A").occupied_count == 1
        assert reconciliation["occupant_conflict_positions"] == 1
        assert measurement.quality_warning is True

    def test_v5_warnings_and_missing_beds_do_not_block_clinical_flow(self):
        today = timezone.localdate()
        _v5_catalog(capture_date=today)
        first = _run()
        captured_at = _at(today, 8)
        _snapshot(
            first, captured_at=captured_at, code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="11001",
            age_band="age_12_or_over", bed="",
        )
        _raw_snapshot(
            first, code="100", sector="Sector A", record="X555",
            nome="PARCIAL", bed="BED-01", captured_at=captured_at,
        )

        result = _materialize(first.pk)
        measurement = result.measurement
        first.refresh_from_db()

        assert result.status == "created"
        assert measurement.quality_warning is True
        assert measurement.groups.get(stable_key="A").occupied_count == 1
        assert first.status == "succeeded"

        # The same census pipeline can still materialize a following run.
        second = _run()
        _snapshot(
            second, captured_at=_at(today, 20), code="100", sector="Sector A",
            status=BedStatus.OCCUPIED, index=0, patient_marker="11002",
            age_band="age_12_or_over", bed="BED-02",
        )
        next_result = _materialize(second.pk)
        assert next_result.status == "created"
        assert next_result.measurement.occupied_for_rate == 1
