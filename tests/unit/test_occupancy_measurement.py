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
) -> CensusSnapshot:
    return CensusSnapshot.objects.create(
        ingestion_run=run,
        captured_at=captured_at,
        setor_codigo=code,
        setor=sector,
        leito=f"BED-{code or 'BLANK'}-{index:03d}",
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


def _catalog(effective_from: date, groups: list[dict]) -> CapacityCatalogVersion:
    catalog = CapacityCatalogVersion.objects.create(
        effective_from=effective_from,
        source_reference="synthetic occupancy test catalog",
        source_sha256=(f"{effective_from:%Y%m%d}" + "a" * 64)[:64],
        schema_version="1.0",
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
