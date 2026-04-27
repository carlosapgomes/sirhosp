#!/usr/bin/env bash
# =============================================================================
# SIRHOSP — Discharges Scheduler Script
#
# Executado pelo systemd timer 3x/dia (11:00, 19:00, 23:55).
# Extrai a lista de altas do dia do sistema fonte e atualiza
# Admission.discharge_date para os pacientes que receberam alta.
#
# Deploy: copiar para /opt/sirhosp/deploy/ e tornar executável.
# =============================================================================
set -euo pipefail

PROJECT_DIR="/opt/sirhosp"
COMPOSE_FILES=(-f compose.yml -f compose.prod.yml)
LOG_TAG="sirhosp-discharges"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log "=== Iniciando extração de altas ==="

cd "$PROJECT_DIR" || {
    log "ERRO: diretório do projeto não encontrado: $PROJECT_DIR"
    exit 1
}

# Verifica se o container web está rodando
if ! docker compose "${COMPOSE_FILES[@]}" ps --status running web | grep -q web; then
    log "ERRO: container 'web' não está rodando. Abortando."
    exit 1
fi

# Executar extração de altas
log "Extraindo altas do dia..."
docker compose "${COMPOSE_FILES[@]}" exec -T web \
    uv run --no-sync python manage.py extract_discharges

log "=== Extração de altas finalizada ==="
