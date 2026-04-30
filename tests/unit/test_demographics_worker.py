"""Tests for demographics_only worker (Slice DI-1)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from apps.ingestion.extractors.subprocess_utils import SubprocessTimeoutError
from apps.ingestion.models import IngestionRun, IngestionRunStageMetric
from apps.ingestion.services import queue_demographics_only_run
from apps.patients.models import Patient


@pytest.mark.django_db
class TestQueueDemographicsOnlyRun:
    """Tests for queue_demographics_only_run()."""

    def test_creates_run_with_correct_intent(self):
        """queue_demographics_only_run creates IngestionRun with
        intent='demographics_only'."""
        run = queue_demographics_only_run(patient_record="12345")

        assert run.status == "queued"
        assert run.intent == "demographics_only"
        assert run.parameters_json["patient_record"] == "12345"
        assert run.parameters_json["intent"] == "demographics_only"

    def test_creates_run_with_empty_record(self):
        """Empty patient_record is still enqueued (validation in worker)."""
        run = queue_demographics_only_run(patient_record="")
        assert run.status == "queued"
        assert run.parameters_json["patient_record"] == ""


@pytest.mark.django_db
class TestProcessDemographicsOnly:
    """Tests for _process_demographics_only() worker method.

    All tests mock subprocess.run to avoid real Playwright execution.
    """

    SCRIPT_PATH = (
        Path(__file__).resolve().parents[3]
        / "automation"
        / "source_system"
        / "patient_demographics"
        / "extract_patient_demographics.py"
    )

    DEMOGRAPHICS_JSON = {
        "_meta": {"patient_record": "14160147",
                   "extracted_at": "2026-01-01T00:00:00"},
        "prontuario": "14160147",
        "nome": "JOSE AUGUSTO MERCES",
        "nome_social": "",
        "sexo": "Masculino",
        "genero": "Cisgênero",
        "data_nascimento": "15/03/1965",
        "nome_mae": "MARIA MERCES",
        "nome_pai": "JOAO MERCES",
        "raca_cor": "Branca",
        "naturalidade": "Sao Paulo",
        "nacionalidade": "Brasileira",
        "estado_civil": "Casado",
        "profissao": "Motorista",
        "grau_instrucao": "Ensino Medio Completo",
        "cns": "898001234567890",
        "cpf": "12345678900",
        "ddd_fone_residencial": "11",
        "fone_residencial": "12345678",
        "logradouro": "Rua das Flores",
        "numero": "123",
        "bairro": "Centro",
        "cidade": "Sao Paulo",
        "uf": "SP",
        "cep": "01001000",
    }

    def _create_queued_run(self, patient_record="14160147"):
        """Helper: create a queued demographics_only run."""
        return IngestionRun.objects.create(
            status="queued",
            intent="demographics_only",
            parameters_json={
                "patient_record": patient_record,
                "intent": "demographics_only",
            },
        )

    def _mock_subprocess_success(self, mock_run, json_data=None):
        """Configure mock subprocess.run to simulate success."""
        data = json_data or self.DEMOGRAPHICS_JSON

        def _side_effect(cmd, **kwargs):
            # Write JSON to the --json-output path
            for i, arg in enumerate(cmd):
                if arg == "--json-output" and i + 1 < len(cmd):
                    output_path = Path(cmd[i + 1])
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text(
                        json.dumps(data, ensure_ascii=False),
                        encoding="utf-8",
                    )
                    break
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mock_run.side_effect = _side_effect

    def _mock_subprocess_failure(self, mock_run, returncode=1,
                                  stderr="Script error"):
        """Configure mock subprocess.run to simulate failure."""
        result = MagicMock()
        result.returncode = returncode
        result.stdout = ""
        result.stderr = stderr
        mock_run.return_value = result

    # ------------------------------------------------------------------
    # Test cases
    # ------------------------------------------------------------------

    @patch("apps.ingestion.extractors.subprocess_utils.run_subprocess")
    def test_successful_extraction_creates_patient(self, mock_run):
        """Successful demographics extraction → Patient created with
        full data."""
        from apps.ingestion.management.commands.process_ingestion_runs import (
            Command,
        )

        self._mock_subprocess_success(mock_run)
        run = self._create_queued_run()

        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd._process_demographics_only(run)

        run.refresh_from_db()
        assert run.status == "succeeded"
        assert run.failure_reason == ""

        patient = Patient.objects.get(
            source_system="tasy", patient_source_key="14160147"
        )
        assert patient.name == "JOSE AUGUSTO MERCES"
        assert patient.mother_name == "MARIA MERCES"
        assert patient.cns == "898001234567890"
        assert patient.cpf == "12345678900"
        assert patient.city == "Sao Paulo"

    @patch("apps.ingestion.extractors.subprocess_utils.run_subprocess")
    def test_successful_extraction_updates_existing_patient(self, mock_run):
        """Existing patient gets demographic data updated."""
        from apps.ingestion.management.commands.process_ingestion_runs import (
            Command,
        )

        # Create patient with minimal data first (simulating census creation)
        Patient.objects.create(
            source_system="tasy",
            patient_source_key="14160147",
            name="JOSE MERCES",
            # All other fields empty
        )

        self._mock_subprocess_success(mock_run)
        run = self._create_queued_run()

        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd._process_demographics_only(run)

        run.refresh_from_db()
        assert run.status == "succeeded"

        patient = Patient.objects.get(
            source_system="tasy", patient_source_key="14160147"
        )
        # Name was updated from census name
        assert patient.name == "JOSE AUGUSTO MERCES"
        # New fields populated
        assert patient.mother_name == "MARIA MERCES"
        assert patient.cpf == "12345678900"

    @patch("apps.ingestion.extractors.subprocess_utils.run_subprocess")
    def test_subprocess_timeout_fails_run(self, mock_run):
        """Timeout → run failed with timeout reason."""
        mock_run.side_effect = SubprocessTimeoutError(
            cmd=["python", "script.py"], timeout=300
        )

        from apps.ingestion.management.commands.process_ingestion_runs import (
            Command,
        )

        run = self._create_queued_run()
        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd._process_demographics_only(run)

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.failure_reason == "timeout"
        assert run.timed_out is True

    @patch("apps.ingestion.extractors.subprocess_utils.run_subprocess")
    def test_subprocess_nonzero_exit_fails_run(self, mock_run):
        """Non-zero exit code → run failed."""
        self._mock_subprocess_failure(mock_run, returncode=1,
                                       stderr="Connection refused")

        from apps.ingestion.management.commands.process_ingestion_runs import (
            Command,
        )

        run = self._create_queued_run()
        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd._process_demographics_only(run)

        run.refresh_from_db()
        assert run.status == "failed"
        assert run.failure_reason == "source_unavailable"

    @patch("apps.ingestion.extractors.subprocess_utils.run_subprocess")
    def test_invalid_json_output_fails_run(self, mock_run):
        """Invalid JSON in output file → run failed."""
        self._mock_subprocess_success(mock_run, json_data=None)

        # Override side_effect to write invalid JSON
        def _side_effect(cmd, **kwargs):
            for i, arg in enumerate(cmd):
                if arg == "--json-output" and i + 1 < len(cmd):
                    output_path = Path(cmd[i + 1])
                    output_path.parent.mkdir(parents=True, exist_ok=True)
                    output_path.write_text("not valid json {{{", encoding="utf-8")
                    break
            result = MagicMock()
            result.returncode = 0
            result.stdout = ""
            result.stderr = ""
            return result

        mock_run.side_effect = _side_effect

        from apps.ingestion.management.commands.process_ingestion_runs import (
            Command,
        )

        run = self._create_queued_run()
        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd._process_demographics_only(run)

        run.refresh_from_db()
        assert run.status == "failed"

    @patch("apps.ingestion.extractors.subprocess_utils.run_subprocess")
    def test_missing_patient_record_fails_early(self, mock_run):
        """Missing patient_record in parameters → fail without subprocess."""
        from apps.ingestion.management.commands.process_ingestion_runs import (
            Command,
        )

        run = IngestionRun.objects.create(
            status="queued",
            intent="demographics_only",
            parameters_json={"intent": "demographics_only"},
            # No patient_record
        )

        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd._process_demographics_only(run)

        run.refresh_from_db()
        assert run.status == "failed"
        # subprocess.run should NOT have been called
        mock_run.assert_not_called()

    @patch("apps.ingestion.extractors.subprocess_utils.run_subprocess")
    def test_stage_metrics_recorded_on_success(self, mock_run):
        """Stage metrics are created for successful demographics extraction."""
        from apps.ingestion.management.commands.process_ingestion_runs import (
            Command,
        )

        self._mock_subprocess_success(mock_run)
        run = self._create_queued_run()

        cmd = Command()
        cmd.stdout = MagicMock()
        cmd.stderr = MagicMock()
        cmd._process_demographics_only(run)

        stages = IngestionRunStageMetric.objects.filter(run=run)
        stage_names = {s.stage_name for s in stages}
        assert "demographics_extraction" in stage_names
        assert "demographics_persistence" in stage_names

        ext_stage = stages.get(stage_name="demographics_extraction")
        assert ext_stage.status == "succeeded"

        persist_stage = stages.get(stage_name="demographics_persistence")
        assert persist_stage.status == "succeeded"
