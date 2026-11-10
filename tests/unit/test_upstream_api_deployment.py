"""Unit evidence for slice UPA-001 R1/R9: route registration, env wiring, logger.

Checks that ``/api/v1/`` is served by the isolated app, that the upstream token
is wired into both production compose environments and documented in
``.env.example``, and that ``config/gunicorn.conf.py`` binds only the
``logger_class`` addition while keeping the rootless boot directives intact.

Synthetic values only.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from types import ModuleType

from django.urls import resolve
from gunicorn.glogging import Logger

from apps.upstream_api.access_log import SanitizedAccessLogger

ROOT = Path(__file__).resolve().parents[2]
COMPOSE_PROD = ROOT / "compose.prod.yml"
COMPOSE_HOSPITAL = ROOT / "compose.hospital.yml"
ENV_EXAMPLE = ROOT / ".env.example"
GUNICORN_CONF = ROOT / "config" / "gunicorn.conf.py"
LOGGER_PATH = "apps.upstream_api.access_log.SanitizedAccessLogger"


def _service_block(compose: str, service: str) -> str:
    match = re.search(
        rf"^  {service}:\n(?P<body>(?:    .*\n|\n)+?)"
        r"(?=^  [a-z][a-z0-9_]*:\n|^volumes:\n|^networks:\n|\Z)",
        compose,
        re.MULTILINE,
    )
    assert match, f"service {service!r} not found"
    return match.group("body")


def test_photo_route_resolves_to_the_isolated_app() -> None:
    match = resolve("/api/v1/inpatients/current")

    assert match.view_name == "upstream_api:current_inpatients"


def test_prod_compose_web_environment_exposes_the_upstream_token() -> None:
    web = _service_block(COMPOSE_PROD.read_text(encoding="utf-8"), "web")

    assert "- SIRHOSP_UPSTREAM_API_TOKEN=${SIRHOSP_UPSTREAM_API_TOKEN:-}" in web


def test_hospital_compose_shared_environment_exposes_the_upstream_token() -> None:
    text = COMPOSE_HOSPITAL.read_text(encoding="utf-8")
    shared = text.split("x-app-environment: &app-environment", 1)[1].split("x-app-service:", 1)[0]

    assert 'SIRHOSP_UPSTREAM_API_TOKEN: "${SIRHOSP_UPSTREAM_API_TOKEN:-}"' in shared


def test_env_example_documents_the_upstream_token() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "SIRHOSP_UPSTREAM_API_TOKEN=" in text


def _gunicorn_config() -> ModuleType:
    spec = importlib.util.spec_from_file_location("gunicorn_conf_under_test", GUNICORN_CONF)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gunicorn_config_binds_the_sanitized_logger_class() -> None:
    config = _gunicorn_config()

    assert config.logger_class == LOGGER_PATH
    assert issubclass(SanitizedAccessLogger, Logger)


def test_gunicorn_rootless_boot_directives_are_untouched() -> None:
    config = _gunicorn_config()

    assert config.preload_app is True
    assert config.graceful_timeout == 0
    assert config.worker_class == "gthread"
    assert config.worker_tmp_dir
    assert config.accesslog == "-"
    assert config.errorlog == "-"
