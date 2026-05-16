"""Extract discharged patients from source system as XLS and upsert records.

Downloads an XLS report from "Pesquisar Pacientes Com Alta" for a given date,
parses it with openpyxl, and upserts DischargeRecord rows by
(prontuario, data_internacao).  Fields that were empty in a previous run
(e.g. saida_em) are updated when they become available.
"""

from __future__ import annotations

import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.discharges.models import DailyDischargeCount, DischargeRecord
from apps.ingestion.extractors.subprocess_utils import (
    SubprocessTimeoutError,
    run_subprocess,
)
from apps.ingestion.models import IngestionRun, IngestionRunStageMetric


def _parse_xls_row(
    row: tuple,
) -> dict[str, Any] | None:
    """Convert an openpyxl row tuple into a patient dict.

    Column layout (0-indexed, from the XLS):
      A(0): JSF internal ID   → ignored
      B(1): Prontuario         → float, convert to int → str
      C(2): Nome               → str
      D(3): Internacao         → DD/MM/YYYY
      E(4): Equipe             → ignored
      F(5): Esp                → str
      G(6): Alta Medica        → DD/MM/YYYY HH:MM or ''
      H(7): Local              → 'L:UN08H' or 'U:0 T'
      I(8): Saida              → DD/MM/YYYY HH:MM or ''
    """
    if len(row) < 9:
        return None

    pront_raw = row[1]
    nome = (row[2] or "").strip()
    data_int = (row[3] or "").strip()
    esp = (row[5] or "").strip()
    alta_str = (row[6] or "").strip()
    local_raw = (row[7] or "").strip()
    saida_str = (row[8] or "").strip()

    # Prontuario
    if pront_raw is None:
        return None
    try:
        prontuario = str(int(float(pront_raw)))
    except (ValueError, TypeError):
        prontuario = str(pront_raw).strip()

    if not prontuario:
        return None

    # Leito: remove "L:" prefix; "U:0 T" → empty
    leito = ""
    if local_raw.startswith("L:"):
        leito = local_raw[2:].strip()
    elif local_raw in ("U:0 T",):
        leito = ""  # unidade inteira, leito nao especificado

    # Datetime fields
    alta_em = _parse_datetime(alta_str)
    saida_em = _parse_datetime(saida_str)

    return {
        "prontuario": prontuario,
        "nome": nome,
        "data_internacao": data_int,
        "especialidade": esp,
        "leito": leito,
        "alta_em": alta_em,
        "saida_em": saida_em,
    }


def _make_aware(dt: datetime | None) -> datetime | None:
    """Convert a naive datetime to timezone-aware."""
    if dt is None:
        return None
    if timezone.is_naive(dt):
        return timezone.make_aware(dt)
    return dt


def _patient_for_raw(p: dict) -> dict:
    """Build a JSON-serializable copy of a patient dict."""
    d = dict(p)
    for key in ("alta_em", "saida_em"):
        val = d.get(key)
        if isinstance(val, datetime):
            d[key] = val.isoformat()
    return d


def _parse_datetime(raw: str) -> datetime | None:
    """Parse 'DD/MM/YYYY HH:MM' or return None."""
    if not raw:
        return None
    try:
        return datetime.strptime(raw, "%d/%m/%Y %H:%M")
    except (ValueError, OverflowError):
        return None


class Command(BaseCommand):
    help = (
        "Extract discharge XLS from source system and upsert DischargeRecord. "
        "Use --date DD/MM/AAAA for historical dates."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--headless",
            action="store_true",
            default=True,
            help="Run Playwright in headless mode.",
        )
        parser.add_argument(
            "--no-headless",
            dest="headless",
            action="store_false",
            help="Run Playwright with visible browser.",
        )
        parser.add_argument(
            "--date",
            type=str,
            default=None,
            help="Target date in DD/MM/AAAA format (default: today).",
        )

    def handle(self, *args, **options):
        headless: bool = options["headless"]
        raw_date: str | None = options.get("date")

        # Resolve date
        today = timezone.localdate()
        if raw_date:
            try:
                ref_date = datetime.strptime(raw_date, "%d/%m/%Y").date()
            except ValueError:
                self.stderr.write(
                    f"Invalid date format: {raw_date}. Use DD/MM/AAAA."
                )
                sys.exit(1)
        else:
            ref_date = today
            raw_date = ref_date.strftime("%d/%m/%Y")

        ref_date_iso = ref_date.isoformat()
        safe_date = raw_date.replace("/", "-")

        self.stdout.write(f"Extracting discharges for {raw_date}...")

        # Resolve credentials
        from django.conf import settings

        source_url = getattr(settings, "SOURCE_SYSTEM_URL", "") or os.getenv(
            "SOURCE_SYSTEM_URL", ""
        )
        username = getattr(settings, "SOURCE_SYSTEM_USERNAME", "") or os.getenv(
            "SOURCE_SYSTEM_USERNAME", ""
        )
        password = getattr(settings, "SOURCE_SYSTEM_PASSWORD", "") or os.getenv(
            "SOURCE_SYSTEM_PASSWORD", ""
        )

        if not all([source_url, username, password]):
            self.stderr.write("Missing source system credentials in settings.")
            sys.exit(1)

        # Path to the extraction script
        script_path = (
            Path(__file__).resolve().parents[4]
            / "automation"
            / "source_system"
            / "discharges"
            / "extract_discharges.py"
        )

        if not script_path.exists():
            self.stderr.write(f"Script not found: {script_path}")
            sys.exit(1)

        # Create IngestionRun
        run = IngestionRun.objects.create(
            status="running",
            intent="discharge_extraction",
            queued_at=timezone.now(),
            processing_started_at=timezone.now(),
            parameters_json={"date": raw_date, "ref_date": ref_date_iso},
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # -- Stage: discharge_extraction (subprocess) -----------------
            ext_stage_start = timezone.now()
            cmd = [
                sys.executable,
                str(script_path),
                "--output-dir",
                str(tmpdir_path),
                "--source-url",
                source_url,
                "--username",
                username,
                "--password",
                password,
                "--date",
                raw_date,
            ]
            cmd.extend(["--reference-date", ref_date_iso])
            if headless:
                cmd.append("--headless")

            self.stdout.write("Running XLS discharge extraction...")
            try:
                result = run_subprocess(cmd, timeout=600, check=False)
            except SubprocessTimeoutError as exc:
                self._record_stage(
                    run, "discharge_extraction", "failed", ext_stage_start,
                    details_json={"error": str(exc)},
                )
                self._mark_run_failed(run, str(exc), "timeout", timed_out=True)
                self.stderr.write(f"Discharge extraction timed out: {exc}")
                sys.exit(1)
            except Exception as exc:
                self._record_stage(
                    run, "discharge_extraction", "failed", ext_stage_start,
                    details_json={"error": str(exc)},
                )
                self._mark_run_failed(run, str(exc), "unexpected_exception")
                self.stderr.write(f"Discharge extraction failed: {exc}")
                sys.exit(1)

            if result.returncode != 0:
                err_msg = result.stderr[:500] if result.stderr else "Unknown error"
                self._record_stage(
                    run, "discharge_extraction", "failed", ext_stage_start,
                    details_json={"returncode": result.returncode},
                )
                self._mark_run_failed(run, err_msg, "source_unavailable")
                self.stderr.write(result.stderr)
                sys.exit(1)

            self._record_stage(
                run, "discharge_extraction", "succeeded", ext_stage_start,
            )

            # -- Stage: discharge_persistence (XLS parse + upsert) --------
            persist_stage_start = timezone.now()

            xls_files = sorted(
                tmpdir_path.glob(f"altas-{safe_date}-*.xlsx"),
                key=lambda p: p.stat().st_mtime,
                reverse=True,
            )
            if not xls_files:
                metrics = {
                    "total_xls": 0, "created": 0, "updated": 0, "errors": 0,
                }
                self._record_stage(
                    run, "discharge_persistence", "succeeded",
                    persist_stage_start, details_json=metrics,
                )
                run.status = "succeeded"
                run.finished_at = timezone.now()
                run.save()
                DailyDischargeCount.objects.update_or_create(
                    date=ref_date, defaults={"count": 0, "raw_data": []},
                )
                self.stdout.write(self.style.SUCCESS(
                    f"No XLS found for {raw_date}."
                ))
                return

            xls_path = xls_files[0]
            self.stdout.write(f"  XLS output: {xls_path}")

            try:
                import openpyxl  # noqa: PLC0415

                wb = openpyxl.load_workbook(xls_path, read_only=True)
                ws = wb.active

                rows = list(ws.iter_rows(values_only=True))
                wb.close()

                if not rows:
                    self.stdout.write("  XLS is empty.")
                    metrics = {
                        "total_xls": 0, "created": 0, "updated": 0, "errors": 0,
                    }
                    self._record_stage(
                        run, "discharge_persistence", "succeeded",
                        persist_stage_start, details_json=metrics,
                    )
                    run.status = "succeeded"
                    run.finished_at = timezone.now()
                    run.save()
                    DailyDischargeCount.objects.update_or_create(
                        date=ref_date, defaults={"count": 0, "raw_data": []},
                    )
                    return

                # Skip header row (first row)
                data_rows = rows[1:] if rows else []
                patients: list[dict[str, Any]] = []
                parse_errors = 0

                for row in data_rows:
                    parsed = _parse_xls_row(row)
                    if parsed is None:
                        parse_errors += 1
                        continue
                    patients.append(parsed)

                self.stdout.write(
                    f"  Rows: {len(data_rows)} | "
                    f"Parsed: {len(patients)} | "
                    f"Errors: {parse_errors}"
                )

                # Upsert DischargeRecords
                created = 0
                updated = 0

                for p in patients:
                    prontuario = p["prontuario"]
                    data_int = p["data_internacao"]

                    existing = DischargeRecord.objects.filter(
                        prontuario=prontuario,
                        data_internacao=data_int,
                    ).first()

                    # Make datetimes timezone-aware
                    alta_em = _make_aware(p["alta_em"])
                    saida_em = _make_aware(p["saida_em"])

                    if existing:
                        changed = False
                        for field, new_val in (
                            ("alta_em", alta_em),
                            ("saida_em", saida_em),
                            ("leito", p["leito"]),
                            ("especialidade", p["especialidade"]),
                            ("nome", p["nome"]),
                        ):
                            old_val = getattr(existing, field)
                            if new_val is not None and new_val != old_val:
                                setattr(existing, field, new_val)
                                changed = True
                        if changed:
                            existing.save()
                            updated += 1
                    else:
                        # Need a daily_count — find or create by alta date
                        count_date = (
                            alta_em.date()
                            if alta_em
                            else ref_date
                        )
                        daily_count, _ = (
                            DailyDischargeCount.objects.get_or_create(
                                date=count_date,
                                defaults={"count": 0, "raw_data": []},
                            )
                        )
                        DischargeRecord.objects.create(
                            daily_count=daily_count,
                            alta_em=alta_em,
                            saida_em=saida_em,
                            prontuario=prontuario,
                            nome=p["nome"],
                            data_internacao=data_int,
                            leito=p["leito"],
                            especialidade=p["especialidade"],
                        )
                        created += 1

                metrics = {
                    "total_xls": len(patients),
                    "created": created,
                    "updated": updated,
                    "errors": parse_errors,
                }

                self.stdout.write(
                    f"  Created: {created} | Updated: {updated} | "
                    f"Errors: {parse_errors}"
                )

                # Persist DailyDischargeCount with JSON-serializable raw_data
                raw_patients = [_patient_for_raw(p) for p in patients]
                DailyDischargeCount.objects.update_or_create(
                    date=ref_date,
                    defaults={
                        "count": len(patients),
                        "raw_data": raw_patients,
                    },
                )

            except Exception as exc:
                self._record_stage(
                    run, "discharge_persistence", "failed",
                    persist_stage_start, details_json={"error": str(exc)},
                )
                self._mark_run_failed(run, str(exc), "unexpected_exception")
                self.stderr.write(f"Discharge processing failed: {exc}")
                sys.exit(1)

            self._record_stage(
                run, "discharge_persistence", "succeeded",
                persist_stage_start, details_json=metrics,
            )

            run.status = "succeeded"
            run.finished_at = timezone.now()
            run.save()

            self.stdout.write(self.style.SUCCESS(
                f"Discharge extraction complete. "
                f"{created} created, {updated} updated."
            ))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _record_stage(
        run: IngestionRun,
        stage_name: str,
        status: str,
        started_at,
        finished_at=None,
        details_json: dict[str, Any] | None = None,
    ) -> None:
        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name=stage_name,
            started_at=started_at,
            finished_at=finished_at or timezone.now(),
            status=status,
            details_json=details_json or {},
        )

    def _mark_run_failed(
        self,
        run: IngestionRun,
        error_message: str,
        failure_reason: str = "",
        timed_out: bool = False,
    ) -> None:
        run.status = "failed"
        run.error_message = error_message
        run.finished_at = timezone.now()
        run.failure_reason = failure_reason
        run.timed_out = timed_out
        run.save()
