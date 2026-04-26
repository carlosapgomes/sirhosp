#!/usr/bin/env bash
# =============================================================================
# SIRHOSP — Census Scheduler Script
#
# Executado pelo systemd timer a cada 8h.
# Extrai censo do sistema fonte (Playwright) e processa snapshot
# para enfileirar extrações de admissões e evoluções.
#
# Deploy: copiar para /opt/sirhosp/deploy/ e tornar executável.
# =============================================================================
set -euo pipefail

PROJECT_DIR="/opt/sirhosp"
COMPOSE_FILES=(-f compose.yml -f compose.prod.yml)
LOG_TAG="sirhosp-census"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

log "=== Iniciando ciclo de censo ==="

cd "$PROJECT_DIR" || {
    log "ERRO: diretório do projeto não encontrado: $PROJECT_DIR"
    exit 1
}

# Verifica se o container web está rodando
if ! docker compose "${COMPOSE_FILES[@]}" ps --status running web | grep -q web; then
    log "ERRO: container 'web' não está rodando. Abortando."
    exit 1
fi

# Passo 1: Extrair censo do sistema fonte via Playwright
log "Passo 1/2: Extraindo censo..."
docker compose "${COMPOSE_FILES[@]}" exec -T web \
    uv run --no-sync python manage.py extract_census
log "Passo 1/2: Extração concluída."

# Passo 2: Processar o snapshot (cria/atualiza pacientes, enfileira admissões)
log "Passo 2/2: Processando snapshot..."
docker compose "${COMPOSE_FILES[@]}" exec -T web \
    uv run --no-sync python manage.py process_census_snapshot
log "Passo 2/2: Processamento concluído."

log "=== Ciclo de censo finalizado com sucesso ==="
