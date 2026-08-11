# Slice Prompt - RHID-S1-C6 Canonical Census Login

## Handoff

Start from zero context. Read `AGENTS.md`, `PROJECT_CONTEXT.md`, the complete
`add-release-image-hospital-deploy` OpenSpec change, the RC3 deployment report at
`/tmp/sirhosp-slice-RHID-DEPLOY-EON-report.md`, the RHID-S1-C5 report, the two
census automation scripts, the existing legacy session bootstrap and this prompt
before editing.

During RC3 acceptance on `eon`, both census extractors reached and rendered the
source-system login page directly, but timed out while clicking the `Entrar`
button. A credential-free diagnostic probe reproduced that timeout while also
showing HTTP 200 for the authenticated page. A second probe using the
production-proven password-Enter submission plus populated `#tempoSessao`
readiness completed successfully without a proxy. The route, DNS, TLS,
credentials and login page are therefore healthy; the duplicated button-click
login in the census scripts is the failed interaction.

## Scope and file limit

Modify no more than these seven tracked files:

1. `apps/ingestion/extractors/legacy_session_bootstrap.py`
2. `automation/source_system/official_census/extract_official_census.py`
3. `automation/source_system/current_inpatients/extract_census.py`
4. `tests/unit/test_proxy_config.py`
5. `openspec/changes/add-release-image-hospital-deploy/specs/adaptive-census-orchestration/spec.md`
6. `openspec/changes/add-release-image-hospital-deploy/tasks.md`
7. `openspec/changes/add-release-image-hospital-deploy/slice-prompts/SLICE-RHID-S1-C6.md`

Do not change network topology, Compose, proxy configuration, census parsing,
sector traversal, persistence, models, migrations, scheduling or clinical
behavior. Do not record credentials, source-system values, cookies, page bodies
or patient data. If another tracked file is required, stop and report the
blocker instead of expanding scope.

## Required change

1. Add failing behavioral regression tests proving both census scripts use
   password-Enter submission and authenticated readiness instead of clicking
   the login button.
2. Make the existing `bootstrap_legacy_session` importable by standalone
   automation subprocesses without initializing Django models.
3. Reuse that single canonical bootstrap in both census scripts with the
   existing source URL, username, password and 180-second timeout.
4. Preserve proxy handling, browser lifecycle, dialog handling and all
   post-login extraction behavior.
5. Add a delta requirement recording the production-proven login contract and
   the absence of a required hospital proxy.

## Acceptance criteria

- [ ] RED fails for both scripts because they still use the button-click login.
- [ ] Both scripts delegate authentication to `bootstrap_legacy_session`.
- [ ] Login submission presses Enter in the password field.
- [ ] Readiness requires a populated, numeric three-part `#tempoSessao`.
- [ ] No login-button click or generic page-stability wait remains in either
      census login path.
- [ ] The standalone import path does not require Django app initialization.
- [ ] Focused tests, strict OpenSpec, official check/unit/lint/typecheck and
      Markdown lint pass.
- [ ] `/tmp/sirhosp-slice-RHID-S1-C6-report.md` records RED/GREEN evidence,
      before/after fragments, commands, results and risks without sensitive
      data.

## Stop rule

Use TDD: RED, minimum GREEN, then controlled cleanup. Run official container
commands for final gate claims. Update task checkboxes only after evidence
exists. Create the required report, commit and push the correction, then stop
this slice before publishing or modifying the hospital runtime.
