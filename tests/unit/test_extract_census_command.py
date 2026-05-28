from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from apps.census.models import BedStatus
from apps.census.services import parse_census_csv


class TestParseCensusCsv:
    def test_parse_valid_csv(self):
        """Parse a valid CSV with mixed bed statuses."""
        csv_content = (
            "setor_codigo,setor,qrt_leito,prontuario,nome,esp,dt_mvt,alta,origem\n"
            "640,UTI A,UG01A,14160147,JOSE MERCES,NEF,26/05,,\n"
            "630,UTI A,UG02B,,DESOCUPADO,,,,\n"
            "654,UTI A,UG03C,,RESERVA INTERNA,,,,,\n"
            "642,ENF B,E01A,99999,MARIA SILVA,CME,27/05,A,640/UG01A\n"
            "651,ENF B,E02B,,LIMPEZA,,,,,\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write(csv_content)
            csv_path = Path(f.name)

        try:
            rows = parse_census_csv(csv_path)
            assert len(rows) == 5
            assert rows[0]["bed_status"] == BedStatus.OCCUPIED
            assert rows[0]["prontuario"] == "14160147"
            assert rows[0]["setor_codigo"] == "640"
            assert rows[0]["setor"] == "UTI A"
            assert rows[1]["bed_status"] == BedStatus.EMPTY
            assert rows[2]["bed_status"] == BedStatus.RESERVED
            assert rows[3]["bed_status"] == BedStatus.OCCUPIED
            assert rows[4]["bed_status"] == BedStatus.MAINTENANCE
        finally:
            csv_path.unlink(missing_ok=True)

    def test_parse_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            parse_census_csv(Path("/nonexistent/census.csv"))

    def test_parse_missing_columns(self):
        csv_content = "setor_codigo,setor,qrt_leito\n640,UTI A,UG01A\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8"
        ) as f:
            f.write(csv_content)
            csv_path = Path(f.name)

        try:
            with pytest.raises(ValueError, match="missing required columns"):
                parse_census_csv(csv_path)
        finally:
            csv_path.unlink(missing_ok=True)
