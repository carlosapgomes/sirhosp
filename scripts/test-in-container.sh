#!/usr/bin/env bash
# =============================================================================
# SIRHOSP - Testes e quality gates em container
# Fluxo: up -> wait -> run -> down
# =============================================================================

set -euo pipefail

COMPOSE_ARGS=(-p "${SIRHOSP_TEST_PROJECT:-sirhosp-test}" -f compose.yml -f compose.test.yml)
TEST_DB_PORT="${SIRHOSP_TEST_DB_PORT:-55432}"

log() {
    printf '[test-in-container] %s\n' "$1"
}

usage() {
    cat <<'EOF'
Usage:
  ./scripts/test-in-container.sh <command>

Commands:
  check         Run Django system checks
  unit          Run unit tests (tests/unit)
  integration   Run integration tests (tests/integration)
  lint          Run ruff lint
  typecheck     Run mypy
  check-and-unit     Run check + unit (single container)
  lint-and-typecheck Run lint + typecheck (single container, no DB)
  quality-gate  Run check + unit + lint + typecheck
EOF
}

dc() {
    POSTGRES_PORT="$TEST_DB_PORT" docker compose "${COMPOSE_ARGS[@]}" "$@"
}

wait_for_db() {
    log "Waiting for db healthcheck..."
    local retries=60
    local count=0

    until dc exec -T db pg_isready -U "${POSTGRES_USER:-sirhosp}" -d "${POSTGRES_DB:-sirhosp}" >/dev/null 2>&1; do
        sleep 1
        count=$((count + 1))
        if [ "$count" -ge "$retries" ]; then
            log "ERROR: db did not become healthy within ${retries}s"
            dc logs db || true
            return 1
        fi
    done
    log "db is healthy"
}

up_stack() {
    log "Starting db service on host port ${TEST_DB_PORT}..."
    dc up -d db
    wait_for_db
}

run_runner() {
    local runner_cmd="$1"
    log "Running: ${runner_cmd}"
    dc run --rm test-runner bash -lc "${runner_cmd}"
}

cleanup() {
    local exit_code=$?
    log "Tearing down test stack..."
    dc down --remove-orphans >/dev/null 2>&1 || true
    exit "$exit_code"
}

main() {
    if [ "${1:-}" = "" ]; then
        usage
        exit 1
    fi

    local cmd="$1"

    case "$cmd" in
        check)
            up_stack
            trap cleanup EXIT
            run_runner "uv run --no-sync python manage.py check"
            ;;
        unit)
            up_stack
            trap cleanup EXIT
            run_runner "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q tests/unit"
            ;;
        integration)
            up_stack
            trap cleanup EXIT
            run_runner "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q tests/integration"
            ;;
        lint)
            up_stack
            trap cleanup EXIT
            run_runner "uv run --no-sync ruff check config apps tests manage.py"
            ;;
        typecheck)
            up_stack
            trap cleanup EXIT
            run_runner "uv run --no-sync mypy config apps tests manage.py"
            ;;
        quality-gate)
            up_stack
            trap cleanup EXIT
            run_runner "uv run --no-sync python manage.py check"
            run_runner "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q tests/unit"
            run_runner "uv run --no-sync ruff check config apps tests manage.py"
            run_runner "uv run --no-sync mypy config apps tests manage.py"
            ;;
        check-and-unit)
            up_stack
            trap cleanup EXIT
            run_runner "uv run --no-sync python manage.py check"
            run_runner "PYTEST_ADDOPTS='-p no:cacheprovider' uv run --no-sync pytest -q tests/unit"
            ;;
        lint-and-typecheck)
            # No DB needed — run in fresh container without database.
            # Unset POSTGRES_HOST to skip the entrypoint DB wait.
            log "Running lint and typecheck (no database)..."
            dc run --rm --no-deps \
                -e POSTGRES_HOST="" \
                -e DATABASE_URL="" \
                test-runner bash -lc "uv run --no-sync ruff check config apps tests manage.py"
            dc run --rm --no-deps \
                -e POSTGRES_HOST="" \
                -e DATABASE_URL="" \
                test-runner bash -lc "uv run --no-sync mypy config apps tests manage.py"
            ;;
        -h|--help|help)
            usage
            ;;
        *)
            usage
            exit 1
            ;;
    esac
}

main "$@"
