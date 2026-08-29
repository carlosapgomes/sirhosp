"""CFC-S3 unit tests: aggregate report generator + decision-ADR validator.

Covers the vertical slice requirements:

- R1: the report generator reads the CFC-S1 stdout capture and renders a
  Markdown report with five fixed sections (cohort, cohort reasons, stage
  timing, hourly histogram, contrast) — aggregates only, fail closed on
  identity sentinels and malformed input;
- R2: the decision-ADR validator enforces objective rules — no identity or
  clinical content, every hypothesis verdict (confirmed/refuted/
  inconclusive) with evidence, a recommendation (corrective change or next
  experiment) present and coherent with the verdicts;
- R3: the operational runbook documents the one-shot read-only
  characterization, the report/ADR commands, the synthetic lab and the
  explicit absence of mutation;
- R4: report, ADR samples and runbook carry aggregates only (identity
  scanner + markdown lint gate).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.ingestion.management.commands.generate_fullsync_failure_report import (
    generate_report,
    parse_characterization_output,
    scan_identity_sentinels,
    validate_decision_adr,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

_HOURLY_BUCKETS: tuple[tuple[int, int], ...] = (
    (0, 0),
    (1, 0),
    (2, 0),
    (3, 3),
    (4, 0),
    (5, 0),
    (6, 0),
    (7, 4),
    (8, 0),
    (9, 0),
    (10, 0),
    (11, 0),
    (12, 3),
    (13, 0),
    (14, 0),
    (15, 0),
    (16, 0),
    (17, 0),
    (18, 0),
    (19, 0),
    (20, 0),
    (21, 0),
    (22, 0),
    (23, 0),
)


def _hourly_line(buckets: tuple[tuple[int, int], ...] = _HOURLY_BUCKETS) -> str:
    """Render the CFC-S1 hourly_histogram line for the given buckets."""
    counts = dict(buckets)
    return "hourly_histogram: " + ",".join(
        f"hour={hour}={counts.get(hour, 0)}" for hour in range(24)
    )


CANONICAL_STDOUT = "\n".join(
    (
        "fullsync_failure_characterization: window_hours=168 min_attempts=3",
        "cohort: patients=2 failed_runs=10 attempts_median=5 attempts_max=6 "
        "first_failure_age_hours=100 last_failure_age_hours=20",
        "cohort_failure_reasons: invalid_payload=6,none=1,timeout=3",
        "contrast_failure_reasons: invalid_payload=1,timeout=3",
        "stage_profiles: admissions_capture:median_seconds=45.0,"
        "p90_seconds=60.0,samples=2|evolution_extraction:median_seconds=30.0,"
        "p90_seconds=45.0,samples=5",
        "terminal_failing_stages: evolution_extraction=5,none=5",
        _hourly_line(),
    )
) + "\n"

EMPTY_STDOUT = "\n".join(
    (
        "fullsync_failure_characterization: window_hours=168 min_attempts=3",
        "cohort: patients=0 failed_runs=0 attempts_median=none "
        "attempts_max=0 first_failure_age_hours=none "
        "last_failure_age_hours=none",
        "cohort_failure_reasons: none",
        "contrast_failure_reasons: none",
        "stage_profiles: none",
        "terminal_failing_stages: none",
        _hourly_line(tuple((hour, 0) for hour in range(24))),
    )
) + "\n"

VALID_ADR = """\
# ADR-0008 — Decisão de correção da coorte fail-only de full-sync

## Status

Proposed

## Contexto

A caracterização read-only da coorte fail-only de full-sync na janela de
168h com `--min-attempts=3` reportou 2 pacientes na coorte, 10 runs
falhos, mediana de 5 tentativas por paciente e última falha há 20h.

## Hipóteses e vereditos

| Hipótese | Veredito | Evidência |
| --- | --- | --- |
| H1 — timeout por volume/deadline | confirmed | Relatório §3 + verdicts.json (H1) |
| H2 — invalid_payload por conteúdo | confirmed | Relatório §2 + verdicts.json (H2) |

## Causa comprovada

H1 e H2 reproduzidas no laboratório sintético contra o código real.

## Correção recomendada

Abrir change futuro com deadline progressivo por volume e revisão das
validações de conteúdo, com controle de regressão.

## Alternativas rejeitadas

1. Aumentar o deadline global por precaução — rejeitada por corrigir por
   suposição.

## Consequências

### Positivas

- Causa comprovada antes da correção.

### Negativas / Trade-offs

- Custo de implementação do change futuro.
"""


class TestReportGenerator:
    def test_generates_report_with_five_fixed_sections(self):
        report = generate_report(CANONICAL_STDOUT)
        for section in (
            "## 1. Coorte fail-only",
            "## 2. Reasons da coorte",
            "## 3. Timing por estágio",
            "## 4. Histograma horário",
            "## 5. Contraste (fail-then-ok)",
        ):
            assert section in report
        assert "| Pacientes na coorte | 2 |" in report
        assert "| invalid_payload | 6 |" in report
        assert "| evolution_extraction | 30.0 | 45.0 | 5 |" in report
        assert "| 3 | 3 |" in report
        assert "| Total | 10 |" in report

    def test_empty_database_report_is_aggregate_and_zeroed(self):
        report = generate_report(EMPTY_STDOUT)
        assert "| Pacientes na coorte | 0 |" in report
        assert "| Mediana de tentativas por paciente | none |" in report
        assert "Nenhum perfil de estágio na janela." in report
        assert "Nenhuma falha na janela." in report
        assert "Nenhuma ocorrência na janela." in report

    def test_parser_handles_none_and_hourly_buckets(self):
        parsed = parse_characterization_output(CANONICAL_STDOUT)
        assert parsed.patients == 2
        assert parsed.attempts_median == 5.0
        assert parsed.first_failure_age_hours == 100
        assert parsed.cohort_reasons == (
            ("invalid_payload", 6),
            ("none", 1),
            ("timeout", 3),
        )
        assert parsed.contrast_reasons == (("invalid_payload", 1), ("timeout", 3))
        assert parsed.hourly[3] == (3, 3)
        assert parsed.hourly[7] == (7, 4)
        assert parsed.hourly[12] == (12, 3)
        assert len(parsed.hourly) == 24

    def test_malformed_input_fails_closed(self):
        for broken in (
            "cohort: patients=x failed_runs=0",
            "hourly_histogram: hour=0=0,hour=1=0",
            "unknown_line: whatever",
            "not a kv line",
        ):
            with pytest.raises(ValueError):
                parse_characterization_output(broken)

    def test_report_is_deterministic(self):
        assert generate_report(CANONICAL_STDOUT) == generate_report(CANONICAL_STDOUT)


class TestIdentityScanner:
    @pytest.mark.parametrize(
        "payload",
        (
            "prontuario=99999",
            'parameters_json={"patient_record": "X"}',
            "https://priv-sentinel.invalid/x",
            "error_message=raw boom",
            "erro bruto no download",
            "PRIV-PAT-CFC-042",
            "PRIV-TEXTO-CLINICO-CFC",
        ),
    )
    def test_scanner_detects_identity_carriers(self, payload):
        kinds = scan_identity_sentinels(CANONICAL_STDOUT + "\n" + payload)
        assert kinds, f"scanner missed payload: {payload}"

    def test_scanner_accepts_clean_aggregate_input(self):
        assert scan_identity_sentinels(CANONICAL_STDOUT) == ()

    def test_generator_fails_closed_and_sanitizes_message(self):
        leaked = CANONICAL_STDOUT + "\nprontuario=PRIV-PAT-CFC-042"
        with pytest.raises(ValueError) as exc:
            generate_report(leaked)
        message = str(exc.value)
        assert "identity sentinel" in message
        assert "PRIV-PAT-CFC-042" not in message


class TestAdrValidator:
    def test_validator_approves_filled_template(self):
        assert validate_decision_adr(VALID_ADR) == ()

    def test_validator_rejects_verdict_without_evidence(self):
        bad = VALID_ADR.replace(
            "| Relatório §3 + verdicts.json (H1) |",
            "| |",
        )
        errors = validate_decision_adr(bad)
        assert any("without evidence" in error for error in errors)

    def test_validator_rejects_invalid_verdict_value(self):
        bad = VALID_ADR.replace("| confirmed | Relatório §3", "| maybe | Relatório §3")
        errors = validate_decision_adr(bad)
        assert any("exactly" in error for error in errors)

    def test_validator_rejects_missing_recommendation(self):
        no_recommendation = VALID_ADR.replace(
            "## Correção recomendada\n\nAbrir change futuro com deadline "
            "progressivo por volume e revisão das\nvalidações de conteúdo, "
            "com controle de regressão.\n",
            "",
        )
        errors = validate_decision_adr(no_recommendation)
        assert any("recommendation" in error for error in errors)

    def test_validator_requires_next_experiment_when_nothing_confirmed(self):
        refuted = VALID_ADR.replace("confirmed", "refuted").replace(
            "## Correção recomendada\n\nAbrir change futuro com deadline "
            "progressivo por volume e revisão das\nvalidações de conteúdo, "
            "com controle de regressão.\n",
            "## Próximo experimento\n\nMedir o perfil de duração real dos "
            "estágios em produção.\n",
        )
        assert validate_decision_adr(refuted) == ()

    def test_validator_rejects_identifier_in_adr(self):
        bad = VALID_ADR.replace("168h com `--min-attempts=3`", "prontuario=99999")
        errors = validate_decision_adr(bad)
        assert any("identity sentinel" in error for error in errors)

    def test_validator_rejects_empty_verdict_table(self):
        no_table = VALID_ADR.split("## Hipóteses e vereditos")[0] + VALID_ADR.split(
            "## Causa comprovada"
        )[1]
        errors = validate_decision_adr(no_table)
        assert any("at least one hypothesis" in error for error in errors)


class TestCommandEndToEnd:
    def test_command_writes_report_and_validates_adr(self, tmp_path):
        capture = tmp_path / "capture.txt"
        capture.write_text(CANONICAL_STDOUT, encoding="utf-8")
        output = tmp_path / "report.md"
        valid_adr = tmp_path / "valid-adr.md"
        valid_adr.write_text(VALID_ADR, encoding="utf-8")
        call_command(
            "generate_fullsync_failure_report",
            input=str(capture),
            output=str(output),
            check_adr=str(valid_adr),
        )
        text = output.read_text(encoding="utf-8")
        assert "## 1. Coorte fail-only" in text

    def test_command_rejects_invalid_adr(self, tmp_path):
        capture = tmp_path / "capture.txt"
        capture.write_text(CANONICAL_STDOUT, encoding="utf-8")
        output = tmp_path / "report.md"
        bad_adr = tmp_path / "bad-adr.md"
        bad_adr.write_text(VALID_ADR.replace("confirmed", "maybe"), encoding="utf-8")
        with pytest.raises(CommandError):
            call_command(
                "generate_fullsync_failure_report",
                input=str(capture),
                output=str(output),
                check_adr=str(bad_adr),
            )

    def test_command_fails_closed_on_sentinel_capture(self, tmp_path):
        capture = tmp_path / "leaked.txt"
        capture.write_text(
            CANONICAL_STDOUT + "\nprontuario=PRIV-PAT-CFC-042", encoding="utf-8"
        )
        output = tmp_path / "report.md"
        with pytest.raises(CommandError):
            call_command(
                "generate_fullsync_failure_report",
                input=str(capture),
                output=str(output),
            )


class TestRunbookConsistency:
    def test_runbook_documents_commands_artifacts_and_no_mutation(self):
        text = (REPO_ROOT / "deploy" / "README.md").read_text(encoding="utf-8")
        assert "characterize_fullsync_failures" in text
        assert "generate_fullsync_failure_report" in text
        assert "fullsync_failure_lab" in text
        assert "verdicts.json" in text
        assert "--apply" in text
        assert "read-only" in text
        assert "mutação" in text
