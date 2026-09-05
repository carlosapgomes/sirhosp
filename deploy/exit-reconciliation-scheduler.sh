#!/usr/bin/env bash
# =============================================================================
# SIRHOSP — Exit reconciliation scheduler (RPSA-S12)
#
# Entry point used by the disabled-by-default systemd units that schedule
# exit reconciliation on the hospital server (no repository clone there;
# every artifact ships as an immutable release asset):
#
#   d1-recovery        05:00 America/Bahia — previous Bahia calendar date
#                      with the four extractors in canonical order through
#                      the S11 runtime mode --mode d1.
#   hourly-discharges  every hour at minute 13 America/Bahia — current-day
#                      discharges through --mode hourly.
#   stale-sweep        every hour at minute 47 America/Bahia — bounded
#                      stale-admission safety sweep via
#                      reconcile_stale_admissions (own PostgreSQL advisory
#                      lock, enqueues at most 100 confirmations, no
#                      Playwright).
#
# Every mode resolves Docker Compose against the hospital runtime under
# /srv/apps/prisma (host .env + compose.hospital.yml) and executes the
# one-shot Playwright-capable runner through
# `--profile recovery run --rm historical_recovery`. Source automation is
# never routed through the long-running application service, never through
# the deprecated PDF flow and never through the legacy domestic install
# tree.
#
# Exit-code contract: exit 75 (EX_TEMPFAIL) means temporary queue/batch
# contention and is retried AT SCRIPT LEVEL for a hard-coded bound of six
# TOTAL invocations (initial attempt plus at most five retries), each
# retry after a fixed 600-second sleep. ANY other nonzero exit fails
# immediately. The loop can never exceed six total invocations; there is
# no systemd Restart= policy for failures.
# =============================================================================
set -euo pipefail

HOSPITAL_DIR="/srv/apps/prisma"
ENV_FILE="${HOSPITAL_DIR}/.env"
COMPOSE_FILE="${HOSPITAL_DIR}/compose.hospital.yml"
RECOVERY_SERVICE="historical_recovery"

# Default "docker compose"; override only for diagnostics/tests.
DOCKER_COMPOSE="${DOCKER_COMPOSE:-docker compose}"

# Retry contract (fixed, never environment-configurable): exit 75 is
# retried at most five times — a hard-coded bound of six total
# invocations — with a fixed 600-second interval between attempts.
MAX_TOTAL_ATTEMPTS=6
RETRY_SLEEP_SECONDS=600

MODE_D1="d1-recovery"
MODE_HOURLY="hourly-discharges"
MODE_STALE="stale-sweep"

log() {
    printf '[exit-reconciliation] %s %s\n' "$(date '+%Y-%m-%d %H:%M:%S %z')" "$*"
}

usage() {
    cat >&2 <<'EOF'
Usage: exit-reconciliation-scheduler.sh <mode>

Modes (bounded, mutually exclusive):
  d1-recovery         D-1 recovery — previous America/Bahia date, four
                      extractors in canonical order (runtime --mode d1)
  hourly-discharges   Current-day discharges (runtime --mode hourly)
  stale-sweep         Bounded stale-admission safety sweep
                      (reconcile_stale_admissions)
EOF
}

if [ "$#" -ne 1 ]; then
    usage
    exit 2
fi

mode="$1"

case "${mode}" in
    "${MODE_D1}")
        RUNNER_COMMAND=(run_exit_reconciliation_runtime --mode d1)
        ;;
    "${MODE_HOURLY}")
        RUNNER_COMMAND=(run_exit_reconciliation_runtime --mode hourly)
        ;;
    "${MODE_STALE}")
        RUNNER_COMMAND=(reconcile_stale_admissions)
        ;;
    *)
        log "modo desconhecido: ${mode}"
        usage
        exit 2
        ;;
esac

run_runner_once() {
    # Resolves the hospital Compose contract and runs the one-shot runner.
    # shellcheck disable=SC2086
    ${DOCKER_COMPOSE} \
        --env-file "${ENV_FILE}" \
        -f "${COMPOSE_FILE}" \
        --profile recovery \
        run --rm "${RECOVERY_SERVICE}" \
        uv run --no-sync python manage.py "${RUNNER_COMMAND[@]}"
}

log "mode=${mode} hospital_dir=${HOSPITAL_DIR} runner=${RECOVERY_SERVICE}"

attempt=0
while [ "${attempt}" -lt "${MAX_TOTAL_ATTEMPTS}" ]; do
    attempt=$((attempt + 1))
    set +e
    run_runner_once
    exit_code=$?
    set -e
    if [ "${exit_code}" -eq 0 ]; then
        log "mode=${mode} result=success"
        exit 0
    fi
    if [ "${exit_code}" -eq 75 ] && [ "${attempt}" -lt "${MAX_TOTAL_ATTEMPTS}" ]; then
        log "mode=${mode} result=busy exit_code=75 attempt=${attempt}/${MAX_TOTAL_ATTEMPTS} next_attempt_in_seconds=${RETRY_SLEEP_SECONDS}"
        sleep "${RETRY_SLEEP_SECONDS}"
        continue
    fi
    log "mode=${mode} result=failed exit_code=${exit_code}"
    exit "${exit_code}"
done
