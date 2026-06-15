"""Tests for apps.census.flow_service — S1 domain aggregation service."""

from __future__ import annotations

from datetime import date, datetime

import pytest
from django.utils import timezone

from apps.admissions.models import DailyAdmissionCount
from apps.census.models import BedStatus, CensusSnapshot
from apps.deaths.models import DailyDeathCount
from apps.discharges.models import DailyDischargeCount


@pytest.fixture
def make_snapshot():
    """Fixture to create CensusSnapshot rows easily."""

    def _make(
        captured_at: datetime,
        setor: str = "UTI GERAL",
        leito: str = "LEITO-01",
        prontuario: str = "PRONT-001",
        nome: str = "PACIENTE TESTE",
        bed_status: str = BedStatus.OCCUPIED,
    ) -> CensusSnapshot:
        return CensusSnapshot.objects.create(
            captured_at=captured_at,
            setor=setor,
            leito=leito,
            prontuario=prontuario,
            nome=nome,
            especialidade="NEF",
            bed_status=bed_status,
        )

    return _make


@pytest.mark.django_db
class TestComputeHospitalFlow:
    """Aggregated tests for compute_hospital_flow."""

    def test_single_day_single_snapshot(
        self, make_snapshot
    ):
        """ADC with one snapshot day, inflow/outflow from dedicated sources."""
        target_date = date(2026, 6, 10)
        t = datetime(2026, 6, 10, 8, 0, tzinfo=timezone.get_current_timezone())

        # 3 occupied beds in the same snapshot
        for i in range(3):
            make_snapshot(
                captured_at=t,
                leito=f"LEITO-{i:02d}",
                prontuario=f"PRONT-{i:03d}",
            )

        DailyAdmissionCount.objects.create(date=target_date, count=5)
        DailyDischargeCount.objects.create(date=target_date, count=2)
        DailyDeathCount.objects.create(date=target_date, count=1)

        from apps.census.flow_service import compute_hospital_flow

        result = compute_hospital_flow(target_date, target_date)

        assert len(result) == 1
        row = result[0]
        assert row["date"] == target_date
        assert row["adc"] == 3.0  # 3 occupied / 1 snapshot
        assert row["n_snapshots"] == 1
        assert row["admissions"] == 5
        assert row["discharges"] == 2
        assert row["deaths"] == 1
        assert row["net_flow"] == 2  # 5 - 2 - 1
        assert row["delta_adc"] is None  # first day
        assert row["residual"] is None  # first day

    def test_multiple_snapshots_same_day(
        self, make_snapshot
    ):
        """ADC is the average across multiple snapshots in the same day."""
        target_date = date(2026, 6, 10)
        tz = timezone.get_current_timezone()

        # Snapshot at 08:00 — 4 occupied
        t1 = datetime(2026, 6, 10, 8, 0, tzinfo=tz)
        for i in range(4):
            make_snapshot(
                captured_at=t1,
                leito=f"LEITO-{i:02d}",
                prontuario=f"PRONT-{i:03d}",
            )

        # Snapshot at 20:00 — 6 occupied
        t2 = datetime(2026, 6, 10, 20, 0, tzinfo=tz)
        for i in range(4, 10):
            make_snapshot(
                captured_at=t2,
                leito=f"LEITO-{i:02d}",
                prontuario=f"PRONT-{i:03d}",
            )

        DailyAdmissionCount.objects.create(date=target_date, count=3)
        DailyDischargeCount.objects.create(date=target_date, count=1)
        DailyDeathCount.objects.create(date=target_date, count=0)

        from apps.census.flow_service import compute_hospital_flow

        result = compute_hospital_flow(target_date, target_date)

        assert len(result) == 1
        row = result[0]
        # (4 + 6) / 2 = 5.0
        assert row["adc"] == 5.0
        assert row["n_snapshots"] == 2
        assert row["net_flow"] == 2  # 3 - 1 - 0

    def test_day_without_snapshot(
        self, make_snapshot
    ):
        """Day with no snapshot returns adc=None, n_snapshots=0."""
        target_date = date(2026, 6, 10)

        DailyAdmissionCount.objects.create(date=target_date, count=2)
        DailyDischargeCount.objects.create(date=target_date, count=1)
        DailyDeathCount.objects.create(date=target_date, count=0)

        from apps.census.flow_service import compute_hospital_flow

        result = compute_hospital_flow(target_date, target_date)

        assert len(result) == 1
        row = result[0]
        assert row["adc"] is None
        assert row["n_snapshots"] == 0
        assert row["admissions"] == 2
        assert row["discharges"] == 1
        assert row["deaths"] == 0
        assert row["net_flow"] == 1
        assert row["delta_adc"] is None
        assert row["residual"] is None

    def test_two_days_with_delta_and_residual(
        self, make_snapshot
    ):
        """Delta ADC and residual calculated correctly across consecutive days."""
        tz = timezone.get_current_timezone()

        # Day 1: 2026-06-10 — 4 occupied
        t1 = datetime(2026, 6, 10, 8, 0, tzinfo=tz)
        for i in range(4):
            make_snapshot(
                captured_at=t1,
                leito=f"LEITO-{i:02d}",
                prontuario=f"PRONT-{i:03d}",
            )
        DailyAdmissionCount.objects.create(date=date(2026, 6, 10), count=3)
        DailyDischargeCount.objects.create(date=date(2026, 6, 10), count=1)
        DailyDeathCount.objects.create(date=date(2026, 6, 10), count=0)

        # Day 2: 2026-06-11 — 7 occupied
        t2 = datetime(2026, 6, 11, 8, 0, tzinfo=tz)
        for i in range(7):
            make_snapshot(
                captured_at=t2,
                leito=f"LEITO-{i:02d}",
                prontuario=f"PRONT-{i:03d}",
            )
        DailyAdmissionCount.objects.create(date=date(2026, 6, 11), count=5)
        DailyDischargeCount.objects.create(date=date(2026, 6, 11), count=2)
        DailyDeathCount.objects.create(date=date(2026, 6, 11), count=1)

        from apps.census.flow_service import compute_hospital_flow

        result = compute_hospital_flow(date(2026, 6, 10), date(2026, 6, 11))

        assert len(result) == 2

        # Day 1
        row1 = result[0]
        assert row1["date"] == date(2026, 6, 10)
        assert row1["adc"] == 4.0
        assert row1["admissions"] == 3
        assert row1["discharges"] == 1
        assert row1["deaths"] == 0
        assert row1["net_flow"] == 2
        assert row1["delta_adc"] is None
        assert row1["residual"] is None

        # Day 2
        row2 = result[1]
        assert row2["date"] == date(2026, 6, 11)
        assert row2["adc"] == 7.0
        assert row2["admissions"] == 5
        assert row2["discharges"] == 2
        assert row2["deaths"] == 1
        assert row2["net_flow"] == 2  # 5 - 2 - 1
        assert row2["delta_adc"] == 3.0  # 7 - 4
        assert row2["residual"] == 1.0  # 3 - 2

    def test_residual_with_negative_net_flow(
        self, make_snapshot
    ):
        """Residual works correctly when net_flow is negative (more out than in)."""
        tz = timezone.get_current_timezone()

        # Day 1: 10 occupied
        t1 = datetime(2026, 6, 10, 8, 0, tzinfo=tz)
        for i in range(10):
            make_snapshot(
                captured_at=t1,
                leito=f"LEITO-{i:02d}",
                prontuario=f"PRONT-{i:03d}",
            )
        DailyAdmissionCount.objects.create(date=date(2026, 6, 10), count=0)
        DailyDischargeCount.objects.create(date=date(2026, 6, 10), count=0)
        DailyDeathCount.objects.create(date=date(2026, 6, 10), count=0)

        # Day 2: 5 occupied
        t2 = datetime(2026, 6, 11, 8, 0, tzinfo=tz)
        for i in range(5):
            make_snapshot(
                captured_at=t2,
                leito=f"LEITO-{i:02d}",
                prontuario=f"PRONT-{i:03d}",
            )
        DailyAdmissionCount.objects.create(date=date(2026, 6, 11), count=1)
        DailyDischargeCount.objects.create(date=date(2026, 6, 11), count=4)
        DailyDeathCount.objects.create(date=date(2026, 6, 11), count=2)

        from apps.census.flow_service import compute_hospital_flow

        result = compute_hospital_flow(date(2026, 6, 10), date(2026, 6, 11))
        row2 = result[1]

        assert row2["adc"] == 5.0
        assert row2["admissions"] == 1
        assert row2["discharges"] == 4
        assert row2["deaths"] == 2
        assert row2["net_flow"] == -5  # 1 - 4 - 2
        assert row2["delta_adc"] == -5.0  # 5 - 10
        assert row2["residual"] == 0.0  # -5 - (-5)

    def test_interval_with_empty_days(
        self, make_snapshot
    ):
        """Days without snapshots nor flow return zeros and adc=None."""
        tz = timezone.get_current_timezone()

        # Day 1: has data
        t1 = datetime(2026, 6, 10, 8, 0, tzinfo=tz)
        make_snapshot(captured_at=t1)
        DailyAdmissionCount.objects.create(date=date(2026, 6, 10), count=2)
        DailyDischargeCount.objects.create(date=date(2026, 6, 10), count=0)
        DailyDeathCount.objects.create(date=date(2026, 6, 10), count=0)

        # Day 2: no snapshots, no flow
        # Day 3: no snapshots, no flow

        # Day 4: has data
        t4 = datetime(2026, 6, 13, 8, 0, tzinfo=tz)
        make_snapshot(captured_at=t4)
        DailyAdmissionCount.objects.create(date=date(2026, 6, 13), count=1)
        DailyDischargeCount.objects.create(date=date(2026, 6, 13), count=1)
        DailyDeathCount.objects.create(date=date(2026, 6, 13), count=0)

        from apps.census.flow_service import compute_hospital_flow

        result = compute_hospital_flow(date(2026, 6, 10), date(2026, 6, 13))

        assert len(result) == 4

        # Day 1
        assert result[0]["date"] == date(2026, 6, 10)
        assert result[0]["adc"] == 1.0
        assert result[0]["admissions"] == 2

        # Day 2 — empty
        assert result[1]["date"] == date(2026, 6, 11)
        assert result[1]["adc"] is None
        assert result[1]["n_snapshots"] == 0
        assert result[1]["admissions"] == 0
        assert result[1]["discharges"] == 0
        assert result[1]["deaths"] == 0
        assert result[1]["net_flow"] == 0
        assert result[1]["delta_adc"] is None  # no previous ADC
        assert result[1]["residual"] is None

        # Day 3 — empty
        assert result[2]["date"] == date(2026, 6, 12)
        assert result[2]["adc"] is None
        assert result[2]["n_snapshots"] == 0
        assert result[2]["admissions"] == 0
        assert result[2]["discharges"] == 0
        assert result[2]["deaths"] == 0
        assert result[2]["net_flow"] == 0
        # delta_adc is None because day 2 has adc=None
        assert result[2]["delta_adc"] is None
        assert result[2]["residual"] is None

        # Day 4 — has data
        assert result[3]["date"] == date(2026, 6, 13)
        assert result[3]["adc"] == 1.0
        assert result[3]["admissions"] == 1
        assert result[3]["discharges"] == 1
        assert result[3]["deaths"] == 0
        assert result[3]["net_flow"] == 0
        # delta_adc from day 3 (None) to day 4 (1.0) = None because day 3 is None
        assert result[3]["delta_adc"] is None
        assert result[3]["residual"] is None

    def test_sector_filter_affects_stock_only(
        self, make_snapshot
    ):
        """Sector filter affects ADC (stock) but not flow (hospital-total)."""
        tz = timezone.get_current_timezone()
        d = date(2026, 6, 10)
        t = datetime(2026, 6, 10, 8, 0, tzinfo=tz)

        # Sector A: 3 occupied
        for i in range(3):
            make_snapshot(
                captured_at=t,
                setor="SETOR A",
                leito=f"A-{i:02d}",
                prontuario=f"PRONT-A-{i:03d}",
            )

        # Sector B: 5 occupied
        for i in range(5):
            make_snapshot(
                captured_at=t,
                setor="SETOR B",
                leito=f"B-{i:02d}",
                prontuario=f"PRONT-B-{i:03d}",
            )

        # Flow (hospital-total, not sector-specific)
        DailyAdmissionCount.objects.create(date=d, count=10)
        DailyDischargeCount.objects.create(date=d, count=4)
        DailyDeathCount.objects.create(date=d, count=1)
        DailyAdmissionCount.objects.create(date=date(2026, 6, 11), count=2)

        from apps.census.flow_service import compute_hospital_flow

        # Hospital-total
        total = compute_hospital_flow(d, d)
        assert total[0]["adc"] == 8.0  # 3 + 5
        assert total[0]["admissions"] == 10

        # Sector A only
        sector_a = compute_hospital_flow(d, d, sector="SETOR A")
        assert sector_a[0]["adc"] == 3.0
        assert sector_a[0]["admissions"] == 10  # flow is still hospital-total
        assert sector_a[0]["discharges"] == 4
        assert sector_a[0]["deaths"] == 1

        # Sector B only
        sector_b = compute_hospital_flow(d, d, sector="SETOR B")
        assert sector_b[0]["adc"] == 5.0
        assert sector_b[0]["admissions"] == 10  # flow is still hospital-total

    def test_missing_flow_source_returns_zero(
        self, make_snapshot
    ):
        """When no DailyAdmissionCount/Discharge/Death exists for a day, return 0."""
        target_date = date(2026, 6, 10)
        tz = timezone.get_current_timezone()
        t = datetime(2026, 6, 10, 8, 0, tzinfo=tz)

        make_snapshot(captured_at=t)
        # No flow records created

        from apps.census.flow_service import compute_hospital_flow

        result = compute_hospital_flow(target_date, target_date)

        assert len(result) == 1
        assert result[0]["adc"] == 1.0
        assert result[0]["admissions"] == 0
        assert result[0]["discharges"] == 0
        assert result[0]["deaths"] == 0
        assert result[0]["net_flow"] == 0

    def test_non_occupied_beds_excluded(
        self, make_snapshot
    ):
        """Empty/maintenance/reserved/isolated beds are not counted in ADC."""
        tz = timezone.get_current_timezone()
        d = date(2026, 6, 10)
        t = datetime(2026, 6, 10, 8, 0, tzinfo=tz)

        # 3 occupied
        for i in range(3):
            make_snapshot(
                captured_at=t,
                leito=f"OCC-{i:02d}",
                prontuario=f"PRONT-{i:03d}",
                bed_status=BedStatus.OCCUPIED,
            )
        # 2 empty
        make_snapshot(
            captured_at=t, leito="EMP-01",
            prontuario="", nome="VAZIO",
            bed_status=BedStatus.EMPTY,
        )
        make_snapshot(
            captured_at=t, leito="EMP-02",
            prontuario="", nome="VAZIO",
            bed_status=BedStatus.EMPTY,
        )
        # 1 maintenance
        make_snapshot(
            captured_at=t, leito="MAINT-01",
            prontuario="", nome="LIMPEZA",
            bed_status=BedStatus.MAINTENANCE,
        )

        from apps.census.flow_service import compute_hospital_flow

        result = compute_hospital_flow(d, d)
        assert result[0]["adc"] == 3.0  # only 3 occupied
        assert result[0]["n_snapshots"] == 1

    def test_end_before_start_raises_value_error(self):
        """Raises ValueError when end < start."""
        from apps.census.flow_service import compute_hospital_flow

        with pytest.raises(ValueError, match="end must be >= start"):
            compute_hospital_flow(date(2026, 6, 20), date(2026, 6, 10))
