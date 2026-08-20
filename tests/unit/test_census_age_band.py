"""Tests for the normalized occupancy age band of census rows (CCO3A-S1).

Covers the pure classification function, the CSV parser propagation and the
``extract_census`` management command persistence, with synthetic data only.
No real patient data is used.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.census.models import BedStatus, CensusSnapshot, OccupancyAgeBand
from apps.census.services import (
    classify_occupancy_age_band,
    normalize_occupancy_age_band,
    parse_census_csv,
)
from apps.ingestion.models import IngestionRun


class TestOccupancyAgeBandChoices:
    """R1: persistible choices equivalent to the four required states."""

    def test_choices_exist(self):
        assert OccupancyAgeBand.UNDER_12 == "under_12"
        assert OccupancyAgeBand.AGE_12_OR_OVER == "age_12_or_over"
        assert OccupancyAgeBand.UNKNOWN == "unknown"
        assert OccupancyAgeBand.NOT_APPLICABLE == "not_applicable"
        assert OccupancyAgeBand.values == [
            "under_12",
            "age_12_or_over",
            "unknown",
            "not_applicable",
        ]

    @pytest.mark.django_db
    def test_snapshot_defaults_to_safe_unknown(self):
        snap = CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="SETOR TESTE",
            leito="L01",
            prontuario="",
            nome="",
            especialidade="",
            bed_status=BedStatus.EMPTY,
        )
        assert snap.age_band == OccupancyAgeBand.UNKNOWN

    @pytest.mark.django_db
    def test_snapshot_persists_band(self):
        snap = CensusSnapshot.objects.create(
            captured_at=timezone.now(),
            setor="SETOR TESTE",
            leito="L02",
            prontuario="P0001",
            nome="PACIENTE",
            especialidade="CLI",
            bed_status=BedStatus.OCCUPIED,
            age_band=OccupancyAgeBand.UNDER_12,
        )
        snap.refresh_from_db()
        assert snap.age_band == OccupancyAgeBand.UNDER_12


class TestNormalizeOccupancyAgeBand:
    """R2/R3/R4: pure normalization of a raw legacy Idade value."""

    @pytest.mark.parametrize(
        "raw",
        ["0", "1", "7", "11", " 7 ", "11 "],
    )
    def test_integer_below_twelve_is_child(self, raw):
        assert (
            normalize_occupancy_age_band(raw)
            == OccupancyAgeBand.UNDER_12
        )

    @pytest.mark.parametrize(
        "raw",
        ["12", "13", "45", "120", " 12 ", "12 "],
    )
    def test_integer_twelve_or_over_is_adult(self, raw):
        assert (
            normalize_occupancy_age_band(raw)
            == OccupancyAgeBand.AGE_12_OR_OVER
        )

    @pytest.mark.parametrize(
        "raw",
        ["1m", "1 M", "1m3d", "1m 3d", "12m", "11m", "143m", "142m60d"],
    )
    def test_month_day_formats_below_limit(self, raw):
        assert (
            normalize_occupancy_age_band(raw)
            == OccupancyAgeBand.UNDER_12
        )

    @pytest.mark.parametrize(
        "raw",
        ["144m", "144m0d", "142m61d"],
    )
    def test_month_day_formats_at_or_above_limit(self, raw):
        assert (
            normalize_occupancy_age_band(raw)
            == OccupancyAgeBand.AGE_12_OR_OVER
        )

    @pytest.mark.parametrize(
        "raw",
        [
            None,
            "",
            "   ",
            "-1",
            "-5",
            "12.5",
            "12,5",
            "5d",
            "5y",
            "anos",
            "m",
            "1m x",
            "1m3x",
            "1m3",
        ],
    )
    def test_invalid_or_unsupported_values_are_unknown(self, raw):
        assert (
            normalize_occupancy_age_band(raw)
            == OccupancyAgeBand.UNKNOWN
        )


class TestClassifyOccupancyAgeBand:
    """R5: bed status takes precedence over any idade value."""

    @pytest.mark.parametrize(
        "status",
        [
            BedStatus.EMPTY,
            BedStatus.MAINTENANCE,
            BedStatus.RESERVED,
            BedStatus.ISOLATION,
        ],
    )
    @pytest.mark.parametrize(
        "raw",
        ["3", "45", "", "1m3d", "99"],
    )
    def test_non_occupied_always_not_applicable(self, status, raw):
        assert (
            classify_occupancy_age_band(raw, status)
            == OccupancyAgeBand.NOT_APPLICABLE
        )

    def test_occupied_row_uses_own_age_value(self):
        assert (
            classify_occupancy_age_band("3", BedStatus.OCCUPIED)
            == OccupancyAgeBand.UNDER_12
        )
        assert (
            classify_occupancy_age_band("45", BedStatus.OCCUPIED)
            == OccupancyAgeBand.AGE_12_OR_OVER
        )
        assert (
            classify_occupancy_age_band("", BedStatus.OCCUPIED)
            == OccupancyAgeBand.UNKNOWN
        )


def _write_csv(content: str) -> Path:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".csv", delete=False, encoding="utf-8"
    ) as f:
        f.write(content)
        return Path(f.name)


class TestParseCensusCsvAgeBand:
    """R7/R8: parser reads optional idade column and preserves fields."""

    def test_csv_with_idade_column_classifies_bands(self):
        content = (
            "setor_codigo,setor,qrt_leito,prontuario,nome,esp,idade\n"
            "640,UTI A,UG01A,P0001,PACIENTE A,NEF,3\n"
            "654,ENF 3A,E01A,P0002,PACIENTE B,OB,45\n"
            "654,ENF 3A,E02B,P0003,PACIENTE C,OB,1m3d\n"
            "654,ENF 3A,E03D,P0004,PACIENTE D,OB,\n"
            "630,UTI A,UG02B,,DESOCUPADO,,8\n"
            "632,UTI A,UG03C,,RESERVA INTERNA,,30\n"
        )
        path = _write_csv(content)
        try:
            rows = parse_census_csv(path)
        finally:
            path.unlink(missing_ok=True)

        by_bed = {r["leito"]: r for r in rows}
        assert by_bed["UG01A"]["age_band"] == OccupancyAgeBand.UNDER_12
        assert by_bed["E01A"]["age_band"] == OccupancyAgeBand.AGE_12_OR_OVER
        assert by_bed["E02B"]["age_band"] == OccupancyAgeBand.UNDER_12
        assert by_bed["E03D"]["age_band"] == OccupancyAgeBand.UNKNOWN
        assert by_bed["UG02B"]["age_band"] == OccupancyAgeBand.NOT_APPLICABLE
        assert by_bed["UG03C"]["age_band"] == OccupancyAgeBand.NOT_APPLICABLE

    def test_csv_without_idade_column_still_accepted(self):
        content = (
            "setor_codigo,setor,qrt_leito,prontuario,nome,esp\n"
            "640,UTI A,UG01A,P0001,PACIENTE A,NEF\n"
            "630,UTI A,UG02B,,DESOCUPADO,,\n"
        )
        path = _write_csv(content)
        try:
            rows = parse_census_csv(path)
        finally:
            path.unlink(missing_ok=True)

        by_bed = {r["leito"]: r for r in rows}
        assert by_bed["UG01A"]["age_band"] == OccupancyAgeBand.UNKNOWN
        assert by_bed["UG02B"]["age_band"] == OccupancyAgeBand.NOT_APPLICABLE

    def test_parser_never_emits_raw_age(self):
        content = (
            "setor_codigo,setor,qrt_leito,prontuario,nome,esp,idade\n"
            "654,ENF 3A,E01A,P0002,PACIENTE B,OB,45\n"
        )
        path = _write_csv(content)
        try:
            rows = parse_census_csv(path)
        finally:
            path.unlink(missing_ok=True)

        assert rows[0]["age_band"] == OccupancyAgeBand.AGE_12_OR_OVER
        assert "idade" not in rows[0]
        assert "45" not in str(rows[0])
        assert rows[0]["setor_codigo"] == "654"
        assert rows[0]["setor"] == "ENF 3A"
        assert rows[0]["prontuario"] == "P0002"

    def test_parser_preserves_existing_fields(self):
        content = (
            "setor_codigo,setor,qrt_leito,prontuario,nome,esp,idade,"
            "dt_int,tempo,dt_mvt,alta,origem\n"
            "640,UTI A,UG01A,P0001,PACIENTE A,NEF,3,01/01/2026,5,"
            "02/01/2026,,\n"
        )
        path = _write_csv(content)
        try:
            rows = parse_census_csv(path)
        finally:
            path.unlink(missing_ok=True)

        row = rows[0]
        assert row["setor_codigo"] == "640"
        assert row["setor"] == "UTI A"
        assert row["leito"] == "UG01A"
        assert row["prontuario"] == "P0001"
        assert row["nome"] == "PACIENTE A"
        assert row["especialidade"] == "NEF"
        assert row["bed_status"] == BedStatus.OCCUPIED
        assert row["data_internacao"] == "01/01/2026"
        assert row["tempo_internacao"] == 5
        assert row["age_band"] == OccupancyAgeBand.UNDER_12


def _synthetic_census_csv_with_age() -> str:
    """Build a 40-sector CSV including the idade column (synthetic rows)."""
    lines = [
        "setor_codigo,setor,qrt_leito,prontuario,nome,esp,idade,"
        "dt_int,tempo,dt_mvt,alta,origem"
    ]
    for i in range(1, 41):
        sector = f"SETOR {i:03d}"
        age = "3" if i % 2 else "45"
        lines.append(
            f"{i},{sector},L{i:03d}A,P{i:05d},PACIENTE {i},CLI,{age},,,,,"
        )
        lines.append(
            f"{i},{sector},L{i:03d}B,,DESOCUPADO,,{age},,,,,"
        )
    return "\n".join(lines)


class TestExtractCensusCommandAgeBand:
    """R7/R8: the real command persists the band on every snapshot."""

    @pytest.mark.django_db
    def test_command_persists_age_band(self):
        with tempfile.TemporaryDirectory() as real_tmp:
            tmp_path = Path(real_tmp)
            (tmp_path / "censo-20260426.csv").write_text(
                _synthetic_census_csv_with_age(), encoding="utf-8"
            )
            fake_result = MagicMock()
            fake_result.returncode = 0
            fake_tmp_ctx = MagicMock()
            fake_tmp_ctx.__enter__.return_value = str(real_tmp)

            with (
                patch(
                    "apps.census.management.commands.extract_census."
                    "run_subprocess",
                    return_value=fake_result,
                ),
                patch("pathlib.Path.exists", return_value=True),
                patch(
                    "tempfile.TemporaryDirectory",
                    return_value=fake_tmp_ctx,
                ),
            ):
                call_command("extract_census")

            run = IngestionRun.objects.first()
            assert run is not None
            assert run.status == "succeeded"
            assert CensusSnapshot.objects.count() == 80

            occupied = CensusSnapshot.objects.filter(
                bed_status=BedStatus.OCCUPIED
            )
            empty = CensusSnapshot.objects.filter(
                bed_status=BedStatus.EMPTY
            )
            assert occupied.count() == 40
            assert empty.count() == 40

            # Odd sectors (age 3) → under_12; even sectors (age 45) → adult
            assert (
                occupied.filter(
                    setor="SETOR 001",
                    age_band=OccupancyAgeBand.UNDER_12,
                ).count()
                == 1
            )
            assert (
                occupied.filter(
                    setor="SETOR 002",
                    age_band=OccupancyAgeBand.AGE_12_OR_OVER,
                ).count()
                == 1
            )
            # Non-occupied rows keep not_applicable even with idade present
            assert (
                empty.filter(
                    age_band=OccupancyAgeBand.NOT_APPLICABLE
                ).count()
                == 40
            )

    @pytest.mark.django_db
    def test_command_preserves_clinical_fields(self):
        with tempfile.TemporaryDirectory() as real_tmp:
            tmp_path = Path(real_tmp)
            (tmp_path / "censo-20260426.csv").write_text(
                _synthetic_census_csv_with_age(), encoding="utf-8"
            )
            fake_result = MagicMock()
            fake_result.returncode = 0
            fake_tmp_ctx = MagicMock()
            fake_tmp_ctx.__enter__.return_value = str(real_tmp)

            with (
                patch(
                    "apps.census.management.commands.extract_census."
                    "run_subprocess",
                    return_value=fake_result,
                ),
                patch("pathlib.Path.exists", return_value=True),
                patch(
                    "tempfile.TemporaryDirectory",
                    return_value=fake_tmp_ctx,
                ),
            ):
                call_command("extract_census")

            snap = CensusSnapshot.objects.get(leito="L001A")
            assert snap.setor == "SETOR 001"
            assert snap.setor_codigo == "1"
            assert snap.prontuario == "P00001"
            assert snap.nome == "PACIENTE 1"
            assert snap.especialidade == "CLI"
            assert snap.bed_status == BedStatus.OCCUPIED
            assert snap.age_band == OccupancyAgeBand.UNDER_12
