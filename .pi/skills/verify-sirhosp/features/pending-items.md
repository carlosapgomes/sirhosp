# Pending items (read-only)

The Pendências sidebar entry opens `/pendencias/`: hospital-wide indicators,
the current inpatients' pending items grouped per patient (or one row per
item), GET filters, a collapsible per-item history, and — from a patient's
admission page — the contextual per-episode list. The ephemeral `verify_user`
holds no `Desospitalização` membership, so every mapped journey is a reader
journey: no create/edit/finalize controls render and the XLSX export is
never clicked. Functional logic is proven by the isolated integration suite;
this map is release-surface verification. Status: future for MCP (nothing
demonstrated yet); no scripted S2 coverage exists for this feature.

## Sub-features

- `pend-panel-entry` shows the sidebar item `Pendências` after `Censo` and
  marks it active on `/pendencias/`; the page heading is `Pendências dos
  internados atuais` and the census photo line renders only when a photo
  exists.
- `pend-indicators` renders three cards — `Pacientes com pendências ativas` (shows `0` when there are none), `Idade média das ativas` and `Idade máxima das ativas` (both `—`) — plus the notice `Nenhuma pendência ativa no momento.` when the cut holds no active items.
- `pend-views` toggles `Por paciente` (default) and `Por pendência` with
  the same filter state; `Abrir episódio` appears per group in the patient
  view and per row in the item view.
- `pend-filters` applies the GET form (`Aplicar filtros`): `Status`
  (`Ativas` default, `Resolvidas`, `Encerradas sem resolução`, `Todas`),
  `Unidade atual`, `Leito`, `Especialidade`, `Tipo`, `Criador`, `Último
  atualizador`, `Ordenação` and the `Tempo mín./máx. (dias)` bounds. A
  filtered-empty result legitimately shows `Nenhuma pendência corresponde
  aos filtros.`; inverted bounds show the `role="alert"` notice with that
  same empty listing.
- `pend-pagination` reads the `Paginação` nav (`Anterior`/`Próxima`) when
  the listing spans pages; pagination never splits one patient's group.
- `pend-history-fragment` expands `Histórico` on an item and loads the
  version fragment by HTMX (header `Versão`) without leaving the panel.
- `pend-contextual-read` opens an episode via `Abrir episódio` and, as a
  reader, sees the episode cards with the `Histórico` link only: no
  `Nova pendência` heading, no `Cadastrar pendência` button, no
  `Editar`/`Finalizar` links.
- `pend-contextual-history` follows the contextual `Histórico` link to the
  full-page version history of that episode's item.
- `pend-no-export-no-write` never clicks `Exportar XLSX` and never opens
  any edit/finalize surface, even as GET.

## How to get to it (user POV)

- Log in and choose `Pendências` in the sidebar (`Menu principal`), or open
  `<origin>/pendencias/` directly (canonical dev `origin` from `doctor`).
- Read the heading `Pendências dos internados atuais`, the census photo
  line (when present) and the three indicator cards.
- Switch between `Por paciente` and `Por pendência`; a group keeps one card
  per patient with all their matching items.
- Set filters — e.g. `Status` = `Resolvidas`, or `Tempo mín. (dias)` = `10`
  — and choose `Aplicar filtros`; the controls keep the selection and the
  URL carries the query string.
- Choose `Histórico` on an item: the collapse opens and the version table
  loads in place.
- Choose `Abrir episódio` to read the patient's episode list; from there,
  `Histórico` opens the full-page history of an item.

## Driving it with Chrome DevTools MCP

Preconditions:

- Authenticated as `verify_user` (reader: no `Desospitalização` group);
  snapshot of `/painel/` on hand; workers stopped; dataset confirmed
  fictitious.
- Empty-outcome contract: an honestly empty panel (indicators `0`/`—`, or
  every listing saying `Nenhuma pendência corresponde aos filtros.`) lets
  `pend-panel-entry`, `pend-indicators`, `pend-views`, `pend-filters` and
  `pend-no-export-no-write` be recorded — but `pend-history-fragment`,
  `pend-contextual-read` and `pend-contextual-history` are BLOCKED without
  at least one item in the current cut, never PASS, and never satisfied by
  fabricating data or starting workers. For positive listings beyond
  existence, an operator-supplied descriptor is required, as in census.

- **Sidebar entry.** From the `/painel/` snapshot, confirm the
  `Pendências` link after `Censo`; click it and `wait_for` text
  `["Pendências dos internados atuais"]`, confirming the URL ends in
  `/pendencias/` and the sidebar marks the item active. End state: panel
  reached through the real menu.
- **Indicators.** Read the three card labels and their values from the
  snapshot; `0`/`—` plus `Nenhuma pendência ativa no momento.` is a valid
  recorded state. End state: values in notes with the run identity
  visible.
- **Views.** Click `Por pendência` and confirm one row per item with the
  same filters; click `Por paciente` to return. End state: both modes
  captured from the same session.
- **Filters (GET only).** On the form, set the `Status` select to
  `Resolvidas` (combobox named `Status`, option by its accessible name),
  choose `Aplicar filtros`, `wait_for` `["Pendências dos internados
  atuais"]` and confirm the URL carries `status=resolved` and the select
  keeps the selection. A resulting `Nenhuma pendência corresponde aos
  filtros.` listing is a valid outcome. As a negative variant, fill
  `Tempo mín. (dias)` with `10` and `Tempo máx. (dias)` with `1`, submit,
  and confirm the `role="alert"` notice plus the empty listing. End state:
  filtered listing (or recorded empty state); `list_network_requests`
  shows only GETs.
- **Pagination.** When the `Paginação` nav is present, follow `Próxima`
  and confirm page 2 renders without duplicating or splitting a patient
  group across pages. End state: navigation recorded in notes.
- **History fragment.** Click the `Histórico` button of one item; confirm
  the collapse region opens and `wait_for` text `["Versão"]` loads inside
  it without navigation (an HTMX GET to `/pendencias/<id>/history/`).
  End state: expanded history captured, network notes show the fragment
  request.
- **Contextual read.** Follow `Abrir episódio`; as a reader, confirm the
  episode cards render and the snapshot (roles and accessible names, not
  ids) contains no `Nova pendência` heading, no `Cadastrar pendência`
  button, and no `Editar`/`Finalizar` links — `Histórico` remains. End
  state: reader page captured with identity visible.
- **Contextual history.** Follow the contextual `Histórico` link; the
  full-page version history of that item opens under
  `/admissions/<admission_id>/pending-items/<item_id>/history/`. End
  state: history page captured.
- **No export, no write.** The `Exportar XLSX` button is visible but never
  clicked; never open `/pendencias/export.xlsx` nor any `/edit/` or
  `/finalize/` URL. `list_network_requests` must show no export navigation
  and no POST outside `/login/`/`/logout/`. End state: discipline recorded
  in notes.
- **Proof.** Distinct artifacts under
  `/tmp/sirhosp-verification-mcp/<run-id>/`, each tagged with the feature
  id and entry point: `shot-pendencias-patients.png`,
  `shot-pendencias-items.png`, `shot-pendencias-filters.png`,
  `shot-pendencias-history.png`, `shot-pendencias-contextual.png`,
  `shot-pendencias-contextual-history.png` (plus the panel entry shot on
  first arrival).

## Gotchas

- Assert reader safety by accessible names (`Cadastrar pendência`,
  `Editar`, `Finalizar`), never by `data-testid`: the a11y snapshot
  exposes roles and names, not test ids, so a testid-absence check passes
  vacuously even when write controls leak.
- Item ids are dynamic: pick `Histórico` by its accessible button name
  inside a row, not a hard-coded id suffix.
- Empty outcomes follow the contract above: panel-level sub-features
  record; item-dependent sub-features are BLOCKED, never PASS, never
  fed by fabricated data or restarted workers.
- Ambiguous cases (conflicting beds, ambiguous identity, two open
  admissions) are deliberately absent from the aggregate by the shared
  conservative cut: their exclusion is correct behavior, not a missing
  row.
- Reader assertions are negative by nature: absence of write controls for
  `verify_user` is the proof; their presence is a finding.
- Filters are GET-only; any POST to a pending-items URL in the network
  listing is a FAIL, not a shortcut.
- Mobile-viewport journeys for this feature are held by the isolated
  integration suite; this map drives desktop reads only.
- Markup lives in `apps/pending_items/templates/pending_items/`
  (`aggregate.html`, `admission_items.html`,
  `_aggregate_history_table.html`) and the sidebar entry in
  `templates/includes/sidebar.html`; handle changes there must update this
  file and its proof.
