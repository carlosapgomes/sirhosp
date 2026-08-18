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


def test_release_is_assembled_as_draft_after_exact_tag_validation() -> None:
    workflow = _workflow_text()
    normalized = " ".join(workflow.split())

    assert "workflow_dispatch:" in workflow
    assert "release_tag:" in workflow
    assert "prerelease:" in workflow
    assert "release:\n    types: [published]" not in workflow
    assert "ref: ${{ inputs.release_tag }}" in workflow
    assert "commit_sha: ${{ steps.release.outputs.commit_sha }}" in workflow
    assert "ref: ${{ needs.validate.outputs.commit_sha }}" in workflow
    assert "./scripts/test-in-container.sh quality-gate" in workflow
    assert "publish:\n    needs: validate" in workflow
    assert workflow.index("validate:") < workflow.index("publish:")
    assert "contents: write" in workflow
    assert "packages: write" in workflow

    create = 'gh release create "$RELEASE_TAG" compose.hospital.yml'
    build = "uses: docker/build-push-action@"
    publish = 'gh release edit "$RELEASE_TAG" --draft=false'
    assert create in normalized
    assert "--draft" in normalized
    assert normalized.index(create) < normalized.index(build)
    assert normalized.index(build) < normalized.index(publish)


def test_release_attaches_version_specific_upgrade_runbook() -> None:
    workflow = _workflow_text()
    normalized = " ".join(workflow.split())

    assert 'UPGRADE_ASSET="docs/releases/${RELEASE_TAG}-upgrade.md"' in workflow
    require_asset = 'test -f "${UPGRADE_ASSET}"'
    create = (
        'gh release create "$RELEASE_TAG" compose.hospital.yml '
        '"${UPGRADE_ASSET}"'
    )
    assert require_asset in workflow
    assert create in normalized
    assert normalized.index(require_asset) < normalized.index(create)
    assert normalized.index(require_asset) < normalized.index(
        "uses: docker/build-push-action@"
    )


def test_release_image_and_release_are_immutable_and_channel_safe() -> None:
    workflow = _workflow_text()
    normalized = " ".join(workflow.split())

    assert "registry: ghcr.io" in workflow
    assert "username: ${{ github.actor }}" in workflow
    assert "password: ${{ secrets.GITHUB_TOKEN }}" in workflow
    assert "images: ghcr.io/${{ github.repository }}" in workflow
    assert "type=raw,value=${{ inputs.release_tag }}" in workflow
    assert (
        "type=raw,value=latest,enable=${{ inputs.prerelease == false }}"
        in workflow
    )
    assert (
        "type=raw,value=prerelease,enable=${{ inputs.prerelease == true }}"
        in workflow
    )
    assert "repos/${{ github.repository }}/immutable-releases" in workflow
    assert "docker buildx imagetools inspect" in workflow
    assert "exact image tag already exists" in workflow
    assert "target: prod" in workflow
    assert "push: true" in workflow
    assert "sbom: true" in workflow
    assert "provenance: mode=max" in workflow
    assert "--clobber" not in workflow
    assert 'gh release edit "$RELEASE_TAG" --draft=false' in normalized
    assert '"repos/${{ github.repository }}/releases/tags/${RELEASE_TAG}"' in workflow
    assert "--jq .immutable" in workflow


def test_hospital_compose_is_standalone_and_version_pinned() -> None:
    compose = _compose_text()

    assert "build:" not in compose
    assert "/app:" not in compose
    assert "tailscale" not in compose.lower()
    assert "cloudflare" not in compose.lower()
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


def test_hospital_compose_joins_existing_cloudflared_edge_network() -> None:
    compose = _compose_text()
    app_service = compose.split(
        "x-app-service: &app-service",
        maxsplit=1,
    )[1].split("x-playwright-service:", maxsplit=1)[0]
    db = _service_block(compose, "db")
    web = _service_block(compose, "web")

    assert "\n  hospital_edge:\n    external: true\n" in compose
    assert "    internal:\n    hospital_edge:\n" in app_service
    assert "    - internal\n" in db
    assert "      hospital_edge:\n        aliases:\n          - prisma\n" in web


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
