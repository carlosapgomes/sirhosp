"""Unit tests for signature datetime fallback in path2 connector."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_PATH2_DIR = (
    Path(__file__).resolve().parents[2]
    / "automation"
    / "source_system"
    / "medical_evolution"
)
_PATH2_FILE = _PATH2_DIR / "path2.py"

if str(_PATH2_DIR) not in sys.path:
    sys.path.insert(0, str(_PATH2_DIR))

# Ensure local automation config.py is used by source_system.py during import.
_config_spec = importlib.util.spec_from_file_location(
    "config",
    _PATH2_DIR / "config.py",
)
_config_mod = importlib.util.module_from_spec(_config_spec)  # type: ignore[arg-type]
_config_spec.loader.exec_module(_config_mod)  # type: ignore[union-attr]
sys.modules["config"] = _config_mod

_spec = importlib.util.spec_from_file_location("_path2", _PATH2_FILE)
_mod = importlib.util.module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(_mod)  # type: ignore[union-attr]


extract_signature_datetime = _mod.extract_signature_datetime
is_evolution_end_line = _mod.is_evolution_end_line
build_evolutions_json_payload = _mod.build_evolutions_json_payload


def test_signature_line_without_time_is_recognized_and_defaults_to_noon():
    signature_line = (
        "Elaborado e assinado por Drª. Stephane Darc Magalhaes Goncalves, "
        "Crm 47168, Hospital Geral Menandro De Faria em 22/04/2026"
    )

    assert is_evolution_end_line(signature_line)
    assert extract_signature_datetime(signature_line) == "2026-04-22T12:00:00"


def test_json_payload_populates_author_and_signature_for_date_only_signature():
    evolution_lines = [
        "22/04/2026 18:44:00",
        "Leito: UTH4D",
        "Conduta",
        "Elaborado e assinado por Drª. Stephane Darc Magalhaes Goncalves, "
        "Crm 47168, Hospital Geral Menandro De Faria em 22/04/2026",
    ]

    payload = build_evolutions_json_payload([evolution_lines])

    assert len(payload) == 1
    assert payload[0]["createdBy"] == "Drª. Stephane Darc Magalhaes Goncalves"
    assert payload[0]["signatureLine"] == evolution_lines[-1]
    assert payload[0]["signedAt"] == "2026-04-22T12:00:00"
