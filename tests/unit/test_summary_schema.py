"""Tests for LLM output schema validation (APS-S3 RED phase).

TDD: tests first (RED), then implement (GREEN), then refactor.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _validate(data: dict) -> list[str]:
    """Import and call the schema validator (imported inside each test to allow
    running before the schema module exists)."""
    from apps.summaries.schema import validate_summary_output

    return validate_summary_output(data)


def _valid_output() -> dict:
    """Minimal valid LLM output matching the required contract."""
    return {
        "coverage_start": "2025-01-01",
        "coverage_end": "2025-01-05",
        "estado_estruturado": {
            "motivo_internacao": "Dor abdominal aguda",
            "linha_do_tempo": [],
            "problemas_ativos": [],
            "problemas_resolvidos": [],
            "procedimentos": [],
            "antimicrobianos": [],
            "exames_relevantes": [],
            "intercorrencias": [],
            "pendencias": [],
            "riscos_eventos_adversos": [],
            "situacao_atual": "Paciente estável",
        },
        "resumo_markdown": (
            "# Resumo de Internação\n\n"
            "## Motivo da internação\nDor abdominal aguda."
        ),
        "mudancas_da_rodada": ["Adicionado motivo da internação"],
        "incertezas": ["Diagnóstico diferencial pendente"],
        "evidencias": [
            {
                "event_id": "evt-001",
                "happened_at": "2025-01-01T10:00:00-03:00",
                "author_name": "Dr. Carlos",
                "snippet": "Paciente refere dor abdominal há 3 dias.",
            },
            {
                "event_id": "evt-002",
                "happened_at": "2025-01-02T11:30:00-03:00",
                "author_name": "Dra. Ana",
                "snippet": "Solicitado USG de abdome total.",
            },
        ],
        "alertas_consistencia": [],
    }


# ---------------------------------------------------------------------------
# Valid output
# ---------------------------------------------------------------------------


class TestValidOutput:
    """Happy path: all required fields present and well-formed."""

    def test_valid_output_passes(self):
        """A complete output with all required fields returns no errors."""
        errors = _validate(_valid_output())
        assert errors == []

    def test_valid_output_with_extra_fields_passes(self):
        """Extra fields are forward-compatible and should not cause errors."""
        data = _valid_output()
        data["future_field"] = "some value"
        errors = _validate(data)
        assert errors == []

    def test_valid_output_empty_evidencias_passes(self):
        """A run with zero evidences is valid (e.g., no events in period)."""
        data = _valid_output()
        data["evidencias"] = []
        errors = _validate(data)
        assert errors == []

    def test_valid_output_empty_mudancas_incertezas(self):
        """Empty mudancas_da_rodada and incertezas are valid."""
        data = _valid_output()
        data["mudancas_da_rodada"] = []
        data["incertezas"] = []
        errors = _validate(data)
        assert errors == []


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------


class TestMissingFields:
    """Top-level required fields must be present."""

    def test_missing_estado_estruturado(self):
        data = _valid_output()
        del data["estado_estruturado"]
        errors = _validate(data)
        assert any("estado_estruturado" in e.lower() for e in errors)

    def test_missing_resumo_markdown(self):
        data = _valid_output()
        del data["resumo_markdown"]
        errors = _validate(data)
        assert any("resumo_markdown" in e.lower() for e in errors)

    def test_missing_mudancas_da_rodada(self):
        data = _valid_output()
        del data["mudancas_da_rodada"]
        errors = _validate(data)
        assert any("mudancas_da_rodada" in e.lower() for e in errors)

    def test_missing_incertezas(self):
        data = _valid_output()
        del data["incertezas"]
        errors = _validate(data)
        assert any("incertezas" in e.lower() for e in errors)

    def test_missing_evidencias(self):
        data = _valid_output()
        del data["evidencias"]
        errors = _validate(data)
        assert any("evidencias" in e.lower() for e in errors)

    def test_missing_alertas_consistencia(self):
        data = _valid_output()
        del data["alertas_consistencia"]
        errors = _validate(data)
        assert any("alertas_consistencia" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# Incorrect types
# ---------------------------------------------------------------------------


class TestTypeErrors:
    """Fields must have the correct types."""

    def test_estado_estruturado_not_a_dict(self):
        data = _valid_output()
        data["estado_estruturado"] = "should be a dict"
        errors = _validate(data)
        assert any("estado_estruturado" in e.lower() for e in errors)

    def test_resumo_markdown_not_a_string(self):
        data = _valid_output()
        data["resumo_markdown"] = 12345
        errors = _validate(data)
        assert any("resumo_markdown" in e.lower() for e in errors)

    def test_mudancas_da_rodada_not_a_list(self):
        data = _valid_output()
        data["mudancas_da_rodada"] = "should be a list"
        errors = _validate(data)
        assert any("mudancas_da_rodada" in e.lower() for e in errors)

    def test_incertezas_not_a_list(self):
        data = _valid_output()
        data["incertezas"] = {"a": "b"}
        errors = _validate(data)
        assert any("incertezas" in e.lower() for e in errors)

    def test_evidencias_not_a_list(self):
        data = _valid_output()
        data["evidencias"] = "should be a list"
        errors = _validate(data)
        assert any("evidencias" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# Evidence validation
# ---------------------------------------------------------------------------


class TestEvidenceValidation:
    """Each evidence item must have event_id and snippet."""

    def test_evidence_missing_event_id(self):
        data = _valid_output()
        data["evidencias"] = [
            {
                "happened_at": "2025-01-01T10:00:00-03:00",
                "author_name": "Dr. Carlos",
                "snippet": "text without event id",
            }
        ]
        errors = _validate(data)
        assert any("event_id" in e.lower() for e in errors)

    def test_evidence_missing_snippet(self):
        data = _valid_output()
        data["evidencias"] = [
            {
                "event_id": "evt-001",
                "happened_at": "2025-01-01T10:00:00-03:00",
                "author_name": "Dr. Carlos",
            }
        ]
        errors = _validate(data)
        assert any("snippet" in e.lower() for e in errors)

    def test_evidence_missing_happened_at(self):
        data = _valid_output()
        data["evidencias"] = [
            {
                "event_id": "evt-001",
                "author_name": "Dr. Carlos",
                "snippet": "texto",
            }
        ]
        errors = _validate(data)
        assert any("happened_at" in e.lower() for e in errors)

    def test_evidence_missing_author_name(self):
        data = _valid_output()
        data["evidencias"] = [
            {
                "event_id": "evt-001",
                "happened_at": "2025-01-01T10:00:00-03:00",
                "snippet": "texto",
            }
        ]
        errors = _validate(data)
        assert any("author_name" in e.lower() for e in errors)

    def test_evidence_empty_event_id(self):
        data = _valid_output()
        data["evidencias"] = [
            {
                "event_id": "",
                "happened_at": "2025-01-01T10:00:00-03:00",
                "author_name": "Dr. Carlos",
                "snippet": "text",
            }
        ]
        errors = _validate(data)
        assert any("event_id" in e.lower() for e in errors)

    def test_evidence_empty_snippet(self):
        data = _valid_output()
        data["evidencias"] = [
            {
                "event_id": "evt-001",
                "happened_at": "2025-01-01T10:00:00-03:00",
                "author_name": "Dr. Carlos",
                "snippet": "",
            }
        ]
        errors = _validate(data)
        assert any("snippet" in e.lower() for e in errors)

    def test_evidence_mixed_valid_and_invalid(self):
        data = _valid_output()
        data["evidencias"] = [
            {
                "event_id": "evt-001",
                "happened_at": "2025-01-01T10:00:00-03:00",
                "author_name": "Dr. Carlos",
                "snippet": "valid",
            },
            {
                "happened_at": "2025-01-02T10:00:00-03:00",
                "author_name": "Dra. Ana",
                "snippet": "missing event_id",
            },
            {
                "event_id": "evt-003",
                "happened_at": "2025-01-03T10:00:00-03:00",
                "author_name": "Dr. Paulo",
                "snippet": "also valid",
            },
        ]
        errors = _validate(data)
        assert any("event_id" in e.lower() for e in errors)

    def test_evidence_null_event_id(self):
        data = _valid_output()
        data["evidencias"] = [
            {
                "event_id": None,
                "happened_at": "2025-01-01T10:00:00-03:00",
                "author_name": "Dr. Carlos",
                "snippet": "text",
            }
        ]
        errors = _validate(data)
        assert any("event_id" in e.lower() for e in errors)

    def test_evidence_null_snippet(self):
        data = _valid_output()
        data["evidencias"] = [
            {
                "event_id": "evt-001",
                "happened_at": "2025-01-01T10:00:00-03:00",
                "author_name": "Dr. Carlos",
                "snippet": None,
            }
        ]
        errors = _validate(data)
        assert any("snippet" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# Multiple errors at once
# ---------------------------------------------------------------------------


class TestMultipleErrors:
    """When multiple things are wrong, all errors are reported."""

    def test_multiple_missing_fields(self):
        """Validator reports all missing fields, not just the first."""
        data: dict = {}
        errors = _validate(data)
        assert len(errors) >= 5  # at least the 5 required fields

    def test_multiple_evidence_errors(self):
        """Each invalid evidence item produces an error."""
        data = _valid_output()
        data["evidencias"] = [
            {
                "snippet": "no id",
                "happened_at": "2025-01-01T10:00:00-03:00",
                "author_name": "Dr. Carlos",
            },
            {
                "event_id": "evt-002",
                "happened_at": "2025-01-02T10:00:00-03:00",
                "author_name": "Dra. Ana",
            },
            {
                "event_id": "",
                "happened_at": "",
                "author_name": "",
                "snippet": "",
            },
        ]
        errors = _validate(data)
        assert len(errors) >= 3
