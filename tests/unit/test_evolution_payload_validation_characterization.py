"""FX-S3 (H2b/D3): characterization suite for payload validations.

Permanent regression suite pinning the six known payload validations of the
full-sync evolution extraction against the REAL code — no browser, no
network, no subprocess, only minimal duck-typed fakes (the same technique
the CFC laboratory and the operational unit tests use):

1. **Viewer-frame rescue** — an ``<object type="application/pdf"
   data="">`` with an EMPTY ``data`` attribute is rescued by a viewer frame
   URL (``.pdf`` path or ``file=`` query) through the real
   :func:`~apps.ingestion.extractors.persistent_evolution_pdf.resolve_pdf_url_from_page`
   and the real :class:`EvolutionPdfFlow` proceeds.
2. **Genuine absence** — no object and no viewer frame (or an empty
   ``data`` attribute with no viewer) raises the sanitized
   ``EvolutionPdfError`` ("could not be located") that the REAL
   :func:`~apps.ingestion.run_lifecycle.classify_failure_reason` maps to
   ``invalid_payload``.
3. **Response signature — content-type** — a ``text/html`` response where a
   PDF is expected fails :func:`assert_pdf_response_signature` and maps to
   ``invalid_payload``.
4. **Response signature — body** — a body without the ``%PDF-`` signature
   fails the same validation and maps to ``invalid_payload``.
5. **Evolution JSON** — invalid JSON and a non-list root fail
   :func:`_parse_evolutions_json` (``InvalidJsonError``) and map to
   ``invalid_payload``.
6. **Container extraction** — HTML without the ``evolution-data`` container
   fails :func:`_extract_json_from_container`
   (``SnapshotContainerMissingError``) and maps to ``invalid_payload``.

Every content fixture carries the ``SYNTH-FX-S3`` sentinel and every failure
test asserts the sanitized message does NOT echo that sentinel (proving
"genuinely invalid content" is distinguishable from a parsing gap without
leaking payload text). Taxonomy is exercised, never modified: this suite
only pins existing behavior; any RED is a real parsing gap whose fix is
strictly local (per D3 the slice ends with the verdict table in the slice
report).
"""

from __future__ import annotations

from typing import Any

import pytest

from apps.ingestion.extractors.errors import (
    InvalidJsonError,
    SnapshotContainerMissingError,
)
from apps.ingestion.extractors.persistent_evolution_pdf import (
    _PDF_OBJECT_SELECTOR,
    EvolutionPdfError,
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

SENTINEL = "SYNTH-FX-S3"
"""Synthetic marker that every content fixture in this suite MUST carry."""

_INVALID_PDF_MESSAGE = "Downloaded report content is not a valid PDF"
"""Constant sanitized message raised by the real response-signature check."""

_CANNOT_LOCATE_MESSAGE = (
    "Evolution report PDF could not be located on the page"
)
"""Constant sanitized message raised by the real flow on genuine absence."""

_SYNTHETIC_PAGE_URL = "https://legacy.example/synth-report"
_SYNTHETIC_PDF_FRAME_URL = "https://legacy.example/viewer-frame/SYNTH-FX-S3-report.pdf"
_SYNTHETIC_FILE_QUERY_FRAME_URL = (
    "https://legacy.example/viewer?file=/downloads/SYNTH-FX-S3-report.pdf"
)
_SYNTHETIC_PDF_BODY_TEXT = (
    "SYNTH-FX-S3 synthetic evolution PDF page (no real content)"
)

INVALID_PAYLOAD = "invalid_payload"


# ---------------------------------------------------------------------------
# Minimal duck-typed Playwright-like fakes (self-contained; lab pattern)
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
        del value, kwargs  # fake: fills are no-ops

    def click(self, **kwargs: Any) -> None:
        del kwargs  # fake: clicks are no-ops

    def get_attribute(self, name: str, **kwargs: Any) -> str | None:
        del name, kwargs
        return self._attribute


class _FakeResponse:
    """Minimal duck-typed API response for the real validation paths."""

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
    """Duck-typed ``page.context.request`` recording every ``get`` call."""

    def __init__(self, response: _FakeResponse) -> None:
        self._response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> _FakeResponse:
        self.calls.append((url, kwargs))
        return self._response


class _FakeContext:
    def __init__(self, request: _FakeRequest) -> None:
        self.request = request


class _FakeFrame:
    def __init__(self, url: str) -> None:
        self.url = url


class _FakePage:
    """Duck-typed page driving the REAL :class:`EvolutionPdfFlow`.

    Only the selectors the real flow touches are configured: date inputs and
    the generate button are absent (count 0); the PDF object locator carries
    the injected synthetic ``data`` attribute (or is absent); viewer frame
    URLs are injected through ``frames``.
    """

    def __init__(
        self,
        *,
        pdf_object_present: bool = True,
        pdf_object_attribute: str | None = None,
        frame_urls: list[str] | None = None,
        url: str = _SYNTHETIC_PAGE_URL,
        request: _FakeRequest | None = None,
    ) -> None:
        self.url = url
        self._pdf_object_present = pdf_object_present
        self._pdf_object_attribute = pdf_object_attribute
        self._frame_urls = frame_urls or []
        self._request = request or _FakeRequest(_FakeResponse())
        self.context = _FakeContext(self._request)

    def locator(self, selector: str) -> _FakeLocator:
        if selector == _PDF_OBJECT_SELECTOR:
            if not self._pdf_object_present:
                return _FakeLocator(count=0)
            return _FakeLocator(count=1, attribute=self._pdf_object_attribute)
        return _FakeLocator(count=0)

    def wait_for_selector(self, selector: str, **kwargs: Any) -> None:
        del selector, kwargs  # fake: never called for absent buttons

    @property
    def frames(self) -> list[_FakeFrame]:
        return [_FakeFrame(url) for url in self._frame_urls]


def _build_synthetic_pdf(body_text: str) -> bytes:
    """Build an in-memory synthetic PDF (PyMuPDF; mirrors the lab harness)."""
    import pymupdf  # local import: heavy dependency (mirrors the extractor)

    document = pymupdf.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), body_text)
        return document.tobytes()
    finally:
        document.close()


def _assert_maps_to_invalid_payload(error: Exception) -> None:
    """Pin the REAL classifier mapping for a sanitized validation error.

    Every failure path in this suite must classify as ``invalid_payload``,
    never ``timeout`` (taxonomy unchanged; D3 non-goal). Also proves the
    sanitized message never echoes the synthetic content sentinel.
    """
    assert SENTINEL not in str(error)
    reason, timed_out = classify_failure_reason(error)
    assert reason == INVALID_PAYLOAD
    assert timed_out is False


# ---------------------------------------------------------------------------
# R1 — viewer-frame rescue for an empty PDF object ``data`` attribute
# ---------------------------------------------------------------------------


class TestViewerRescueFromEmptyDataAttribute:
    """R1/D3-1: ``<object data="">`` + viewer frame URL -> flow proceeds."""

    def _run_rescue_flow(
        self, frame_url: str
    ) -> tuple[_FakeRequest, list[dict[str, Any]]]:
        request = _FakeRequest(
            _FakeResponse(
                ok=True,
                body=_build_synthetic_pdf(_SYNTHETIC_PDF_BODY_TEXT),
                headers={"content-type": "application/pdf"},
            )
        )
        page = _FakePage(
            pdf_object_present=True,
            pdf_object_attribute="",  # empty data attribute (the gap candidate)
            frame_urls=[frame_url],
            request=request,
        )
        flow = EvolutionPdfFlow(page)
        events = flow.extract(
            start_date="2026-01-01",
            end_date="2026-01-31",
            admission_key=SENTINEL,
            timeout=60,
        )
        # The flow proceeds (no error); the resolved URL is the viewer URL.
        assert request.calls, "flow must download through the viewer-resolved URL"
        return request, events

    def test_empty_data_attribute_rescued_via_pdf_frame_url(self) -> None:
        request, events = self._run_rescue_flow(_SYNTHETIC_PDF_FRAME_URL)
        assert events == []
        assert request.calls[0][0] == _SYNTHETIC_PDF_FRAME_URL

    def test_empty_data_attribute_rescued_via_file_query_frame_url(self) -> None:
        request, events = self._run_rescue_flow(_SYNTHETIC_FILE_QUERY_FRAME_URL)
        assert events == []
        assert request.calls[0][0] == (
            "https://legacy.example/downloads/" + "SYNTH-FX-S3-report.pdf"
        )


# ---------------------------------------------------------------------------
# R2 — genuine absence (no object, no viewer)
# ---------------------------------------------------------------------------


class TestGenuineAbsenceMapsToInvalidPayload:
    """R2/D3-2: nothing resolves a PDF URL -> sanitized error -> invalid_payload."""

    @pytest.mark.parametrize(
        ("pdf_object_present", "pdf_object_attribute", "frame_urls"),
        [
            (False, None, []),  # no object tag at all
            (True, "", []),  # empty data attribute and no viewer
        ],
        ids=["no-object-no-viewer", "empty-attribute-no-viewer"],
    )
    def test_genuine_absence_maps_to_invalid_payload(
        self,
        pdf_object_present: bool,
        pdf_object_attribute: str | None,
        frame_urls: list[str],
    ) -> None:
        page = _FakePage(
            pdf_object_present=pdf_object_present,
            pdf_object_attribute=pdf_object_attribute,
            frame_urls=frame_urls,
        )
        with pytest.raises(EvolutionPdfError) as excinfo:
            EvolutionPdfFlow(page).extract(
                start_date="2026-01-01",
                end_date="2026-01-31",
                admission_key=SENTINEL,
                timeout=60,
            )
        error = excinfo.value
        assert _CANNOT_LOCATE_MESSAGE in str(error)
        _assert_maps_to_invalid_payload(error)


# ---------------------------------------------------------------------------
# R3 — PDF response signature (content-type and %PDF- body signature)
# ---------------------------------------------------------------------------


class TestResponseSignatureValidationMapsToInvalidPayload:
    """R3/D3-3 and D3-4: non-PDF responses fail before parsing."""

    def _assert_validation_failure(
        self, response: _FakeResponse, body: bytes
    ) -> None:
        with pytest.raises(EvolutionPdfError) as excinfo:
            assert_pdf_response_signature(response, body)
        error = excinfo.value
        assert str(error) == _INVALID_PDF_MESSAGE
        _assert_maps_to_invalid_payload(error)

    def test_html_content_type_maps_to_invalid_payload(self) -> None:
        body = "<html><body>SYNTH-FX-S3 legacy error page</body></html>".encode()
        self._assert_validation_failure(
            _FakeResponse(headers={"content-type": "text/html"}, body=body),
            body,
        )

    def test_missing_pdf_signature_maps_to_invalid_payload(self) -> None:
        body = "SYNTH-FX-S3 body without PDF signature".encode()
        self._assert_validation_failure(
            _FakeResponse(
                headers={"content-type": "application/pdf"}, body=body
            ),
            body,
        )


# ---------------------------------------------------------------------------
# R4 — evolution JSON parsing and container extraction
# ---------------------------------------------------------------------------


class TestEvolutionJsonValidationMapsToInvalidPayload:
    """R4/D3-5: invalid JSON and non-list roots are deterministic payloads."""

    def test_invalid_json_maps_to_invalid_payload(self) -> None:
        content = '{"admission_key": "SYNTH-FX-S3", "happened_at": '
        with pytest.raises(InvalidJsonError) as excinfo:
            _parse_evolutions_json(content)
        _assert_maps_to_invalid_payload(excinfo.value)

    def test_non_list_json_root_maps_to_invalid_payload(self) -> None:
        content = '{"type": "object", "note": "SYNTH-FX-S3"}'
        with pytest.raises(InvalidJsonError) as excinfo:
            _parse_evolutions_json(content)
        _assert_maps_to_invalid_payload(excinfo.value)


class TestMissingContainerMapsToInvalidPayload:
    """R4/D3-6: HTML without the evolution-data container is deterministic."""

    def test_missing_container_maps_to_invalid_payload(self) -> None:
        html = (
            "<html><body><p>SYNTH-FX-S3 no evolution-data container"
            "</p></body></html>"
        )
        with pytest.raises(SnapshotContainerMissingError) as excinfo:
            _extract_json_from_container(
                html, _EVOLUTION_DATA_DIV_ID, _EVOLUTION_DATA_CONTAINER_RE
            )
        error = excinfo.value
        assert SENTINEL not in str(error)
        reason, timed_out = classify_failure_reason(error)
        assert reason == INVALID_PAYLOAD
        assert timed_out is False


# ---------------------------------------------------------------------------
# Taxonomy guard: every failure above is invalid_payload, never timeout
# ---------------------------------------------------------------------------


class TestCharacterizationTaxonomyGuard:
    """The suite pins the deterministic mapping for every known validation."""

    def test_no_failure_path_in_this_suite_is_classified_as_timeout(self) -> None:
        # R2/R3/R4 raise sanitized EvolutionPdfError-family errors; the real
        # classifier must map each one to invalid_payload (never timeout).
        # The per-test assertions above already pin that; this guard re-checks
        # that the suite exercises only non-timeout deterministic paths.
        for error in (
            EvolutionPdfError(_CANNOT_LOCATE_MESSAGE),
            InvalidJsonError("Invalid JSON in evolution data"),
            SnapshotContainerMissingError(
                "Page HTML contains no data container."
            ),
        ):
            reason, timed_out = classify_failure_reason(error)
            assert reason == INVALID_PAYLOAD
            assert timed_out is False
