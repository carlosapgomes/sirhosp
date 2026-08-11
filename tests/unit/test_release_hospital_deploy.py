"""Contract tests for release images and standalone hospital deployment."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "publish-release-image.yml"
COMPOSE = ROOT / "compose.hospital.yml"


def _workflow_text() -> str:
    assert WORKFLOW.exists(), "release image workflow must exist"
    return WORKFLOW.read_text(encoding="utf-8")


def _compose_text() -> str:
    assert COMPOSE.exists(), "standalone hospital Compose must exist"
    return COMPOSE.read_text(encoding="utf-8")


def _service_block(compose: str, service: str) -> str:
    match = re.search(
        rf"^  {service}:\n(?P<body>(?:    .*\n|\n)+?)"
        r"(?=^  [a-z][a-z0-9_]*:\n|^volumes:\n|^networks:\n|\Z)",
        compose,
        re.MULTILINE,
    )
    assert match, f"service {service!r} not found"
    return match.group("body")


def test_published_release_is_validated_before_image_publication() -> None:
    workflow = _workflow_text()

    assert "release:\n    types: [published]" in workflow
    assert workflow.count("ref: ${{ github.event.release.tag_name }}") == 2
    assert "./scripts/test-in-container.sh quality-gate" in workflow
    assert "publish:\n    needs: validate" in workflow
    assert workflow.index("validate:") < workflow.index("publish:")
    assert "contents: write" in workflow
    assert "packages: write" in workflow


def test_release_image_uses_exact_and_separate_channel_tags() -> None:
    workflow = _workflow_text()

    assert "registry: ghcr.io" in workflow
    assert "username: ${{ github.actor }}" in workflow
    assert "password: ${{ secrets.GITHUB_TOKEN }}" in workflow
    assert "images: ghcr.io/${{ github.repository }}" in workflow
    assert "type=raw,value=${{ github.event.release.tag_name }}" in workflow
    assert (
        "type=raw,value=latest,"
        "enable=${{ github.event.release.prerelease == false }}" in workflow
    )
    assert (
        "type=raw,value=prerelease,"
        "enable=${{ github.event.release.prerelease == true }}" in workflow
    )
    assert "target: prod" in workflow
    assert "push: true" in workflow
    assert "sbom: true" in workflow
    assert "provenance: mode=max" in workflow
    upload = (
        'gh release upload "${{ github.event.release.tag_name }}" '
        "compose.hospital.yml --clobber"
    )
    normalized_workflow = " ".join(workflow.split())
    assert upload in normalized_workflow
    assert normalized_workflow.index(
        "uses: docker/build-push-action@"
    ) < normalized_workflow.index(upload)


def test_hospital_compose_is_standalone_and_version_pinned() -> None:
    compose = _compose_text()

    assert "build:" not in compose
    assert "/app:" not in compose
    assert "tailscale" not in compose.lower()
    assert "cloudflare" not in compose.lower()
    assert "external: true" not in compose
    assert (
        "image: ghcr.io/carlosapgomes/sirhosp:"
        "${SIRHOSP_VERSION:?Set SIRHOSP_VERSION to an exact release tag}"
        in compose
    )
    assert compose.count("\n    ports:\n") == 1
    assert "${SIRHOSP_BIND_ADDRESS:-0.0.0.0}:${DJANGO_PORT:-8000}:8000" in compose
    assert "sirhosp_db_data:/var/lib/postgresql/data" in compose

    for required in (
        "DJANGO_SECRET_KEY",
        "DJANGO_ALLOWED_HOSTS",
        "POSTGRES_PASSWORD",
        "SOURCE_SYSTEM_URL",
        "SOURCE_SYSTEM_USERNAME",
        "SOURCE_SYSTEM_PASSWORD",
    ):
        assert f"${{{required}:?" in compose


def test_hospital_compose_runs_the_complete_current_topology() -> None:
    compose = _compose_text()

    db = _service_block(compose, "db")
    web = _service_block(compose, "web")
    persistent = _service_block(compose, "persistent_worker")
    orchestrator = _service_block(compose, "census_orchestrator")
    summary = _service_block(compose, "summary_worker")

    assert "image: postgres:16-alpine" in db
    assert "ports:" not in db
    assert "healthcheck:" in db
    assert "ports:" in web
    assert "healthcheck:" in web
    assert "container_name:" not in persistent
    assert "process_ingestion_runs_persistent_session" in persistent
    assert "--real-handle" in persistent
    assert "--enable-real-queue" in persistent
    assert "run_adaptive_census_cycles" in orchestrator
    assert "--loop" in orchestrator
    assert "process_summary_runs" in summary
    assert "--pipeline" in summary
    assert compose.count("<<: *app-service") == 3
    assert compose.count("<<: *playwright-service") == 2
    assert "restart: unless-stopped" in compose
    assert "tmpfs:" in compose
    assert "shm_size:" in compose
