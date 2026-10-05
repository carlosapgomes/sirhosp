# Census

The census page filters currently admitted patients by name or record
(`#q`), unit (`#unidade`), specialty (`#especialidade`), situation, and
ordering, with TomSelect-enhanced selects. Proven: playwright (TomSelect
init, unit round-trip through the UI). Demonstrated: mcp (page read with
sidebar, filters, and table). Positive filter against an operator descriptor:
future for MCP.

## Sub-features

- `census-filters-present` renders `Nome ou Registro`, `Setor / Unidade`,
  `Especialidade`, `Situação`, `Ordenar por`, and `Filtrar`.
- `census-tomselect` initializes TomSelect on `#unidade` and `#especialidade`.
- `census-filter-unit` picks a unit through the TomSelect UI, submits, and
  keeps the selection.
- `census-filter-positive` returns exactly the operator-described rows.
- `census-empty` shows the legitimate empty state when nothing matches.
- `census-no-export` never visits `Exportar Excel` during verification.

## How to get to it (user POV)

- Log in and choose `Censo`, or open
  `https://portal-dev.verification.invalid/censo/` directly.
- Read `Censo Hospitalar` with the capture line (`Censo capturado em`).
- Type into `Nome ou Registro` (`#q`), pick `Setor / Unidade` (`#unidade`)
  or `Especialidade` (`#especialidade`), choose `Filtrar`.
- Read the patient table (`Registro`, `Nome`, `Setor / Unidade`).
- Ignore `Exportar Excel` (`/censo/exportar/`): forbidden in verification.

## Driving it with Chrome DevTools MCP

Preconditions:

- Authenticated; on `/censo/` with `RootWebArea` url confirmed.
- For `census-filter-positive`: an operator-supplied synthetic descriptor
  file outside the checkout with `query` (only `q`, `unidade`,
  `especialidade`, `finding`, `ordenar`), `expect_registro`, `expect_nome`,
  and `expect_rows`. Never infer expectations from the table itself.

- **Filters present.** From the snapshot, confirm `Menu principal`, `Censo
  Hospitalar`, `Filtrar`, `Perfil`, `Sair`. End state: filter form read.
- **TomSelect (future for MCP).** Confirm `document.getElementById('unidade').tomselect`
  is initialized before and after submit; pick the first offered unit
  through the `.ts-dropdown .option` UI, submit the GET form, and confirm
  the selection survives. The scripted S2 run proves this path today; an MCP
  round has only read the page so far.
- **Positive filter (future for MCP).** Fill `#q` / pick TomSelect values /
  `select_option` for the rest from the descriptor, submit, and require the
  exact row count plus the expected record and name. Without the descriptor
  file the case is BLOCKED, never PASS. End state: filtered rows matching
  the descriptor, screenshotted.
- **No export.** The `Exportar Excel` link is visible in the snapshot but
  never clicked; `list_network_requests` must show no export navigation.
  End state: export untouched, recorded in notes.
- **Proof.** `shot-censo.png` plus sanitized snapshot under
  `/tmp/sirhosp-verification-mcp/<run-id>/`, with the feature id and entry
  point recorded.

## Gotchas

- TomSelect replaces the native select UI: set values through the dropdown
  options, not by typing into the hidden select.
- Selects re-initialize after submit; assert TomSelect presence again on the
  filtered page, not just before submit.
- An old photo with workers stopped is a legitimate state: never run
  ingestion to turn the badge green.
- Filter option values come from the live dev dataset; hard-coding a unit
  from another round makes the check brittle. Read options first.
- Filter markup lives in `apps/services_portal/templates/services_portal/censo.html`;
  selector changes there must update this file and its proof.
