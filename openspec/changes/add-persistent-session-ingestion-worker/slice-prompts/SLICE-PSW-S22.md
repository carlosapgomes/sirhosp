# SLICE PSW-S22: Authenticated PDF Form-Download Parity

## Handoff for a Context-Zero Implementer

Implement only PSW-S22 after PSW-S21 is committed. Read project instructions,
all change artifacts, PSW-S21 report, persistent PDF/bridge/navigation code,
and the known working `path2.py` functions
`baixar_pdf_via_formulario_relatorio` and `download_pdf_from_report`. Read PDF,
timeout, normalization, and full-sync tests. Start clean.

Use only synthetic anonymous HTML, ViewState, headers, and PDF bytes.

## Mandatory DeepSeek4-Flash Protocol

1. Record `BASE_REF`, clean status, and requirement matrix.
2. Run official unit baseline before edits; record exit and summary.
3. Add failing direct/fallback tests first and capture a real RED.
4. Implement minimum GREEN using the existing authenticated request context.
5. Run download/filesystem/security inspections and explain occurrences.
6. Run all official gates.
7. Mark tasks/report/commit/push only after complete evidence, then stop.

## Objective

Download evolution PDFs through the already-authenticated context using a direct
URL when valid and the real `#printLinks` JSF form POST fallback otherwise,
without filesystem clinical artifacts or a new login/browser.

## Requirements

- **R1:** Preserve a valid direct authenticated PDF URL path when present.
- **R2:** Parse `#printLinks` action and `javax.faces.ViewState` and POST the
  required `printLinks`/`downloadLinkAjax` form through
  `page.context.request` when direct resolution is unavailable.
- **R3:** Use the existing context cookies/session implicitly; never copy/log
  cookie or authorization values.
- **R4:** Propagate the bounded chunk timeout to GET/POST and classify request
  timeout through PSW-S17 timeout semantics.
- **R5:** Validate response status, content type when available, and `%PDF-`
  signature before parsing.
- **R6:** Raise typed sanitized failures for missing form/action/ViewState,
  non-success HTTP, non-PDF body, timeout, and invalid/empty PDF text.
- **R7:** Keep PDF bytes and extracted text in memory; create no PDF, HTML, or
  debug files.
- **R8:** Preserve normalization, admission key, shared persistence, tab cleanup,
  and no-new-browser/login guarantees.
- **R9:** Keep current subprocess extractor unchanged.

## Expected Scope

Target maximum: 6 versioned files including `tasks.md`.

Expected: persistent PDF module and/or bridge, focused tests, one full-sync
wiring regression if needed, and `tasks.md`.

Forbidden: current `path2.py` modification, models/migrations, chunking,
intent/queue logic, demographics, rollout enablement, real artifacts.

## TDD

### RED

Cover direct GET success, form POST success, missing ViewState, HTTP failure,
request timeout, HTML body with status 200, invalid bytes, and successful
normalization/persistence. Spy on filesystem write APIs and browser/login launch.

### GREEN

Port only the minimal JSF form parsing/request contract. Reuse PDF validation
and normalization already present.

### REFACTOR

Keep acquisition separate from text normalization. Avoid generic HTML-form or
HTTP client abstractions.

## Mandatory Inspection Checks

```bash
rg -n "printLinks|downloadLinkAjax|ViewState|request\.(get|post)" \
  apps/ingestion/extractors
rg -n "write_bytes|write_text|NamedTemporaryFile|TemporaryDirectory|open\(" \
  apps/ingestion/extractors/persistent_evolution_pdf.py \
  apps/ingestion/extractors/real_handle_bridge.py
rg -n "cookie|authorization|password|PDF bytes|raw HTML" \
  apps/ingestion/extractors
```

Explain safe constants/documentation separately from any runtime logging.

## Binary Success Criteria

- [ ] Direct and form-fallback paths pass with synthetic PDF data.
- [ ] Form POST includes required JSF fields.
- [ ] Existing authenticated request context is the only transport.
- [ ] Timeout and invalid payload classifications are correct.
- [ ] No filesystem artifact is created.
- [ ] Normalized events persist with correct admission key.
- [ ] Current worker/path2 remain unchanged.
- [ ] All official gates pass.

## Self-Evaluation Gates

1. Can a report with only `#printLinks` still fail before POST is attempted?
2. Can HTML/error bytes reach PyMuPDF as if valid?
3. Can any sensitive header/cookie/body enter logs or errors?
4. Can this path create a file or new browser/login?
5. Is normalization duplicated in the acquisition code?

Required answers: no, no, no, no, no.

## Validation

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
openspec validate add-persistent-session-ingestion-worker --strict
git diff --name-only "$BASE_REF"...HEAD -- '*.md' | xargs -r markdownlint-cli2
```

## Required Report

Create `/tmp/sirhosp-slice-PSW-S22-report.md` with protocol evidence, direct vs
form request table, RED/GREEN, security/filesystem inspections, snippets,
commands/exit codes, files, risks, and verifier handoff.

Final prompt: implement only PSW-S22. Missing JSF fallback, unsafe body handling,
filesystem output, secret leakage, or absent gate means incomplete.
