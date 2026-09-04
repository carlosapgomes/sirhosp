"""Integration: legacy PDF command retirement (RPSA-S3).

Proves the fail-safe retirement contract for the two legacy PDF
commands:

- ``process_discharge_pdf`` and ``backfill_daily_discharges`` fail with
  a safe deprecation ``CommandError`` BEFORE opening/parsing any PDF,
  printing patient identity, persisting evidence, enqueueing work or
  changing aggregate or clinical state — even when the target file or
  directory exists;
- the retired commands keep no executable reference to the dedicated
  PDF helper (``pdf_utils``) or ``pymupdf``.

All fixtures are synthetic; no real PDF is required (the fail-safe must
trigger before any byte is read).
"""

from __future__ import annotations

from datetime import date
from importlib import import_module
from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.discharges.models import DailyDischargeCount, DischargeRecord
from apps.ingestion.models import IngestionRun
from apps.patients.models import Admission, Patient

# =========================================================================
# process_discharge_pdf
# =========================================================================


@pytest.mark.django_db
class TestProcessDischargePdfRetired:
    def test_invocation_fails_safe_before_reading_pdf(self, tmp_path: Path):
        """Even with an existing target file, the command fails before any
        side effect: no DB mutation, no enqueue, no patient output."""
        fake_pdf = tmp_path / "altas-01-06-2026.pdf"
        fake_pdf.write_bytes(b"not-a-real-pdf")

        with pytest.raises(CommandError) as excinfo:
            call_command(
                "process_discharge_pdf",
                str(fake_pdf),
                "--discharge-date=2026-06-01",
            )

        assert "deprecat" in str(excinfo.value).lower()
        assert Patient.objects.count() == 0
        assert Admission.objects.count() == 0
        assert DischargeRecord.objects.count() == 0
        assert DailyDischargeCount.objects.count() == 0
        assert IngestionRun.objects.count() == 0

    def test_invocation_with_missing_path_still_raises_command_error(
        self, tmp_path: Path,
    ):
        with pytest.raises(CommandError):
            call_command(
                "process_discharge_pdf",
                str(tmp_path / "nao-existe.pdf"),
            )

    def test_error_message_never_carries_seeded_identity(
        self, tmp_path: Path,
    ):
        """Identity that already exists in the mirror must not leak into
        the deprecation error output."""
        DischargeRecord.objects.create(
            prontuario="700001",
            nome="PACIENTE SECRETO 700001",
            data_internacao="20/05/2026",
        )

        with pytest.raises(CommandError) as excinfo:
            call_command("process_discharge_pdf", str(tmp_path / "x.pdf"))

        message = str(excinfo.value)
        assert "700001" not in message
        assert "PACIENTE SECRETO" not in message


# =========================================================================
# backfill_daily_discharges
# =========================================================================


@pytest.mark.django_db
class TestBackfillDailyDischargesRetired:
    def test_invocation_fails_safe_with_existing_pdf_dir(self, tmp_path: Path):
        """Even with a directory of matching PDF names, the command fails
        before any side effect: aggregate and evidence stay untouched."""
        pdf_dir = tmp_path / "pdfs"
        pdf_dir.mkdir()
        (pdf_dir / "altas-01-06-2026.pdf").write_bytes(b"not-a-real-pdf")
        (pdf_dir / "altas-02-06-2026.pdf").write_bytes(b"not-a-real-pdf")

        seeded_aggregate = DailyDischargeCount.objects.create(
            date=date(2026, 6, 1), count=7
        )

        with pytest.raises(CommandError) as excinfo:
            call_command("backfill_daily_discharges", str(pdf_dir))

        assert "deprecat" in str(excinfo.value).lower()
        assert DailyDischargeCount.objects.count() == 1
        seeded_aggregate.refresh_from_db()
        assert seeded_aggregate.count == 7
        assert DischargeRecord.objects.count() == 0
        assert IngestionRun.objects.count() == 0

    def test_invocation_with_missing_dir_still_raises_command_error(
        self, tmp_path: Path,
    ):
        with pytest.raises(CommandError):
            call_command(
                "backfill_daily_discharges", str(tmp_path / "nao-existe")
            )


# =========================================================================
# No executable helper references remain in the retired commands
# =========================================================================


def _helper_reference_violations(module_name: str) -> list[str]:
    """Executable references to the retired PDF helper in a command module:
    static imports (AST), dynamic ``import_module`` usage, direct pymupdf
    use or helper calls. Docstring mentions are documentation, not code,
    and are resolved against the AST/import surface only."""
    import ast

    module = import_module(module_name)
    module_file = module.__file__
    assert module_file is not None
    source = Path(module_file).read_text(encoding="utf-8")
    tree = ast.parse(source)
    violations: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if "pdf_utils" in alias.name or "pymupdf" in alias.name:
                    violations.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom) and node.module:
            if "pdf_utils" in node.module or "pymupdf" in node.module:
                violations.append(f"from {node.module}")
    if "import_module" in source:
        violations.append("dynamic import_module usage")
    if "extract_patients" in source:
        violations.append("helper call extract_patients")
    return violations


class TestRetiredCommandsHaveNoExecutableHelperReferences:
    def test_process_discharge_pdf_has_no_pdf_helper_or_pymupdf_import(self):
        assert _helper_reference_violations(
            "apps.discharges.management.commands.process_discharge_pdf"
        ) == []

    def test_backfill_daily_discharges_has_no_pdf_helper_or_pymupdf_import(
        self,
    ):
        assert _helper_reference_violations(
            "apps.discharges.management.commands.backfill_daily_discharges"
        ) == []
