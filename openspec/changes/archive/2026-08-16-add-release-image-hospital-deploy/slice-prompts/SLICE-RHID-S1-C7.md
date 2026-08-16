# Slice Prompt - RHID-S1-C7 Current Census Result Freshness

## Handoff

Start from zero context. Read `AGENTS.md`, `PROJECT_CONTEXT.md`, the complete
`add-release-image-hospital-deploy` OpenSpec change, the RC3 deployment report at
`/tmp/sirhosp-slice-RHID-DEPLOY-EON-report.md`, the RHID-S1-C6 report at
`/tmp/sirhosp-slice-RHID-S1-C6-report.md` and this prompt before editing.

During RC4 acceptance on `eon`, the canonical login succeeded and the official
census persisted 640 records. The adaptive current-census cycle then returned a
nonzero process status because its CSV contained zero rows. A sanitized live DOM
probe proved that the search results do contain occupied sectors. The production
extractor was reading the previous sector's explicit empty row before the JSF
search response replaced the result table. A one-sector probe that waited for the
new result confirmed a 32-row table, downloaded a 7009-byte XLSX and parsed all
32 synthetic-count records without exposing patient values.

Implement only this corrective slice. Do not change authentication, proxy,
official-census, persistence, models, migrations, scheduling or clinical
behavior.

## Goal

Make the current-census extractor wait for a fresh, stable JSF result table after
every `Pesquisar` action before deciding that a sector is empty or exporting its
XLSX.

## Files

Change no more than these five tracked files:

1. `automation/source_system/current_inpatients/extract_census.py`
2. `tests/unit/test_proxy_config.py`
3. `openspec/changes/add-release-image-hospital-deploy/specs/adaptive-census-orchestration/spec.md`
4. `openspec/changes/add-release-image-hospital-deploy/tasks.md`
5. `openspec/changes/add-release-image-hospital-deploy/slice-prompts/SLICE-RHID-S1-C7.md`

The required report under `/tmp` is not a tracked file. Stop and report a blocker
instead of exceeding this limit.

## Required behavior

1. Capture a sanitized result-table state immediately before `Pesquisar`.
2. After the click, ignore the unchanged stale table until a search-result signal
   changes.
3. Wait until the refreshed table is no longer loading and is stable before
   classifying it or starting the XLSX export.
4. The state/signature must not return, log or persist patient names, record
   numbers, cell text, HTML, cookies or credentials. Structural counts and a
   non-reversible in-browser hash are allowed.
5. A refresh timeout must fail the sector attempt instead of accepting stale
   empty output.
6. Preserve the existing retry policy, empty-sector handling, XLSX parser,
   completeness gate and canonical login.

## TDD

1. RED: add a behavioral regression proving that stale explicit-empty state is
   ignored until a fresh non-empty table appears.
2. RED: add a regression proving that the current-census run uses the refreshed
   state before choosing export versus empty-sector handling.
3. GREEN: implement the minimum freshness/stability helpers and wire them around
   `click_pesquisar`.
4. REFACTOR only after the focused tests pass.

## Validation

Run focused tests first, then the official commands required by `AGENTS.md` for
this slice. Run strict OpenSpec validation and Markdown lint for every changed
Markdown file.

After publication, acceptance is a new immutable prerelease on `eon` followed by
an isolated adaptive one-shot cycle with workers stopped. It must return zero,
persist a complete snapshot and report nonzero records before production
services are reactivated.

## Report

Create `/tmp/sirhosp-slice-RHID-S1-C7-report.md` with:

- summary and acceptance checklist;
- changed files;
- before/after snippets for every changed file;
- RED/GREEN evidence and all command results;
- sanitized live evidence used for the diagnosis;
- risks, pending work and the next operational step.

Do not include credentials, cookies, patient values, screenshots, HTML or raw
source-system payloads.

## Stop rule

Commit and push only after focused tests, official gates, OpenSpec validation,
Markdown lint and the report pass. Stop before publishing or modifying the
hospital runtime; release and deployment acceptance are separate operational
steps.
