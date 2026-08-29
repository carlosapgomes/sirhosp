"""CFC-S3: aggregate characterization report generator + decision-ADR
validator.

Reads the stdout capture of the CFC-S1 command
``characterize_fullsync_failures`` (aggregate-only by contract) and
renders a Markdown report with five fixed sections: cohort, cohort
reasons, stage timing, hourly histogram and contrast baseline. Fails
closed when the capture carries an identity sentinel (patient-record
keys, URLs, raw error markers, clinical-text markers) or is malformed.

Also validates a decision ADR against objective rules: no identity or
clinical content; every hypothesis verdict
(``confirmed``/``refuted``/``inconclusive``) with evidence; a
recommendation (corrective change or next experiment) present and
coherent with the verdicts.

This module is read-only: it never queries the database, never mutates
state and never touches the network. The management command only reads
and writes the explicit ``--input``/``--output``/``--check-adr`` files.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

_NONE_TEXT = "none"

# ---------------------------------------------------------------------------
# Identity sentinel scanner (R4) — same fail-closed discipline as CFC-S1 and
# RPAP-S5: the characterization stdout is aggregate-only by contract, so any
# of these identity carriers in the input means the capture is corrupted.
# ---------------------------------------------------------------------------

_IDENTITY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "parameter_payload_key",
        re.compile(r"\bparameters_json\b|\bpatient_record\b"),
    ),
    ("patient_identifier", re.compile(r"\bprontuario\b|\bpatient_id\b")),
    ("url", re.compile(r"https?://\S+")),
    (
        "raw_error_marker",
        re.compile(r"\berror_message\b|\berro bruto\b|\bTraceback\b"),
    ),
    (
        "clinical_text_marker",
        re.compile(r"\bPRIV-PAT\b|\bPRIV-TEXTO\b|\bSENTINEL\b"),
    ),
)


def scan_identity_sentinels(text: str) -> tuple[str, ...]:
    """Kinds of identity carriers found in ``text`` (empty tuple = clean)."""
    return tuple(
        kind
        for kind, pattern in _IDENTITY_PATTERNS
        if pattern.search(text) is not None
    )


# ---------------------------------------------------------------------------
# Parsed report model (aggregates only)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StageProfile:
    """Duration profile of one stage (aggregate, seconds)."""

    stage_name: str
    median_seconds: float
    p90_seconds: float
    samples: int


@dataclass(frozen=True)
class CharacterizationReport:
    """Full aggregate characterization parsed from the CFC-S1 stdout."""

    window_hours: int
    min_attempts: int
    patients: int
    failed_runs: int
    attempts_median: float | None
    attempts_max: int
    first_failure_age_hours: int | None
    last_failure_age_hours: int | None
    cohort_reasons: tuple[tuple[str, int], ...]
    contrast_reasons: tuple[tuple[str, int], ...]
    stage_profiles: tuple[StageProfile, ...]
    terminal_failing_stages: tuple[tuple[str, int], ...]
    hourly: tuple[tuple[int, int], ...]


# ---------------------------------------------------------------------------
# Parsing (R1) — strict: missing/unknown lines, bad numbers or a wrong
# bucket count fail closed.
# ---------------------------------------------------------------------------


def parse_characterization_output(stdout: str) -> CharacterizationReport:
    fields = _section_fields(stdout)
    required = (
        "fullsync_failure_characterization",
        "cohort",
        "cohort_failure_reasons",
        "contrast_failure_reasons",
        "stage_profiles",
        "terminal_failing_stages",
        "hourly_histogram",
    )
    missing = [key for key in required if key not in fields]
    if missing:
        raise ValueError(f"missing characterization line(s): {','.join(missing)}")

    header = _kv(fields["fullsync_failure_characterization"])
    cohort = _kv(fields["cohort"])
    return CharacterizationReport(
        window_hours=_int(header["window_hours"]),
        min_attempts=_int(header["min_attempts"]),
        patients=_int(cohort["patients"]),
        failed_runs=_int(cohort["failed_runs"]),
        attempts_median=_optional_float(cohort["attempts_median"]),
        attempts_max=_int(cohort["attempts_max"]),
        first_failure_age_hours=_optional_int(cohort["first_failure_age_hours"]),
        last_failure_age_hours=_optional_int(cohort["last_failure_age_hours"]),
        cohort_reasons=_pairs(fields["cohort_failure_reasons"]),
        contrast_reasons=_pairs(fields["contrast_failure_reasons"]),
        stage_profiles=_profiles(fields["stage_profiles"]),
        terminal_failing_stages=_pairs(fields["terminal_failing_stages"]),
        hourly=_hourly(fields["hourly_histogram"]),
    )


def _section_fields(stdout: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for raw_line in stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        key, sep, value = line.partition(":")
        if not sep or not key or not value:
            raise ValueError(f"malformed characterization line: {key or '(empty)'}")
        fields[key.strip()] = value.strip()
    return fields


def _kv(text: str) -> dict[str, str]:
    return dict(
        item.partition("=")[::2] for item in text.split() if "=" in item
    )


def _profile_kv(text: str) -> dict[str, str]:
    return dict(
        item.partition("=")[::2] for item in text.split(",") if "=" in item
    )


def _int(text: str) -> int:
    return int(text)


def _optional_int(text: str) -> int | None:
    return None if text == _NONE_TEXT else int(text)


def _optional_float(text: str) -> float | None:
    return None if text == _NONE_TEXT else float(text)


def _pairs(text: str) -> tuple[tuple[str, int], ...]:
    if text == _NONE_TEXT:
        return ()
    return tuple(
        (label, int(count))
        for label, count in (item.split("=", 1) for item in text.split(","))
    )


def _profiles(text: str) -> tuple[StageProfile, ...]:
    if text == _NONE_TEXT:
        return ()
    profiles: list[StageProfile] = []
    for item in text.split("|"):
        name, sep, body = item.partition(":")
        if not sep:
            raise ValueError(f"malformed stage profile: {name}")
        metrics = _profile_kv(body)
        profiles.append(
            StageProfile(
                stage_name=name,
                median_seconds=float(metrics["median_seconds"]),
                p90_seconds=float(metrics["p90_seconds"]),
                samples=_int(metrics["samples"]),
            )
        )
    return tuple(profiles)


def _hourly(text: str) -> tuple[tuple[int, int], ...]:
    buckets: list[tuple[int, int]] = []
    for item in text.split(","):
        label, sep, value = item.partition("=")
        if label != "hour" or not sep:
            raise ValueError(f"malformed hourly bucket: {item}")
        hour, count = value.split("=", 1)
        buckets.append((_int(hour), _int(count)))
    if len(buckets) != 24:
        raise ValueError(
            f"hourly histogram must have 24 buckets, got {len(buckets)}"
        )
    return tuple(buckets)


# ---------------------------------------------------------------------------
# Markdown rendering (R1) — five fixed sections, aggregates only
# ---------------------------------------------------------------------------


def render_report_markdown(report: CharacterizationReport) -> str:
    lines: list[str] = [
        "# Relatório de caracterização — coorte fail-only de full-sync",
        "",
        "Gerado a partir da saída agregada do command read-only "
        "`characterize_fullsync_failures` (CFC-S1). Somente agregados: "
        "nenhum identificador de paciente, run, parâmetro, texto clínico, "
        "URL ou erro bruto.",
        "",
        f"Janela: `{report.window_hours}h` — "
        f"`--min-attempts={report.min_attempts}`.",
        "",
        "## 1. Coorte fail-only",
        "",
        "| Métrica | Valor |",
        "| --- | --- |",
        f"| Pacientes na coorte | {report.patients} |",
        f"| Runs falhos da coorte | {report.failed_runs} |",
        "| Mediana de tentativas por paciente | "
        f"{_optional_number_text(report.attempts_median)} |",
        f"| Máximo de tentativas por paciente | {report.attempts_max} |",
        "| Idade da primeira falha (h) | "
        f"{_optional_int_text(report.first_failure_age_hours)} |",
        "| Idade da última falha (h) | "
        f"{_optional_int_text(report.last_failure_age_hours)} |",
        "",
        "## 2. Reasons da coorte",
        "",
    ]
    lines.extend(_pairs_table(report.cohort_reasons, "Reason", "Contagem"))
    lines.extend(["", "## 3. Timing por estágio", ""])
    if report.stage_profiles:
        lines.extend(
            [
                "| Estágio | Mediana (s) | p90 (s) | Amostras |",
                "| --- | ---: | ---: | ---: |",
            ]
        )
        lines.extend(
            f"| {profile.stage_name} | {profile.median_seconds:.1f} | "
            f"{profile.p90_seconds:.1f} | {profile.samples} |"
            for profile in report.stage_profiles
        )
    else:
        lines.append("Nenhum perfil de estágio na janela.")
    lines.extend(["", "Estágio terminal falho:", ""])
    lines.extend(
        _pairs_table(report.terminal_failing_stages, "Estágio", "Contagem")
    )
    lines.extend(["", "## 4. Histograma horário", ""])
    nonzero = [(hour, count) for hour, count in report.hourly if count > 0]
    if nonzero:
        lines.extend(["| Hora (UTC) | Falhas |", "| ---: | ---: |"])
        lines.extend(f"| {hour} | {count} |" for hour, count in nonzero)
        lines.append(f"| Total | {sum(count for _, count in nonzero)} |")
    else:
        lines.append("Nenhuma falha na janela.")
    lines.extend(["", "## 5. Contraste (fail-then-ok)", ""])
    lines.extend(_pairs_table(report.contrast_reasons, "Reason", "Contagem"))
    return "\n".join(lines) + "\n"


def generate_report(stdout: str) -> str:
    """Fail-closed pipeline: scan -> parse -> render."""
    sentinels = scan_identity_sentinels(stdout)
    if sentinels:
        raise ValueError(
            "input rejected: identity sentinel present "
            f"({','.join(sentinels)})"
        )
    return render_report_markdown(parse_characterization_output(stdout))


def _optional_number_text(value: float | None) -> str:
    return _NONE_TEXT if value is None else f"{value:g}"


def _optional_int_text(value: int | None) -> str:
    return _NONE_TEXT if value is None else str(value)


def _pairs_table(
    pairs: tuple[tuple[str, int], ...], label: str, value: str
) -> list[str]:
    if not pairs:
        return ["Nenhuma ocorrência na janela."]
    rows = [f"| {label} | {value} |", "| --- | ---: |"]
    rows.extend(f"| {name} | {count} |" for name, count in pairs)
    return rows


# ---------------------------------------------------------------------------
# Decision ADR validator (R2) — objective rules
# ---------------------------------------------------------------------------

_VERDICTS = ("confirmed", "refuted", "inconclusive")
_VERDICT_HEADER_RE = re.compile(
    r"^\|\s*Hipótese\s*\|\s*Veredito\s*\|\s*Evidência\s*\|"
)
_SECTION_RE = re.compile(
    r"^##\s*(Correção recomendada|Próximo experimento)\s*$"
)


def validate_decision_adr(adr_text: str) -> tuple[str, ...]:
    """Objective ADR rules; empty tuple means the ADR is valid.

    - no identity/clinical content (same scanner as the report input);
    - every hypothesis verdict row declares exactly one of
      confirmed/refuted/inconclusive AND a non-empty evidence cell;
    - a recommendation exists: `## Correção recomendada` when at least one
      hypothesis is confirmed, otherwise `## Próximo experimento`.
    """
    errors: list[str] = []
    for kind in scan_identity_sentinels(adr_text):
        errors.append(f"ADR contains identity sentinel: {kind}")

    rows = _extract_verdict_rows(adr_text)
    if not rows:
        errors.append(
            "ADR must declare at least one hypothesis verdict row "
            "(table `| Hipótese | Veredito | Evidência |`)"
        )
    for index, (verdict, evidence) in enumerate(rows, start=1):
        if verdict not in _VERDICTS:
            errors.append(
                f"hypothesis row {index}: verdict must be exactly "
                "confirmed/refuted/inconclusive"
            )
        if not evidence:
            errors.append(f"hypothesis row {index}: verdict without evidence")

    has_correction = _section_has_content(adr_text, "Correção recomendada")
    has_next_experiment = _section_has_content(adr_text, "Próximo experimento")
    if not (has_correction or has_next_experiment):
        errors.append(
            "ADR must include a recommendation: `## Correção recomendada` "
            "or `## Próximo experimento`"
        )
    confirmed = any(verdict == "confirmed" for verdict, _ in rows)
    if confirmed and not has_correction:
        errors.append(
            "confirmed hypothesis requires a `## Correção recomendada` section"
        )
    if not confirmed and not has_next_experiment:
        errors.append(
            "no confirmed hypothesis requires a `## Próximo experimento` section"
        )
    return tuple(errors)


def _extract_verdict_rows(adr_text: str) -> tuple[tuple[str, str], ...]:
    lines = adr_text.splitlines()
    start = next(
        (i for i, line in enumerate(lines) if _VERDICT_HEADER_RE.match(line)),
        None,
    )
    if start is None:
        return ()
    rows: list[tuple[str, str]] = []
    for line in lines[start + 2 :]:
        stripped = line.strip()
        if not stripped.startswith("|"):
            break
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if len(cells) < 3:
            break
        rows.append((cells[1], cells[2]))
    return tuple(rows)


def _section_has_content(adr_text: str, heading: str) -> bool:
    lines = adr_text.splitlines()
    for index, line in enumerate(lines):
        if _SECTION_RE.match(line.strip()) and line.strip().endswith(heading):
            body = [
                next_line.strip()
                for next_line in lines[index + 1 :]
                if next_line.strip() and not next_line.strip().startswith("#")
            ]
            return bool(body)
    return False


# ---------------------------------------------------------------------------
# Management command (thin wrapper, file I/O only)
# ---------------------------------------------------------------------------


class Command(BaseCommand):
    help = (
        "Generate the aggregate characterization report from a CFC-S1 "
        "stdout capture (fails closed on identity sentinels and malformed "
        "input) and optionally validate the decision ADR."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--input",
            required=True,
            help="Path to the CFC-S1 `characterize_fullsync_failures` "
            "stdout capture.",
        )
        parser.add_argument(
            "--output",
            required=True,
            help="Path to write the generated Markdown report.",
        )
        parser.add_argument(
            "--check-adr",
            default=None,
            help="Optional path to a decision ADR to validate.",
        )

    def handle(self, *args, **options):
        input_text = self._read_text(Path(options["input"]))
        try:
            report_md = generate_report(input_text)
        except ValueError as exc:
            raise CommandError(str(exc)) from exc
        output_path = Path(options["output"])
        try:
            output_path.write_text(report_md, encoding="utf-8")
        except OSError as exc:
            raise CommandError(
                f"cannot write report: {exc.strerror or exc}"
            ) from exc
        self.stdout.write(
            f"report written: {output_path} ({len(report_md)} chars)"
        )
        if options["check_adr"]:
            self._check_adr(Path(options["check_adr"]))

    def _check_adr(self, path: Path) -> None:
        adr_text = self._read_text(path)
        errors = validate_decision_adr(adr_text)
        if errors:
            for error in errors:
                self.stderr.write(f"adr validation: {error}")
            raise CommandError(
                f"decision ADR invalid: {len(errors)} error(s)"
            )
        self.stdout.write(f"decision ADR valid: {path}")

    @staticmethod
    def _read_text(path: Path) -> str:
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise CommandError(
                f"cannot read {path}: {exc.strerror or exc}"
            ) from exc
