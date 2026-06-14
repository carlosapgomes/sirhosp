# Recovery Command Handoff

## Canonical entry point

The canonical recovery entry point is:

```bash
python manage.py recover_historical_data --date DD/MM/AAAA
```

All historical data recovery should use this Django management command. It
orchestrates the four extraction services (discharges, admissions, deaths,
official census) via Python-callable service functions, supports dry-run
planning, fail-fast mode, extractor selection, and returns a deterministic exit
status.

## Legacy shell script

`scripts/recover-historical-data.sh` is a legacy helper that predates the Django
command. It is **kept unchanged** (except for a prominent header comment) to
support existing operator automation and documentation that references it
directly.

Operators SHOULD use `python manage.py recover_historical_data` for new
workflows. The legacy script:

- still invokes four `python manage.py extract_*` commands via Docker Compose
  subprocess, one per extractor per day;
- does not call the new Django recovery command;
- may diverge in error handling, output format, and metadata tracking from the
  canonical command.

No future slice should add features to the legacy shell script. If the script
becomes unused, it may be removed in a separate change.

## Non-goals confirmed

- **No persistent recovery job model or migration** was added in this change.
  The `recover_historical_data` command relies only on the per-extractor
  `IngestionRun` records created by extractor services.
- **No recovery attempt table** was added.
- **No Celery, Redis, or background orchestration infrastructure** was added.
  Coordination remains via synchronous Python execution and the database state
  already written by extractor services.
- **No new persistent orchestration state** was introduced.

## Existing extractor commands remain supported

The following existing Django management commands remain available and supported
as individual CLI wrappers:

- `python manage.py extract_discharges`
- `python manage.py extract_admissions`
- `python manage.py extract_deaths`
- `python manage.py extract_official_census`

The recovery command calls their underlying Python service functions directly
and does not use `call_command`, subprocess, or shell scripts as the
integration boundary.

## Known caveats

### Pre-existing unrelated test failures

The following test was already failing before this change and is unrelated to
the recovery command:

```text
tests/unit/test_report_suspected_stale_inpatients_command.py
  ::test_reports_only_active_admissions_without_events_in_last_72h
```

Likely a pre-existing logic issue in the stale inpatient detection command.

### Pre-existing unrelated lint errors

- `apps/services_portal/urls.py:23` — line length (101 > 100)
- Various `test_services_portal_*` files — unused variables

All pre-existing, none in code modified by this change.

### Pre-existing type-check error

```text
tests/unit/test_services_portal_sectors.py:
  Source file found twice under different module names
```

Pre-existing mypy module resolution issue, not related to this change.
