"""CFC-S2: synthetic lab harness for full-sync chronic failure hypotheses.

This module reproduces the two full-sync chronic-failure hypotheses against
the REAL evolution extraction and classification code, using fixtures that
are 100% synthetic and versioned in this repository:

- **H1 (timeout by volume/deadline)**: a synthetic long evolution report
  (parametrizable item count) driven through the real
  :class:`~apps.ingestion.extractors.persistent_evolution_pdf.EvolutionPdfFlow`
  with a configurable constrained deadline. The real shared-monotonic-deadline
  boundary raises a typed ``EvolutionPdfTimeoutError`` that the real
  classifier maps to ``timeout``; the experiment records the measured
  duration and parameters.
- **H2 (invalid_payload by content)**: synthetic content fixtures that
  violate known payload validations (invalid JSON, non-list root, missing
  container, text/html response, missing ``%PDF-`` signature, empty PDF
  object attribute) are run through the real validation paths and classified
  by :func:`~apps.ingestion.run_lifecycle.classify_failure_reason`; each
  experiment records which validation triggered the mapping.

Laboratory discipline (project policy): this harness lives under
``automation/lab/``, is never imported by ``apps/`` operational code, and
never touches production rows, credentials, patient identifiers, real HTML
or real PDFs. No network, subprocess or browser is used: the interactive
flow is driven with minimal duck-typed fake page/locator/request objects
(the same technique the operational unit tests use), so every experiment
runs headless-free and deterministically. The optional CLI writes a
consolidated synthetic ``verdicts.json`` artifact for on-demand inspection.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from apps.ingestion.extractors.errors import ExtractionError
from apps.ingestion.extractors.persistent_evolution_pdf import (
    _PDF_OBJECT_SELECTOR,
    EvolutionPdfFlow,
    assert_pdf_response_signature,
)
from apps.ingestion.extractors.persistent_extraction_adapter import (
    _EVOLUTION_DATA_CONTAINER_RE,
    _EVOLUTION_DATA_DIV_ID,
    _extract_json_from_container,
    _parse_evolutions_json,
)
from apps.ingestion.run_lifecycle import classify_failure_reason

# ---------------------------------------------------------------------------
# Synthetic sentinels and defaults
# ---------------------------------------------------------------------------

SYNTHETIC_SENTINEL = "SYNTH-LAB-CFC"
"""Marker that every synthetic fixture content MUST carry."""

H2_FILE_SENTINEL = "SYNTH-LAB-CFC-H2"
"""Sentinel of the versioned H2 content-fixture file."""

ARTIFACT_SENTINEL = "SYNTH-LAB-CFC-ARTIFACT"
"""Sentinel of the consolidated verdicts artifact."""

_FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"

_SYNTHETIC_PAGE_URL = "https://lab.example/synthetic-report"
_SYNTHETIC_PDF_URL = "https://lab.example/synth-report.pdf"
_SYNTHETIC_ADMISSION_KEY = "SYNTH-ADM-H1"

DEFAULT_H1_ITEM_COUNT = 120
DEFAULT_H1_DEADLINE_SECONDS = 1
DEFAULT_H1_LATENCY_PER_ITEM_MS = 10
DEFAULT_H1_CONTROL_ITEM_COUNT = 40
DEFAULT_H1_CONTROL_DEADLINE_SECONDS = 60
DEFAULT_H1_CONTROL_LATENCY_PER_ITEM_MS = 10

VerdictValue = Literal["confirmed", "refuted", "inconclusive"]


@dataclass(frozen=True)
class ExperimentVerdict:
    """Sanitized, synthetic verdict artifact for one lab experiment."""

    hypothesis: str
    fixture: str
    params: dict[str, Any]
    measured_duration_seconds: float | None
    reason: str | None
    verdict: VerdictValue
    notes: str


# ---------------------------------------------------------------------------
# Minimal duck-typed Playwright-like objects (lab-only, never in apps/)
# ---------------------------------------------------------------------------


class _FakeLocator:
    """Minimal duck-typed locator (count/fill/click/get_attribute)."""

    def __init__(self, *, count: int = 0, attribute: str | None = None) -> None:
        self._count = count
        self._attribute = attribute
        self.first: _FakeLocator = self

    def count(self) -> int:
        return self._count

    def fill(self, value: str, **kwargs: Any) -> None:
        del value, kwargs  # lab-only fake: fills are no-ops

    def click(self, **kwargs: Any) -> None:
        del kwargs  # lab-only fake: clicks are no-ops

    def get_attribute(self, name: str, **kwargs: Any) -> str | None:
        del name, kwargs
        return self._attribute


class _FakeResponse:
    """Minimal duck-typed API response used by the real download path."""

    def __init__(
        self,
        *,
        ok: bool = True,
        body: bytes = b"",
        headers: dict[str, str] | None = None,
    ) -> None:
        self.ok = ok
        self._body = body
        self.headers = headers or {}

    def body(self) -> bytes:
        return self._body


class _FakeRequest:
    """Duck-typed ``page.context.request`` with a volume-proportional delay.

    ``latency_ms`` models a slow legacy download whose cost grows with the
    number of report items (the H1 volume hypothesis). The fake IGNORES the
    bounded timeout passed by the real flow, so an overrun is caught by the
    real shared-deadline boundary check (``_remaining_ms``) - the documented
    D21 behavior of :mod:`persistent_evolution_pdf`.
    """

    def __init__(self, response: _FakeResponse, *, latency_ms: int = 0) -> None:
        self._response = response
        self._latency_ms = latency_ms
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append((url, kwargs))
        if self._latency_ms > 0:
            time.sleep(self._latency_ms / 1000.0)
        return self._response


class _FakeContext:
    def __init__(self, request: _FakeRequest) -> None:
        self.request = request


class _FakePage:
    """Minimal duck-typed page for the REAL :class:`EvolutionPdfFlow`.

    Only the selectors the real flow touches are configured: the legacy date
    inputs and the generate button are absent (count 0), and the PDF object
    locator carries the injected synthetic ``data`` attribute.
    """

    def __init__(
        self,
        *,
        pdf_object_attribute: str,
        request: _FakeRequest,
        url: str = _SYNTHETIC_PAGE_URL,
    ) -> None:
        self._pdf_object_attribute = pdf_object_attribute
        self.url = url
        self.context = _FakeContext(request)

    def locator(self, selector: str) -> _FakeLocator:
        if selector == _PDF_OBJECT_SELECTOR:
            return _FakeLocator(count=1, attribute=self._pdf_object_attribute)
        return _FakeLocator(count=0)

    def wait_for_selector(self, selector: str, **kwargs: Any) -> None:
        del selector, kwargs  # lab-only fake: never called for absent buttons

    @property
    def frames(self) -> list[Any]:
        return []


# ---------------------------------------------------------------------------
# Synthetic fixture loading
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _load_report_block() -> str:
    """Load the versioned synthetic H1 report block (one evolution)."""
    path = _FIXTURES_DIR / "fullsync_synthetic_report_block.txt"
    return path.read_text(encoding="utf-8").strip()


@lru_cache(maxsize=1)
def _load_h2_fixtures() -> list[dict[str, Any]]:
    """Load the versioned synthetic H2 content fixtures."""
    path = _FIXTURES_DIR / "fullsync_synthetic_content.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload["fixtures"]


def load_h2_fixtures() -> list[dict[str, Any]]:
    """Public accessor for the synthetic H2 content fixtures."""
    return _load_h2_fixtures()


def _build_synthetic_report_pdf(block_text: str, count: int) -> bytes:
    """Build an in-memory synthetic PDF with ``count`` evolution pages."""
    import pymupdf  # local import: heavy dependency (mirrors the extractor)

    document = pymupdf.open()
    try:
        for _ in range(count):
            page = document.new_page()
            page.insert_text((72, 72), block_text)
        return document.tobytes()
    finally:
        document.close()


# ---------------------------------------------------------------------------
# H1: timeout by volume / deadline
# ---------------------------------------------------------------------------


def _build_volume_flow(
    *,
    item_count: int,
    deadline_seconds: int,
    latency_per_item_ms: int,
) -> tuple[EvolutionPdfFlow, _FakeRequest]:
    """Build the REAL EvolutionPdfFlow over a synthetic volume fixture.

    Returns the flow and the request spy separately so experiments can
    inspect the bounded download timeout even when ``flow.extract`` raises.
    """
    pdf_bytes = _build_synthetic_report_pdf(_load_report_block(), item_count)
    request = _FakeRequest(
        _FakeResponse(ok=True, body=pdf_bytes),
        latency_ms=latency_per_item_ms * item_count,
    )
    page = _FakePage(pdf_object_attribute=_SYNTHETIC_PDF_URL, request=request)
    return EvolutionPdfFlow(page), request


def _observed_download_timeout_ms(request: _FakeRequest) -> int | None:
    """Return the bounded download timeout the real flow actually passed."""
    if not request.calls:
        return None
    timeout = request.calls[0][1].get("timeout")
    return int(timeout) if timeout is not None else None


def run_h1_timeout_experiment(
    *,
    item_count: int = DEFAULT_H1_ITEM_COUNT,
    deadline_seconds: int = DEFAULT_H1_DEADLINE_SECONDS,
    latency_per_item_ms: int = DEFAULT_H1_LATENCY_PER_ITEM_MS,
) -> ExperimentVerdict:
    """H1: constrained deadline + synthetic long list -> typed ``timeout``."""
    params: dict[str, Any] = {
        "item_count": item_count,
        "deadline_seconds": deadline_seconds,
        "latency_per_item_ms": latency_per_item_ms,
    }
    flow, request = _build_volume_flow(
        item_count=item_count,
        deadline_seconds=deadline_seconds,
        latency_per_item_ms=latency_per_item_ms,
    )
    started = time.monotonic()
    exc: Exception | None = None
    try:
        flow.extract(
            start_date="2026-01-01",
            end_date="2026-01-31",
            admission_key=_SYNTHETIC_ADMISSION_KEY,
            timeout=deadline_seconds,
        )
    except Exception as err:  # noqa: BLE001 - lab captures any failure to classify
        exc = err
    measured = time.monotonic() - started
    reason = classify_failure_reason(exc)[0] if exc is not None else None
    verdict: VerdictValue = "confirmed" if reason == "timeout" else "refuted"
    params["download_timeout_ms"] = _observed_download_timeout_ms(request)
    if verdict == "confirmed":
        notes = (
            "synthetic volume-proportional download overran the shared "
            "monotonic deadline; typed EvolutionPdfTimeoutError surfaced "
            "at the real boundary check"
        )
    else:
        notes = (
            "unexpected outcome: "
            + (f"{type(exc).__name__}" if exc is not None else "no error")
        )
    return ExperimentVerdict(
        hypothesis="H1-timeout-by-volume-deadline",
        fixture="fullsync_synthetic_report_block.txt",
        params=params,
        measured_duration_seconds=round(measured, 3),
        reason=reason,
        verdict=verdict,
        notes=notes,
    )


def run_h1_control_experiment(
    *,
    item_count: int = DEFAULT_H1_CONTROL_ITEM_COUNT,
    deadline_seconds: int = DEFAULT_H1_CONTROL_DEADLINE_SECONDS,
    latency_per_item_ms: int = DEFAULT_H1_CONTROL_LATENCY_PER_ITEM_MS,
) -> ExperimentVerdict:
    """H1 control: generous deadline completes and parses N synthetic events."""
    params: dict[str, Any] = {
        "item_count": item_count,
        "deadline_seconds": deadline_seconds,
        "latency_per_item_ms": latency_per_item_ms,
    }
    flow, request = _build_volume_flow(
        item_count=item_count,
        deadline_seconds=deadline_seconds,
        latency_per_item_ms=latency_per_item_ms,
    )
    started = time.monotonic()
    exc: Exception | None = None
    events: list[dict[str, Any]] = []
    try:
        events = flow.extract(
            start_date="2026-01-01",
            end_date="2026-01-31",
            admission_key=_SYNTHETIC_ADMISSION_KEY,
            timeout=deadline_seconds,
        )
    except Exception as err:  # noqa: BLE001 - lab captures any failure to classify
        exc = err
    measured = time.monotonic() - started
    reason = classify_failure_reason(exc)[0] if exc is not None else None
    parsed_all = exc is None and len(events) == item_count
    verdict: VerdictValue = "confirmed" if parsed_all else "refuted"
    params["download_timeout_ms"] = _observed_download_timeout_ms(request)
    if verdict == "confirmed":
        notes = (
            f"control: generous deadline completed and parsed "
            f"{len(events)} synthetic evolution events"
        )
    else:
        notes = (
            "control failed: "
            + (
                f"{type(exc).__name__}"
                if exc is not None
                else "unexpected event count"
            )
        )
    return ExperimentVerdict(
        hypothesis="H1-control-generous-deadline",
        fixture="fullsync_synthetic_report_block.txt",
        params=params,
        measured_duration_seconds=round(measured, 3),
        reason=reason,
        verdict=verdict,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# H2: invalid_payload by content
# ---------------------------------------------------------------------------


def _run_h2_fixture(fixture: dict[str, Any]) -> Exception | None:
    """Run the real validation path for one synthetic content fixture.

    Returns the raised :class:`ExtractionError` (or ``None`` when the
    synthetic content parses/validates cleanly).
    """
    kind = fixture["kind"]
    content = fixture["content"]
    try:
        if kind in {"invalid_json", "root_not_list", "valid_control"}:
            _parse_evolutions_json(content)
        elif kind == "missing_container":
            _extract_json_from_container(
                content, _EVOLUTION_DATA_DIV_ID, _EVOLUTION_DATA_CONTAINER_RE
            )
        elif kind == "text_html_response":
            body = content.encode("utf-8")
            assert_pdf_response_signature(
                _FakeResponse(headers={"content-type": "text/html"}, body=body),
                body,
            )
        elif kind == "bad_pdf_signature":
            body = content.encode("utf-8")
            assert_pdf_response_signature(
                _FakeResponse(
                    headers={"content-type": "application/pdf"}, body=body
                ),
                body,
            )
        elif kind == "empty_pdf_attribute":
            flow = EvolutionPdfFlow(
                _FakePage(
                    pdf_object_attribute="",
                    request=_FakeRequest(_FakeResponse(ok=True, body=b"")),
                )
            )
            flow.extract(
                start_date="2026-01-01",
                end_date="2026-01-31",
                admission_key="SYNTH-ADM-H2",
                timeout=60,
            )
        else:
            raise ValueError(f"unknown synthetic fixture kind: {kind!r}")
    except ExtractionError as exc:
        return exc
    return None


def run_h2_experiment(fixture: dict[str, Any]) -> ExperimentVerdict:
    """H2: classify one synthetic content fixture through the real classifier."""
    exc = _run_h2_fixture(fixture)
    reason = classify_failure_reason(exc)[0] if exc is not None else None
    expected = fixture.get("expected_reason")
    verdict: VerdictValue = "confirmed" if reason == expected else "refuted"
    params: dict[str, Any] = {
        "fixture_id": fixture["id"],
        "kind": fixture["kind"],
        "exception_type": type(exc).__name__ if exc is not None else None,
    }
    if exc is not None:
        notes = f"validation triggered: {fixture['validation']}"
    else:
        notes = "control: synthetic valid payload parsed without failure"
    return ExperimentVerdict(
        hypothesis=(
            "H2-valid-control"
            if fixture.get("control")
            else "H2-invalid-payload-content"
        ),
        fixture=fixture["id"],
        params=params,
        measured_duration_seconds=None,
        reason=reason,
        verdict=verdict,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Consolidated runner and artifact
# ---------------------------------------------------------------------------


def run_experiments(
    output_path: str | Path | None = None,
    *,
    h1_item_count: int = DEFAULT_H1_ITEM_COUNT,
    h1_deadline_seconds: int = DEFAULT_H1_DEADLINE_SECONDS,
    h1_latency_per_item_ms: int = DEFAULT_H1_LATENCY_PER_ITEM_MS,
    h1_control_item_count: int = DEFAULT_H1_CONTROL_ITEM_COUNT,
    h1_control_deadline_seconds: int = DEFAULT_H1_CONTROL_DEADLINE_SECONDS,
    h1_control_latency_per_item_ms: int = DEFAULT_H1_CONTROL_LATENCY_PER_ITEM_MS,
) -> list[ExperimentVerdict]:
    """Run every lab experiment and consolidate the verdict artifacts."""
    verdicts: list[ExperimentVerdict] = [
        run_h1_timeout_experiment(
            item_count=h1_item_count,
            deadline_seconds=h1_deadline_seconds,
            latency_per_item_ms=h1_latency_per_item_ms,
        ),
        run_h1_control_experiment(
            item_count=h1_control_item_count,
            deadline_seconds=h1_control_deadline_seconds,
            latency_per_item_ms=h1_control_latency_per_item_ms,
        ),
    ]
    verdicts.extend(run_h2_experiment(f) for f in _load_h2_fixtures())
    if output_path is not None:
        write_verdicts(verdicts, output_path)
    return verdicts


def write_verdicts(
    verdicts: list[ExperimentVerdict], output_path: str | Path
) -> None:
    """Write the consolidated synthetic ``verdicts.json`` artifact."""
    payload: dict[str, Any] = {
        "synthetic_sentinel": ARTIFACT_SENTINEL,
        "verdicts": [asdict(v) for v in verdicts],
    }
    Path(output_path).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# On-demand CLI (writes the synthetic verdicts artifact)
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "CFC-S2 synthetic lab: reproduce the H1/H2 full-sync failure "
            "hypotheses against the real extraction/classification code "
            "with 100%% synthetic fixtures (no browser, no network)."
        )
    )
    parser.add_argument(
        "--output",
        default="verdicts.json",
        help="path to write the consolidated verdicts artifact",
    )
    args = parser.parse_args(argv)
    verdicts = run_experiments(output_path=args.output)
    print(f"[fullsync-failure-lab] {len(verdicts)} experiments -> {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
