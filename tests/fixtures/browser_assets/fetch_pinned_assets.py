#!/usr/bin/env python
"""Fetch the pinned browser-test assets referenced by the shell.

Downloads byte-for-byte the exact CDN URLs used by ``templates/base.html``
(Bootstrap 5.3.3, Bootstrap Icons 1.11.3, HTMX 2.0.4) plus the icon font
binaries referenced by the pinned icons CSS and a copy of the project
theme CSS, into this directory. Text payloads are verified by version
marker; font binaries carry no version marker, so they are verified by
exact expected size and SHA-256 recorded from the verified first fetch.
Licenses travel inline in the distributed banners.

Run once with network access, then commit the resulting files::

    python tests/fixtures/browser_assets/fetch_pinned_assets.py

Regenerate ``SOURCES.md`` from the already-pinned files without network::

    python tests/fixtures/browser_assets/fetch_pinned_assets.py --local

The browser tests never fetch: when a fixture is absent they fail closed
with infrastructure instructions instead of touching the network.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ASSETS_DIR = Path(__file__).resolve().parent
REPO_ROOT = ASSETS_DIR.parents[2]

PINNED: dict[str, tuple[str, bytes | None]] = {
    # filename: (shell URL, version marker that must occur in the payload;
    # None for binaries verified by EXPECTED_BINARIES instead)
    "bootstrap-5.3.3.min.css": (
        "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css",
        b"5.3.3",
    ),
    "bootstrap-icons-1.11.3.css": (
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.css",
        b"1.11.3",
    ),
    "bootstrap-5.3.3.bundle.min.js": (
        "https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js",
        b"5.3.3",
    ),
    "htmx-2.0.4.js": (
        "https://unpkg.com/htmx.org@2.0.4",
        b"2.0.4",
    ),
    "bootstrap-icons.woff2": (
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff2",
        None,
    ),
    "bootstrap-icons.woff": (
        "https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/fonts/bootstrap-icons.woff",
        None,
    ),
}

# filename: (expected bytes, expected SHA-256). Font binaries contain no
# version marker, so a fresh download must match these exactly.
EXPECTED_BINARIES: dict[str, tuple[int, str]] = {
    "bootstrap-icons.woff2": (
        130396,
        "476adf42b40325098fcfa8b36ab3e769186bb4f6ce6a249753e2e1a9c22bf99e",
    ),
    "bootstrap-icons.woff": (
        176032,
        "bb1de989b83970f6f4e54de1cd974c5cba55b73582da5e1b225a6d0edf029483",
    ),
}

THEME_SOURCE = REPO_ROOT / "static" / "css" / "sirhosp.css"
THEME_FIXTURE = "sirhosp-theme.css"


def _download(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": "sirhosp-tests"})
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        return response.read()


def _verify(filename: str, url: str, payload: bytes) -> None:
    """Refuse payloads that do not match the pinned identity."""
    marker = PINNED[filename][1]
    if marker is not None:
        if marker not in payload:
            raise RuntimeError(
                f"{url}: version marker {marker!r} not found; refusing to pin."
            )
        return
    expected = EXPECTED_BINARIES.get(filename)
    if expected is None:
        raise RuntimeError(f"{filename}: no marker or binary pin; refusing to pin.")
    expected_size, expected_digest = expected
    digest = hashlib.sha256(payload).hexdigest()
    if len(payload) != expected_size or digest != expected_digest:
        raise RuntimeError(
            f"{url}: binary mismatch (got {len(payload)} bytes sha256:{digest}); "
            "refusing to pin."
        )


def _row(filename: str, source: str, payload: bytes) -> str:
    digest = hashlib.sha256(payload).hexdigest()
    return f"| `{filename}` | `{source}` | {len(payload)} | `{digest}` |"


def _write_sources(stamp_label: str, rows: list[str]) -> None:
    lines = [
        "# Browser asset fixtures (D9)",
        "",
        "Pinned copies of the exact CDN payloads referenced by",
        "`templates/base.html` (plus the icon font binaries referenced by the",
        "pinned icons CSS), plus the project theme CSS. Served by",
        "`page.route` interception in `tests/integration/test_pending_items_browser.py`.",
        "Licenses travel inline in each distributed file banner.",
        "",
        f"{stamp_label}: {datetime.now(timezone.utc).isoformat()}",
        "",
        "| Fixture | Source | Bytes | SHA-256 |",
        "| --- | --- | --- | --- |",
        *rows,
        "",
    ]
    (ASSETS_DIR / "SOURCES.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str]) -> int:
    local_only = len(argv) > 1 and argv[1] == "--local"
    if len(argv) > 1 and not local_only:
        print(f"usage: {Path(argv[0]).name} [--local]", file=sys.stderr)
        return 2
    rows: list[str] = []
    for filename, (url, _marker) in PINNED.items():
        if local_only:
            payload = (ASSETS_DIR / filename).read_bytes()
        else:
            payload = _download(url)
            (ASSETS_DIR / filename).write_bytes(payload)
        _verify(filename, url, payload)
        rows.append(_row(filename, url, payload))
    theme_bytes = THEME_SOURCE.read_bytes()
    if not local_only:
        (ASSETS_DIR / THEME_FIXTURE).write_bytes(theme_bytes)
    rows.append(
        _row(THEME_FIXTURE, "static/css/sirhosp.css (local copy)", theme_bytes)
    )
    _write_sources(
        "Regenerated at (local)" if local_only else "Fetched at", rows
    )
    print(f"pinned {len(PINNED) + 1} fixtures in {ASSETS_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
