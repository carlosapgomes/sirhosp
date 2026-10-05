# Navigation

The sidebar shell carries the user across Dashboard, Censo, Leitos, Fluxo,
Setores, Pacientes, Monitor de Risco, and Logs de Resumos, marks the active
menu, and exposes `Perfil` plus the run identity. Proven: playwright (shell
links, active menu, per-role `Estatísticas`). Demonstrated: mcp (shell read,
profile page read).

## Sub-features

- `nav-shell-links` renders every sidebar link with real hrefs.
- `nav-active-menu` marks exactly the current section as active.
- `nav-profile` opens `/perfil/` from the sidebar `Perfil` link.
- `nav-role-user` hides the `Estatísticas` item from the common role.
- `nav-role-admin` shows exactly one `Estatísticas` item to the admin role.
- `nav-mobile-menu` opens and closes the off-canvas menu by click.

## How to get to it (user POV)

- Log in and land on `/painel/` (Dashboard).
- Read the sidebar (`#sidebar`, `Menu principal`): Dashboard, Censo
  (`/censo/`), Leitos, Fluxo Hospitalar, Setores, Pacientes, Monitor de
  Risco, Logs de Resumos, and `Estatísticas` for the admin role only.
- Choose `Censo` to reach `/censo/`; the active mark follows.
- Choose `Perfil` in the sidebar footer to reach `/perfil/`.
- On a narrow viewport, choose `Menu` (`#sidebarToggle`, `Abrir menu`) to
  open the off-canvas sidebar; choose the overlay (`#sidebarOverlay`) or
  press Escape to close.

## Driving it with Chrome DevTools MCP

Preconditions:

- Authenticated as the run role; snapshot of `/painel/` on hand.

- **Shell links.** From the `/painel/` snapshot, confirm `navigation Menu
  principal` with links `Dashboard` (`/painel/`), `Censo` (`/censo/`), and
  `Perfil` (`/perfil/`) in the footer. End state: every expected href read
  from the live page, matching `templates/includes/sidebar.html`.
- **Role visibility.** As `verify_user`, confirm no `Estatísticas` link. As
  `verify_admin`, confirm exactly one, without visiting any export. End
  state: per-role presence recorded in notes.
- **Censo entry.** Navigate to `/censo/`. Run `wait_for` with text
  `["Censo", "Filtrar"]` and confirm `RootWebArea` url ends in `/censo/`.
  End state: `Censo Hospitalar` heading with the sidebar intact.
- **Profile entry.** Navigate to `/perfil/`. Run `wait_for` with text
  `["Perfil", "<username>"]` and screenshot to the evidence dir. End state:
  profile page showing the run identity.
- **Mobile menu (future for MCP).** Resize to 390x844, click
  `#sidebarToggle`, confirm `#sidebar` gains `open` and `#sidebarOverlay`
  gains `show`; click the overlay and confirm both classes drop. The mobile
  logout clicks `#sidebarToggle` first, because `Sair` is only reachable
  once the off-canvas menu is open. End state: open/close states screenshotted.
- **Proof.** Snapshots plus `shot-painel.png`, `shot-censo.png`,
  `shot-perfil.png` under `/tmp/sirhosp-verification-mcp/<run-id>/`.

## Gotchas

- The a11y snapshot exposes roles and names, not CSS ids: assert
  `Menu principal`, `Perfil`, `Sair`, never a literal `#sidebar` string.
- `Estatísticas` renders only with `perms.statistics_reports.view_daily_statistics`;
  asserting it for the common role is a bug in the check, not the product.
- Desktop and mobile need separate contexts; viewport state must not leak
  between roles.
- Sidebar markup lives in `templates/includes/sidebar.html` and the toggle
  script in `templates/base_sidebar.html`; a template change moves the
  handles, so re-prove after any sidebar edit.
