"""Synthetic census extraction artifacts shared by ECD-S2 tests.

These helpers build the local producer/consumer handoff only from synthetic
values. They intentionally duplicate the public summary schema so the tests
detect an incompatible wire contract instead of importing it from production.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

SUMMARY_FILENAME = "censo-extraction-summary.json"

SUMMARY_FIELDS = (
    "summary_version",
    "sectors_discovered",
    "sectors_selected",
    "sectors_processed",
    "sectors_empty",
    "sectors_failed",
    "rows_read",
    "rows_omitted",
    "rows_emitted",
    "pages_processed",
    "scope_limited",
    "scope_complete",
)


def build_summary(
    *,
    discovered: int,
    selected: int | None = None,
    processed: int | None = None,
    empty: int = 0,
    failed: int = 0,
    rows_emitted: int,
    rows_omitted: int = 0,
    pages_processed: int = 0,
    scope_limited: bool | None = None,
    scope_complete: bool | None = None,
) -> dict:
    """Return a schema-v1 summary for synthetic handoff tests."""
    selected = discovered if selected is None else selected
    processed = selected if processed is None else processed
    scope_limited = selected < discovered if scope_limited is None else scope_limited
    scope_complete = (
        processed == selected and failed == 0
        if scope_complete is None
        else scope_complete
    )
    return {
        "summary_version": 1,
        "sectors_discovered": discovered,
        "sectors_selected": selected,
        "sectors_processed": processed,
        "sectors_empty": empty,
        "sectors_failed": failed,
        "rows_read": rows_emitted + rows_omitted,
        "rows_omitted": rows_omitted,
        "rows_emitted": rows_emitted,
        "pages_processed": pages_processed,
        "scope_limited": scope_limited,
        "scope_complete": scope_complete,
    }


def write_summary(
    directory: Path,
    summary: dict,
    *,
    name: str = SUMMARY_FILENAME,
) -> Path:
    path = Path(directory) / name
    path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def temp_output_dir() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory()
