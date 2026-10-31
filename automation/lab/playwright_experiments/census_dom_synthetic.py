"""Local synthetic census UI for DOM extraction verification.

This module renders a self-contained PrimeFaces-like census page in a local
browser. It exists only for lab verification and tests: the operational
collector reads it through its real DOM code, but nothing here is imported by
production, and no hospital host, credential or patient data is involved.

The markup reproduces the structures already evidenced in the source UI:
``resultList_data`` table body, ``ui-column-title`` headers (including the
hidden first ``Alta``/``Origem`` export variants), the native page-size select,
the paginator next control, and PrimeFaces Tooltip widgets whose ``cfg.target``
points at the date cell descendant.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

DEFAULT_PAGE_OPTIONS = (20, 50, 100)

# Header order evidenced in the source UI. The first Alta/Origem occurrence is
# the export-contract variant and is hidden; the visible duplicate is
# presentation only.
DEFAULT_COLUMNS = (
    ("acoes", "Ações", "extra", ""),
    ("qrt_leito", "Qrt/Leito", "value", "leito"),
    ("prontuario", "Prontuário", "value", "prontuario"),
    ("nome", "Nome/Situação", "value", "nome"),
    ("dtnasc", "Dt. Nasc.", "extra", ""),
    ("idade", "Idade", "value", "idade"),
    ("dt_int", "Dt Int", "date", "int"),
    ("esp", "Esp", "value", "esp"),
    ("medico", "Médico", "extra", "medico"),
    ("dt_mvt", "Dt Mvt", "date", "mvt"),
    ("alta_export", "Alta", "value", "alta"),
    ("alta_view", "Alta", "value", "alta_view"),
    ("origem_export", "Origem", "value", "origem"),
    ("origem_view", "Origem", "value", "origem_view"),
    ("tempo", "Tempo", "value", "tempo"),
    ("convenio", "Convênio", "value", "convenio"),
    ("transferencia", "Transferência", "extra", ""),
    ("condicoes", "Condições", "extra", ""),
    ("destinos", "Destinos", "extra", ""),
)

REORDERED_COLUMNS = (
    ("qrt_leito", "Qrt/Leito", "value", "leito"),
    ("dt_int", "Dt Int", "date", "int"),
    ("prontuario", "Prontuário", "value", "prontuario"),
    ("nome", "Nome/Situação", "value", "nome"),
    ("esp", "Esp", "value", "esp"),
    ("dt_mvt", "Dt Mvt", "date", "mvt"),
    ("alta_export", "Alta", "value", "alta"),
    ("alta_view", "Alta", "value", "alta_view"),
    ("origem_export", "Origem", "value", "origem"),
    ("origem_view", "Origem", "value", "origem_view"),
    ("tempo", "Tempo", "value", "tempo"),
    ("convenio", "Convênio", "value", "convenio"),
    ("idade", "Idade", "value", "idade"),
    ("acoes", "Ações", "extra", ""),
    ("dtnasc", "Dt. Nasc.", "extra", ""),
    ("medico", "Médico", "extra", ""),
    ("transferencia", "Transferência", "extra", ""),
    ("condicoes", "Condições", "extra", ""),
    ("destinos", "Destinos", "extra", ""),
)

HIDDEN_COLUMN_KEYS = frozenset({"alta_export", "origem_export"})


def make_row(
    leito: str,
    prontuario: str = "",
    nome: str = "",
    *,
    esp: str = "CLÍNICA MÉDICA",
    idade: str = "40",
    tempo: int | str = 3,
    convenio: str = "SUS",
    dt_int: str = "01/02",
    int_tip: str | None = "01/02/2026 08:15",
    dt_mvt: str = "02/02",
    mvt_tip: str | None = "02/02/2026 10:30",
    alta: str = "",
    alta_view: str = "",
    origem: str = "",
    origem_view: str = "",
    int_extra: list[str] | None = None,
    mvt_extra: list[str] | None = None,
    int_attr: str | None = None,
    mvt_attr: str | None = None,
) -> dict[str, Any]:
    """Build one synthetic source row (all values fictional)."""
    return {
        "leito": leito,
        "prontuario": prontuario,
        "nome": nome,
        "esp": esp,
        "idade": idade,
        "tempo": tempo,
        "convenio": convenio,
        "dt_int": dt_int,
        "int_tip": int_tip,
        "dt_mvt": dt_mvt,
        "mvt_tip": mvt_tip,
        "alta": alta,
        "alta_view": alta_view,
        "origem": origem,
        "origem_view": origem_view,
        "int_extra": list(int_extra or []),
        "mvt_extra": list(mvt_extra or []),
        "int_attr": int_attr,
        "mvt_attr": mvt_attr,
        "medico": "",
    }


def make_sector(
    code: str,
    description: str,
    rows: list[dict[str, Any]],
    *,
    empty: bool = False,
    page_options: tuple[int, ...] = DEFAULT_PAGE_OPTIONS,
    default_page_size: int = 20,
    page_delay_ms: int = 30,
    tooltip_delay_ms: int = 120,
    next_mode: str = "normal",
    total_mode: str = "native",
    total_override: int | None = None,
    header_variant: str = "default",
    click_selects: str | None = None,
    global_tip: str | None = None,
) -> dict[str, Any]:
    """Build one synthetic sector definition.

    ``next_mode``: ``normal``, ``repeat`` (next never advances), ``missing``
    (next control absent before the last page).
    ``total_mode``: ``native`` (rowCount reported), ``absent`` (no total) or
    ``override`` (untrustworthy rowCount from ``total_override``).
    """
    return {
        "code": code,
        "description": description,
        "label": f"{code} - {description}",
        "rows": rows,
        "empty": empty,
        "page_options": list(page_options),
        "default_page_size": default_page_size,
        "page_delay_ms": page_delay_ms,
        "tooltip_delay_ms": tooltip_delay_ms,
        "next_mode": next_mode,
        "total_mode": total_mode,
        "total_override": total_override,
        "header_variant": header_variant,
        "click_selects": click_selects,
        "global_tip": global_tip,
    }


def occupied_rows(count: int, *, code: str, offset: int = 0) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for index in range(1, count + 1):
        number = offset + index
        rows.append(
            make_row(
                f"L{code}-{number:03d}A",
                f"SYN{code}{number:04d}",
                f"PACIENTE SINTÉTICO {code} {number}",
                idade="2m12d" if number % 5 == 0 else str(20 + (number % 60)),
                dt_int="01/02",
                int_tip="01/02/2026 08:15",
                dt_mvt="02/02",
                mvt_tip="02/02/2026 10:30",
            )
        )
    return rows


def generic_sector(index: int) -> dict[str, Any]:
    """One small sector with an occupied bed and a vacancy label."""
    code = f"{10 + index // 10} {index % 10 + 1}"
    description = f"ALA SINTÉTICA {index:02d}"
    rows = [
        make_row(
            f"LEITO{index:02d}A",
            f"SYN-G{index:03d}",
            f"PACIENTE SINTÉTICO G{index:03d}",
            dt_int="05/02",
            int_tip="05/02/2026 07:40",
            dt_mvt="06/02",
            mvt_tip="06/02/2026 09:05",
        ),
        make_row(
            f"LEITO{index:02d}B",
            "",
            "DESOCUPADO",
            esp="",
            idade="",
            tempo="",
            convenio="",
            dt_int="",
            int_tip=None,
            dt_mvt="",
            mvt_tip=None,
        ),
    ]
    return make_sector(code, description, rows)


def build_full_catalog() -> dict[str, Any]:
    """Return the full catalog used to cross the operational 40-sector gate.

    41 non-empty sectors plus one explicitly empty sector: 39 generic sectors,
    one 45-row accented sector, one 101-row shared-code sector that spans two
    native pages, and one second sector sharing the same source code.
    """
    sectors = [generic_sector(index) for index in range(1, 40)]

    pediatric = occupied_rows(44, code="PED")
    pediatric.append(
        make_row(
            "LEITO-PED-RES",
            "",
            "RESERVA",
            esp="",
            idade="",
            tempo="",
            convenio="",
            dt_int="",
            int_tip=None,
            dt_mvt="10/02",
            mvt_tip="10/02/2026 11:20",
        )
    )
    assert len(pediatric) == 45
    sectors.append(
        make_sector(
            "4 8",
            "4C - CLINICA MÉDICA PEDIÁTRICA - HGRS",
            pediatric,
            header_variant="reordered",
        )
    )

    long_rows = occupied_rows(97, code="NORTE")
    # Conflicting physical position: two distinct source rows share bed/record.
    long_rows.append(dict(long_rows[0]))
    long_rows.append(
        make_row(
            "LEITO-NORTE-RES",
            "",
            "RESERVA",
            esp="",
            idade="",
            tempo="",
            convenio="",
            dt_int="",
            int_tip=None,
            dt_mvt="03/02",
            mvt_tip="03/02/2026 12:00",
        )
    )
    # Both identities empty: omitted by the established parser rule, counted.
    long_rows.insert(
        50,
        make_row(
            "LEITO-NORTE-OMIT",
            "",
            "",
            esp="",
            idade="",
            tempo="",
            convenio="",
            dt_int="",
            int_tip=None,
            dt_mvt="",
            mvt_tip=None,
        ),
    )
    # Duplicate of an earlier row across the page boundary: never deduplicated.
    long_rows.append(dict(long_rows[1]))
    assert len(long_rows) == 101
    sectors.append(
        make_sector("5 1", "ALA NORTE", long_rows)
    )
    sectors.append(
        make_sector(
            "5 1",
            "ALA SUL",
            [
                make_row(
                    "LEITO-SUL-A",
                    "SYN-SUL-1",
                    "PACIENTE SINTÉTICO SUL 1",
                    dt_int="04/02",
                    int_tip="04/02/2026 13:10",
                    dt_mvt="04/02",
                    mvt_tip="04/02/2026 18:45",
                ),
                make_row(
                    "LEITO-SUL-B",
                    "SYN-SUL-2",
                    "PACIENTE SINTÉTICO SUL 2",
                    dt_int="04/02",
                    int_tip="04/02/2026 14:10",
                    dt_mvt="05/02",
                    mvt_tip="05/02/2026 03:00",
                ),
            ],
        )
    )
    sectors.append(
        make_sector("9 9", "ALA SEM PACIENTES", [], empty=True)
    )
    return {"sectors": sectors, "columns": "default"}


def build_failing_catalog(failing_sectors: int = 40) -> dict[str, Any]:
    """Catalog where the sector after ``failing_sectors`` successes is broken.

    The failure is structural and fast: the broken sector does not expose a
    native page-size option of at least 100.
    """
    sectors = [generic_sector(index) for index in range(1, failing_sectors + 2)]
    broken = sectors[-1]
    broken["page_options"] = [10, 20]
    broken["default_page_size"] = 20
    return {"sectors": sectors, "columns": "default"}


def build_scenario_catalog(
    sector: dict[str, Any],
) -> dict[str, Any]:
    return {"sectors": [sector], "columns": "default"}


_HTML_TEMPLATE = r"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<title>Censo sintético local</title>
<style>
  body { font-family: sans-serif; margin: 12px; }
  table { border-collapse: collapse; }
  th, td { border: 1px solid #999; padding: 2px 6px; white-space: nowrap; }
  .ui-tooltip { position: absolute; }
  .hidden-column { display: none; }
  .ui-state-disabled { opacity: .4; pointer-events: none; }
  #unidadeFuncional\:unidadeFuncional\:suggestion_panel {
    border: 1px solid #444; max-height: 240px; overflow-y: auto;
    position: absolute; background: white; z-index: 5;
  }
</style>
</head>
<body>
<div id="unidadeFuncional:unidadeFuncional">
  <button id="unidadeFuncional:unidadeFuncional:suggestion_button">Setores</button>
  <input id="unidadeFuncional:unidadeFuncional:suggestion_input" autocomplete="off">
  <button id="unidadeFuncional:unidadeFuncional:sgClear">Limpar</button>
  <span id="unidadeFuncional:unidadeFuncional:sgDescricaoLabel"></span>
  <div id="unidadeFuncional:unidadeFuncional:suggestion_panel" style="display:none"></div>
</div>
<p><button id="bt_pesquisar:button">Pesquisar</button></p>
<div id="form_loading" style="display:none">Carregando</div>
<div class="ui-datatable" id="form:resultList">
  <table>
    <thead><tr id="census-head-row"></tr></thead>
    <tbody id="form:resultList_data"></tbody>
  </table>
  <div class="ui-paginator ui-widget-header" id="census-paginator"></div>
</div>
<script>
const CATALOG = __CATALOG__;
const state = { selected: null, pageSize: 20, page: 0, generation: 0 };
const input = document.getElementById('unidadeFuncional:unidadeFuncional:suggestion_input');
const clearButton = document.getElementById('unidadeFuncional:unidadeFuncional:sgClear');
const sectorButton = document.getElementById('unidadeFuncional:unidadeFuncional:suggestion_button');
const descriptionLabel = document.getElementById(
  'unidadeFuncional:unidadeFuncional:sgDescricaoLabel'
);
const panel = document.getElementById('unidadeFuncional:unidadeFuncional:suggestion_panel');
const searchButton = document.getElementById('bt_pesquisar:button');
const tbody = document.getElementById('form:resultList_data');
const headRow = document.getElementById('census-head-row');
const paginator = document.getElementById('census-paginator');

window.PrimeFaces = {
  ajax: { Queue: { isEmpty: () => true, requests: [] } },
  widget: { Tooltip: function Tooltip() {} },
  widgets: {},
};

function compact(value) {
  return (value || '').normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]/g, '');
}

function currentSector() {
  return state.selected === null ? null : CATALOG.sectors[state.selected];
}

function columnsFor(sector) {
  return sector && sector.header_variant === 'reordered'
    ? __REORDERED_COLUMNS__ : __DEFAULT_COLUMNS__;
}

function renderHead(sector) {
  headRow.innerHTML = '';
  for (const [key, title] of columnsFor(sector)) {
    const th = document.createElement('th');
    if (__HIDDEN_KEYS__.has(key)) th.className = 'hidden-column';
    const span = document.createElement('span');
    span.className = 'ui-column-title';
    span.textContent = title;
    th.appendChild(span);
    headRow.appendChild(th);
  }
}

function pageRows(sector) {
  const start = state.page * state.pageSize;
  return sector.rows.slice(start, start + state.pageSize);
}

function cellValue(row, kind) {
  if (kind === 'leito') return row.leito;
  if (kind === 'prontuario') return row.prontuario;
  if (kind === 'nome') return row.nome;
  if (kind === 'esp') return row.esp;
  if (kind === 'idade') return row.idade;
  if (kind === 'tempo') return row.tempo;
  if (kind === 'convenio') return row.convenio;
  if (kind === 'alta') return row.alta;
  if (kind === 'alta_view') return row.alta_view;
  if (kind === 'origem') return row.origem;
  if (kind === 'origem_view') return row.origem_view;
  if (kind === 'int') return row.dt_int;
  if (kind === 'mvt') return row.dt_mvt;
  return '';
}

function clearTips() {
  document.querySelectorAll('.ui-tooltip').forEach(node => node.remove());
  for (const key of Object.keys(PrimeFaces.widgets)) {
    if (key.startsWith('tt-') || key === 'results') delete PrimeFaces.widgets[key];
  }
}

function render() {
  const sector = currentSector();
  const generation = state.generation;
  clearTips();
  headRow.innerHTML = '';
  tbody.innerHTML = '';
  paginator.innerHTML = '';
  if (!sector) return;
  if (!sector.page_options.includes(state.pageSize)) {
    state.pageSize = sector.page_options[0];
  }
  renderHead(sector);

  if (sector.empty) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = columnsFor(sector).length;
    td.textContent = 'Nenhum registro encontrado';
    tr.appendChild(td);
    tbody.appendChild(tr);
    const span = document.createElement('span');
    span.className = 'ui-paginator-page ui-state-active';
    span.textContent = '1';
    paginator.appendChild(span);
    const next = document.createElement('a');
    next.className = 'ui-paginator-next ui-state-disabled';
    next.setAttribute('aria-disabled', 'true');
    next.textContent = 'Próxima';
    paginator.appendChild(next);
    return;
  }

  const columns = columnsFor(sector);
  const rows = pageRows(sector);
  rows.forEach((row, rowIndex) => {
    const tr = document.createElement('tr');
    for (const [key, , kind, valueKey] of columns) {
      const td = document.createElement('td');
      if (__HIDDEN_KEYS__.has(key)) td.className = 'hidden-column';
      if (kind === 'date') {
        const span = document.createElement('span');
        span.id = 'form:resultList:' + rowIndex + ':' + (valueKey === 'int' ? 'dtint' : 'dtmvt');
        span.textContent = cellValue(row, valueKey);
        td.appendChild(span);
      } else if (kind === 'value') {
        td.textContent = cellValue(row, valueKey);
      }
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  });

  const totalPages = Math.max(1, Math.ceil(sector.rows.length / state.pageSize));
  const select = document.createElement('select');
  select.className = 'ui-paginator-rpp-options';
  for (const option of sector.page_options) {
    const item = document.createElement('option');
    item.value = String(option);
    item.textContent = String(option);
    if (option === state.pageSize) item.selected = true;
    select.appendChild(item);
  }
  select.addEventListener('change', event => {
    const nextGeneration = ++state.generation;
    state.pageSize = Number(event.target.value);
    state.page = 0;
    setTimeout(() => {
      if (nextGeneration === state.generation) render();
    }, 30);
  });
  paginator.appendChild(select);

  for (let page = 0; page < totalPages; page += 1) {
    const span = document.createElement('span');
    span.className = 'ui-paginator-page' + (page === state.page ? ' ui-state-active' : '');
    span.textContent = String(page + 1);
    paginator.appendChild(span);
  }

  const lastPage = state.page >= totalPages - 1;
  if (!lastPage || sector.next_mode !== 'missing') {
    const next = document.createElement('a');
    next.className = 'ui-paginator-next' + (lastPage ? ' ui-state-disabled' : '');
    if (lastPage) next.setAttribute('aria-disabled', 'true');
    next.textContent = 'Próxima';
    if (!lastPage) {
      next.addEventListener('click', event => {
        event.preventDefault();
        const nextGeneration = ++state.generation;
        if (state.page + 1 < totalPages && sector.next_mode !== 'repeat') {
          state.page += 1;
        }
        setTimeout(() => {
          if (nextGeneration === state.generation) render();
        }, sector.page_delay_ms);
      });
    }
    paginator.appendChild(next);
  }

  const totalMode = sector.total_mode || 'native';
  PrimeFaces.widgets.results = {
    tbody: [tbody],
    getPaginator: () => ({
      cfg: totalMode === 'absent'
        ? {}
        : { rowCount: totalMode === 'override'
            ? Number(sector.total_override)
            : sector.rows.length },
    }),
  };

  const generationForTips = state.generation;
  setTimeout(() => {
    if (generationForTips === state.generation) initTooltips(sector, generationForTips);
  }, sector.tooltip_delay_ms);

  if (sector.global_tip) {
    const tip = document.createElement('div');
    tip.className = 'ui-tooltip';
    tip.textContent = sector.global_tip;
    document.body.appendChild(tip);
  }
}

function addDateTip(span, value, generation, kind, rowIndex, slot) {
  if (!span || !value) return;
  const tip = document.createElement('div');
  tip.className = 'ui-tooltip synth-tooltip';
  tip.style.display = 'none';
  tip.id = 'tt-' + generation + '-' + kind + '-' + rowIndex + '-' + slot;
  tip.textContent = value;
  document.body.appendChild(tip);
  const widget = new PrimeFaces.widget.Tooltip();
  widget.cfg = { id: tip.id, target: '#' + span.id.replace(/:/g, '\\:') };
  widget.jq = [tip];
  widget.target = [span];
  PrimeFaces.widgets[tip.id] = widget;
}

function initTooltips(sector, generation) {
  if (generation !== state.generation) return;
  pageRows(sector).forEach((row, rowIndex) => {
    const intSpan = document.getElementById('form:resultList:' + rowIndex + ':dtint');
    const mvtSpan = document.getElementById('form:resultList:' + rowIndex + ':dtmvt');
    if (intSpan && row.int_attr) intSpan.setAttribute('title', row.int_attr);
    if (mvtSpan && row.mvt_attr) mvtSpan.setAttribute('title', row.mvt_attr);
    (row.int_extra || []).forEach((value, slot) => {
      addDateTip(intSpan, value, generation, 'int', rowIndex, slot + 1);
    });
    (row.mvt_extra || []).forEach((value, slot) => {
      addDateTip(mvtSpan, value, generation, 'mvt', rowIndex, slot + 1);
    });
    addDateTip(intSpan, row.int_tip, generation, 'int', rowIndex, 0);
    addDateTip(mvtSpan, row.mvt_tip, generation, 'mvt', rowIndex, 0);
  });
}

function showSuggestions(indices) {
  panel.innerHTML = '';
  if (!indices.length) {
    panel.style.display = 'none';
    return;
  }
  for (const index of indices) {
    const sector = CATALOG.sectors[index];
    const item = document.createElement('div');
    item.setAttribute('role', 'cell');
    item.className = 'ui-autocomplete-item';
    item.dataset.index = String(index);
    item.textContent = sector.label;
    item.addEventListener('click', () => chooseSector(index));
    panel.appendChild(item);
  }
  panel.style.display = 'block';
}

function chooseSector(index) {
  const sector = CATALOG.sectors[index];
  const targetIndex = sector.click_selects === null || sector.click_selects === undefined
    ? index
    : CATALOG.sectors.findIndex(candidate => candidate.label === sector.click_selects);
  const target = targetIndex >= 0 ? CATALOG.sectors[targetIndex] : sector;
  state.selected = targetIndex >= 0 ? targetIndex : index;
  input.value = target.code;
  descriptionLabel.textContent = target.description;
  panel.style.display = 'none';
}

function filterSuggestions() {
  const query = compact(input.value);
  if (!query) {
    panel.style.display = 'none';
    return;
  }
  const indices = [];
  CATALOG.sectors.forEach((sector, index) => {
    if (compact(sector.label).includes(query)) indices.push(index);
  });
  showSuggestions(indices);
}

input.addEventListener('input', filterSuggestions);
input.addEventListener('keydown', filterSuggestions);
input.addEventListener('keyup', filterSuggestions);
sectorButton.addEventListener('click', () => {
  showSuggestions(CATALOG.sectors.map((_sector, index) => index));
});
clearButton.addEventListener('click', () => {
  input.value = '';
  descriptionLabel.textContent = '';
  state.selected = null;
  panel.style.display = 'none';
});
searchButton.addEventListener('click', () => {
  const generation = ++state.generation;
  const sector = currentSector();
  state.page = 0;
  if (sector) state.pageSize = sector.default_page_size || 20;
  setTimeout(() => {
    if (generation === state.generation) render();
  }, sector ? sector.page_delay_ms : 10);
});

render();
</script>
</body>
</html>
"""


def render_html(catalog: dict[str, Any]) -> str:
    return (
        _HTML_TEMPLATE.replace(
            "__CATALOG__", json.dumps(catalog, ensure_ascii=False)
        )
        .replace(
            "__DEFAULT_COLUMNS__",
            json.dumps([list(column) for column in DEFAULT_COLUMNS]),
        )
        .replace(
            "__REORDERED_COLUMNS__",
            json.dumps([list(column) for column in REORDERED_COLUMNS]),
        )
        .replace(
            "__HIDDEN_KEYS__",
            "new Set(" + json.dumps(sorted(HIDDEN_COLUMN_KEYS)) + ")",
        )
    )


class SyntheticCensusServer:
    """Serve one synthetic catalog at ``http://127.0.0.1:<port>/``."""

    def __init__(self, catalog: dict[str, Any]) -> None:
        self.catalog = catalog
        body = render_html(catalog).encode("utf-8")

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if self.path not in ("/", "/index.html"):
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, _format: str, *_args: Any) -> None:
                return None

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )

    @property
    def url(self) -> str:
        address = self._server.server_address
        host = address[0]
        if isinstance(host, bytes):
            host = host.decode("ascii")
        return f"http://{host}:{int(address[1])}/"

    def __enter__(self) -> "SyntheticCensusServer":
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5)
