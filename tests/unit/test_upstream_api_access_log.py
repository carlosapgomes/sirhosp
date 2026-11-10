"""Unit evidence for slice UPA-001 R8/R10: every ``/api/v1`` target is sanitized.

The sanitizer reduces request targets by prefix to a fixed route pattern,
drops query strings and leaves every non-API path untouched. The gunicorn
logger class applies it to the access atoms and suppresses framework error
records that would otherwise carry a raw target. The logger also scopes the
access format: an ``/api/v1`` record renders method, sanitized route and
status only, while every other record keeps the access format configured for
the server (gunicorn's default), so portal logging is unchanged.

Synthetic values only.
"""

from __future__ import annotations

import importlib.util
import logging
import re
from datetime import timedelta
from pathlib import Path
from types import ModuleType

import pytest
from gunicorn.config import Config as GunicornConfig

from apps.upstream_api.access_log import (
    API_ACCESS_LOG_FORMAT,
    UNMATCHED_ROUTE,
    SanitizedAccessLogger,
    sanitize_environ,
    sanitize_request_target,
)

GUNICORN_CONF = Path(__file__).resolve().parents[2] / "config" / "gunicorn.conf.py"
ALLOWED_ACCESS_ATOMS = {"m", "U", "s"}
GUNICORN_DEFAULT_ACCESS_LOG_FORMAT = GunicornConfig().access_log_format
PORTAL_ACCESS_LINE = re.compile(
    r'^127\.0\.0\.1 - - '
    r'\[\d{2}/[A-Z][a-z]{2}/\d{4}:\d{2}:\d{2}:\d{2} [+-]\d{4}\] '
    r'"GET /beds/\?setor=640 HTTP/1\.1" '
    r'200 4321 "http://synthetic\.example/beds" "synthetic-agent/1\.0"$'
)


@pytest.mark.parametrize(
    ("target", "expected"),
    [
        ("/api/v1/inpatients/current", "/api/v1/inpatients/current"),
        (
            "/api/v1/inpatients/current?prontuario=0000001&token=synthetic",
            "/api/v1/inpatients/current",
        ),
        ("/api/v1/patients/0000001", UNMATCHED_ROUTE),
        ("/api/v1/patients/0000001?prontuario=0000001", UNMATCHED_ROUTE),
        ("/api/v1/", UNMATCHED_ROUTE),
        ("/api/v1", UNMATCHED_ROUTE),
        ("/api/v1/inpatients/current/../../etc/passwd", UNMATCHED_ROUTE),
        ("/api/v1/inpatients/current/", UNMATCHED_ROUTE),
        ("/beds/?setor=640", "/beds/?setor=640"),
        ("/health/", "/health/"),
        ("/api/v10/anything", "/api/v10/anything"),
        ("/", "/"),
        ("", ""),
    ],
)
def test_sanitize_request_target_reduces_api_targets_and_drops_queries(
    target: str, expected: str
) -> None:
    assert sanitize_request_target(target) == expected


def test_sanitize_environ_rewrites_every_request_target_entry() -> None:
    environ = {
        "REQUEST_METHOD": "GET",
        "RAW_URI": "/api/v1/patients/0000001?prontuario=0000001",
        "PATH_INFO": "/api/v1/patients/0000001",
        "QUERY_STRING": "prontuario=0000001",
    }

    sanitized = sanitize_environ(environ)

    assert sanitized["RAW_URI"] == UNMATCHED_ROUTE
    assert sanitized["PATH_INFO"] == UNMATCHED_ROUTE
    assert sanitized["QUERY_STRING"] == ""
    assert sanitized["REQUEST_METHOD"] == "GET"
    assert environ["RAW_URI"] == "/api/v1/patients/0000001?prontuario=0000001"


def test_sanitize_environ_leaves_portal_targets_intact() -> None:
    environ = {"RAW_URI": "/beds/?setor=640", "PATH_INFO": "/beds/", "QUERY_STRING": "setor=640"}

    assert sanitize_environ(environ) == environ


class _StubConfig:
    loglevel = "info"
    capture_output = False
    errorlog = None
    accesslog: str | None = None
    syslog = False
    logconfig = None
    logconfig_dict = None
    logconfig_json = None
    disable_redirect_access_to_syslog = True
    access_log_format = GUNICORN_DEFAULT_ACCESS_LOG_FORMAT


class _StubResponse:
    headers: tuple[tuple[str, str], ...] = ()

    def __init__(self, status: str = "404 Not Found", sent: int = 0) -> None:
        self.status = status
        self.sent = sent


class _StubRequest:
    headers: tuple[tuple[str, str], ...] = ()


class _RecordingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


def _logger() -> SanitizedAccessLogger:
    return SanitizedAccessLogger(_StubConfig())


def _gunicorn_config() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gunicorn_conf_access_log", GUNICORN_CONF)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _server_access_log_format() -> str:
    """Access format the deployed server uses, as the repo config leaves it."""
    return getattr(_gunicorn_config(), "access_log_format", GUNICORN_DEFAULT_ACCESS_LOG_FORMAT)


def _capture_access_line(
    environ: dict[str, str], *, status: str, sent: int, access_log_format: str
) -> str:
    """Render one record through gunicorn's own access path (``Logger.access``)."""
    config = _StubConfig()
    config.accesslog = "-"  # access logging enabled, as in the deployed server
    config.access_log_format = access_log_format
    logger = SanitizedAccessLogger(config)
    logger.access_log.handlers.clear()  # gunicorn's stdout handler is not under test
    handler = _RecordingHandler()
    logger.access_log.addHandler(handler)
    try:
        logger.access(_StubResponse(status, sent), _StubRequest(), environ, timedelta(0))
    finally:
        logger.access_log.removeHandler(handler)

    assert len(handler.records) == 1
    return handler.records[0].getMessage()


def _portal_environ() -> dict[str, str]:
    return {
        "REQUEST_METHOD": "GET",
        "RAW_URI": "/beds/?setor=640",
        "PATH_INFO": "/beds/",
        "QUERY_STRING": "setor=640",
        "SERVER_PROTOCOL": "HTTP/1.1",
        "REMOTE_ADDR": "127.0.0.1",
        "HTTP_REFERER": "http://synthetic.example/beds",
        "HTTP_USER_AGENT": "synthetic-agent/1.0",
    }


def test_api_access_log_format_references_only_allowed_atoms() -> None:
    referenced = set(re.findall(r"%\(([^)]+)\)", API_ACCESS_LOG_FORMAT))

    assert referenced == ALLOWED_ACCESS_ATOMS


def test_access_log_format_is_scoped_by_request_target() -> None:
    logger = _logger()
    logger.cfg.access_log_format = '%(h)s "%(r)s" %(s)s portal-format'
    api_environ = {
        "REQUEST_METHOD": "GET",
        "RAW_URI": "/api/v1/inpatients/current?prontuario=0000001",
        "PATH_INFO": "/api/v1/inpatients/current",
        "QUERY_STRING": "prontuario=0000001",
    }

    assert logger.access_log_format_for(api_environ) == API_ACCESS_LOG_FORMAT
    assert logger.access_log_format_for(_portal_environ()) == '%(h)s "%(r)s" %(s)s portal-format'


@pytest.mark.parametrize(
    ("target", "status", "expected_line"),
    [
        ("/api/v1/inpatients/current", "200", "GET /api/v1/inpatients/current 200"),
        (
            "/api/v1/inpatients/current?prontuario=0000001&token=synthetic",
            "200",
            "GET /api/v1/inpatients/current 200",
        ),
        ("/api/v1/inpatients/current", "401", "GET /api/v1/inpatients/current 401"),
        (
            "/api/v1/patients/0000001?prontuario=0000001",
            "404",
            f"GET {UNMATCHED_ROUTE} 404",
        ),
    ],
)
def test_api_access_record_carries_method_route_and_status_only(
    target: str, status: str, expected_line: str
) -> None:
    path, _, query = target.partition("?")
    environ = {
        "REQUEST_METHOD": "GET",
        "RAW_URI": target,
        "PATH_INFO": path,
        "QUERY_STRING": query,
        "SERVER_PROTOCOL": "HTTP/1.1",
        # Fields the default gunicorn format would have printed.
        "REMOTE_ADDR": "127.0.0.1",
        "HTTP_REFERER": "http://synthetic.example/prontuario/0000001",
        "HTTP_USER_AGENT": "synthetic-agent/1.0 (0000001)",
    }

    line = _capture_access_line(
        environ,
        status=status,
        sent=565,
        access_log_format=_server_access_log_format(),
    )

    assert line == expected_line
    assert len(line.split()) == 3
    assert "0000001" not in line
    assert "127.0.0.1" not in line
    assert "synthetic-agent" not in line


def test_portal_access_record_keeps_the_default_gunicorn_format() -> None:
    assert not hasattr(
        _gunicorn_config(), "access_log_format"
    ), "a global access_log_format would also narrow portal access records"

    line = _capture_access_line(
        _portal_environ(), status="200", sent=4321, access_log_format=_server_access_log_format()
    )

    assert PORTAL_ACCESS_LINE.match(line), line
    assert len(line.split()) > 3
    # The portal record keeps the request line with its query string intact.
    assert '"GET /beds/?setor=640 HTTP/1.1"' in line


def test_access_atoms_carry_method_sanitized_route_and_status_only() -> None:
    environ = {
        "REQUEST_METHOD": "GET",
        "RAW_URI": "/api/v1/patients/0000001?prontuario=0000001",
        "PATH_INFO": "/api/v1/patients/0000001",
        "QUERY_STRING": "prontuario=0000001",
        "SERVER_PROTOCOL": "HTTP/1.1",
    }

    atoms = _logger().atoms(_StubResponse(), _StubRequest(), environ, timedelta(0))

    assert atoms["r"] == f"GET {UNMATCHED_ROUTE} HTTP/1.1"
    assert atoms["m"] == "GET"
    assert atoms["U"] == UNMATCHED_ROUTE
    assert atoms["q"] == ""
    assert atoms["s"] == "404"
    emitted = " ".join(str(value) for value in atoms.values())
    assert "0000001" not in emitted
    assert "prontuario=" not in emitted


def test_framework_error_records_carrying_api_targets_are_suppressed() -> None:
    logger = _logger()
    handler = _RecordingHandler()
    logger.error_log.addHandler(handler)
    try:
        logger.warning(
            "Invalid request from ip=127.0.0.1: Invalid HTTP request line: %r",
            "GARBAGE /api/v1/patients/0000001?x=1",
        )
        logger.exception("Error handling request %s %s", "GET", "/api/v1/patients/0000001?x=1")
        logger.error("Worker warm-up finished")
    finally:
        logger.error_log.removeHandler(handler)

    messages = [record.getMessage() for record in handler.records]

    assert messages == ["Worker warm-up finished"]
    assert all("/api/v1" not in message for message in messages)


def test_framework_error_records_without_api_targets_are_kept() -> None:
    logger = _logger()
    handler = _RecordingHandler()
    logger.error_log.addHandler(handler)
    try:
        logger.error("Worker timeout after %s seconds", 120)
    finally:
        logger.error_log.removeHandler(handler)

    assert [record.getMessage() for record in handler.records] == [
        "Worker timeout after 120 seconds"
    ]
