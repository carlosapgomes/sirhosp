"""Tests for import_wards_beds_registry command and PDF parser."""

from __future__ import annotations

from pathlib import Path

import pytest
from django.core.management import call_command

from apps.census.models import Bed, Ward


def _make_ward_beds_pdf_text() -> str:
    """Return a minimal valid snapshot of the ward/bed catalog PDF text."""
    return (
        "Unidade 640\n"
        "01 6 - 1A - CIRURGIA GERAL - HGRS\n"
        "Leito\n"
        "Status\n"
        "Acomodação\n"
        "Ativo\n"
        "101AA\n"
        "16\n"
        "ENFERMARIA\n"
        "A\n"
        "101AB\n"
        "16\n"
        "ENFERMARIA\n"
        "A\n"
        "102AA\n"
        "31\n"
        "ENFERMARIA\n"
        "I\n"
        "Total\n"
        "3\n"
        "Unidade 630\n"
        "00 T - UTI CIRÚRGICA - HGRS\n"
        "Leito\n"
        "Status\n"
        "Acomodação\n"
        "Ativo\n"
        "UC01A\n"
        "11\n"
        "UTI\n"
        "A\n"
        "UC02B\n"
        "16\n"
        "UTI\n"
        "A\n"
        "Total\n"
        "2\n"
    )


@pytest.mark.django_db
class TestImportWardsBedsRegistry:
    def test_creates_wards_and_beds_from_pdf_text(self, tmp_path: Path):
        """Command creates Ward and Bed records from PDF text."""
        pdf_text = _make_ward_beds_pdf_text()
        input_file = tmp_path / "leitos.txt"
        input_file.write_text(pdf_text, encoding="utf-8")

        call_command("import_wards_beds_registry", "--input", str(input_file), "--text-mode")

        assert Ward.objects.count() == 2
        w1 = Ward.objects.get(source_code="640")
        assert w1.name == "01 6 - 1A - CIRURGIA GERAL - HGRS"
        assert w1.beds.count() == 3

        w2 = Ward.objects.get(source_code="630")
        assert w2.name == "00 T - UTI CIRÚRGICA - HGRS"
        assert w2.beds.count() == 2

    def test_bed_attributes_are_parsed_correctly(self, tmp_path: Path):
        pdf_text = _make_ward_beds_pdf_text()
        input_file = tmp_path / "leitos.txt"
        input_file.write_text(pdf_text, encoding="utf-8")

        call_command("import_wards_beds_registry", "--input", str(input_file), "--text-mode")

        b1 = Bed.objects.get(ward__source_code="640", code="101AA")
        assert b1.status == "16"
        assert b1.accommodation == "ENFERMARIA"
        assert b1.is_active is True

        b2 = Bed.objects.get(ward__source_code="640", code="102AA")
        assert b2.status == "31"
        assert b2.is_active is False  # Ativo='I'

    def test_idempotent_second_import_updates_existing(self, tmp_path: Path):
        """Second import toggles a bed's is_active and creates new ones."""
        pdf_text = _make_ward_beds_pdf_text()
        input_file = tmp_path / "leitos.txt"
        input_file.write_text(pdf_text, encoding="utf-8")

        call_command("import_wards_beds_registry", "--input", str(input_file), "--text-mode")
        assert Bed.objects.count() == 5

        # Toggle 101AA from A -> I, add new bed 101AC
        modified = _make_ward_beds_pdf_text().replace(
            "101AA\n16\nENFERMARIA\nA\n",
            "101AA\n16\nENFERMARIA\nI\n101AC\n0\nENFERMARIA\nA\n",
        )
        input_file2 = tmp_path / "leitos2.txt"
        input_file2.write_text(modified, encoding="utf-8")
        call_command("import_wards_beds_registry", "--input", str(input_file2), "--text-mode")

        b1 = Bed.objects.get(ward__source_code="640", code="101AA")
        assert b1.is_active is False  # was A, now I

        new_bed = Bed.objects.get(ward__source_code="640", code="101AC")
        assert new_bed.is_active is True

        assert Bed.objects.count() == 6
