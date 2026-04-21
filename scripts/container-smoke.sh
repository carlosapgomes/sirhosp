#!/usr/bin/env bash
# =============================================================================
# Container Smoke Test - SIRHOSP
# Valida stack dev e prod em container via docker compose
# Fail-fast: exit code != 0 em qualquer falha
# =============================================================================

set -e  # Fail-fast: qualquer comando falhando aborta

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

# Função de log
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Função para limpar e sair
cleanup() {
    local exit_code=$?
    log_info "Limpando ambientes..."
    # Limpa prod se existir
    docker compose -f compose.yml -f compose.prod.yml down -v --remove-orphans 2>/dev/null || true
    # Limpa dev se existir
    docker compose -f compose.yml -f compose.dev.yml down -v --remove-orphans 2>/dev/null || true
    exit $exit_code
}

trap cleanup EXIT

# Validação de dependências
check_deps() {
    log_info "Validando dependências..."

    for cmd in docker curl grep; do
        if ! command -v $cmd &> /dev/null; then
            log_error "Comando '$cmd' não encontrado. Instale antes de continuar."
            exit 1
        fi
    done

    log_info "Dependências validadas."
}

# Smoke test para modo DEV
smoke_dev() {
    log_info "=========================================="
    log_info "INICIANDO SMOKE TEST - MODO DEV"
    log_info "=========================================="

    # Cleanup prévio
    docker compose -f compose.yml -f compose.dev.yml down -v --remove-orphans 2>/dev/null || true

    # Build
    log_info "[DEV] Construindo imagem..."
    if ! docker compose -f compose.yml -f compose.dev.yml build web worker; then
        log_error "[DEV] Build falhou!"
        exit 1
    fi
    log_info "[DEV] Build OK"

    # Up
    log_info "[DEV] Subindo stack..."
    if ! docker compose -f compose.yml -f compose.dev.yml up -d db web worker; then
        log_error "[DEV] Up falhou!"
        exit 1
    fi

    # Aguarda db ficar healthy
    log_info "[DEV] Aguardando db ficar healthy..."
    local max_wait=60
    local count=0
    while [ $count -lt $max_wait ]; do
        if docker compose -f compose.yml -f compose.dev.yml exec -T db pg_isready -U sirhosp -d sirhosp &>/dev/null; then
            break
        fi
        sleep 1
        count=$((count + 1))
    done
    if [ $count -ge $max_wait ]; then
        log_error "[DEV] Db não ficou healthy após ${max_wait}s"
        docker compose -f compose.yml -f compose.dev.yml logs db
        exit 1
    fi
    log_info "[DEV] Db healthy"

    # Migrações
    log_info "[DEV] Aplicando migrações..."
    if ! docker compose -f compose.yml -f compose.dev.yml exec -T web uv run --no-sync python manage.py migrate --noinput; then
        log_error "[DEV] Migrações falharam!"
        exit 1
    fi

    # Check
    log_info "[DEV] Executando manage.py check..."
    if ! docker compose -f compose.yml -f compose.dev.yml exec -T web uv run --no-sync python manage.py check; then
        log_error "[DEV] manage.py check falhou!"
        exit 1
    fi

    # Health check
    log_info "[DEV] Verificando /health/..."
    local max_wait=30
    local count=0
    while [ $count -lt $max_wait ]; do
        if curl -sf http://localhost:8000/health/ &>/dev/null; then
            break
        fi
        sleep 1
        count=$((count + 1))
    done
    if [ $count -ge $max_wait ]; then
        log_error "[DEV] /health/ não respondeu após ${max_wait}s"
        docker compose -f compose.yml -f compose.dev.yml logs web
        exit 1
    fi

    # Captura resposta do health
    local health_response
    health_response=$(curl -sf http://localhost:8000/health/)
    log_info "[DEV] Health response: $health_response"

    # PS
    log_info "[DEV] Status dos serviços:"
    docker compose -f compose.yml -f compose.dev.yml ps

    # Logs
    log_info "[DEV] Logs do web (últimas 20 linhas):"
    docker compose -f compose.yml -f compose.dev.yml logs web --tail=20

    # Down
    log_info "[DEV] Encerrando stack..."
    if ! docker compose -f compose.yml -f compose.dev.yml down -v --remove-orphans; then
        log_error "[DEV] Down falhou!"
        exit 1
    fi

    # Verifica que não há containers ativos
    log_info "[DEV] Verificando containers removidos..."
    local active_dev
    active_dev=$(docker ps -aq --filter "name=sirhosp" 2>/dev/null || echo "")
    if [ -n "$active_dev" ]; then
        log_warn "[DEV] Ainda há containers ativos: $active_dev"
    else
        log_info "[DEV] Nenhum container ativo da stack dev"
    fi

    log_info "[DEV] SMOKE DEV CONCLUÍDO COM SUCESSO"
}

# Smoke test para modo PROD
smoke_prod() {
    log_info "=========================================="
    log_info "INICIANDO SMOKE TEST - MODO PROD"
    log_info "=========================================="

    # Cleanup prévio
    docker compose -f compose.yml -f compose.prod.yml down -v --remove-orphans 2>/dev/null || true

    # Build
    log_info "[PROD] Construindo imagem..."
    if ! docker compose -f compose.yml -f compose.prod.yml build web worker; then
        log_error "[PROD] Build falhou!"
        exit 1
    fi
    log_info "[PROD] Build OK"

    # Up
    log_info "[PROD] Subindo stack..."
    if ! docker compose -f compose.yml -f compose.prod.yml up -d db web worker; then
        log_error "[PROD] Up falhou!"
        exit 1
    fi

    # Aguarda db ficar healthy
    log_info "[PROD] Aguardando db ficar healthy..."
    local max_wait=60
    local count=0
    while [ $count -lt $max_wait ]; do
        if docker compose -f compose.yml -f compose.prod.yml exec -T db pg_isready -U sirhosp -d sirhosp &>/dev/null; then
            break
        fi
        sleep 1
        count=$((count + 1))
    done
    if [ $count -ge $max_wait ]; then
        log_error "[PROD] Db não ficou healthy após ${max_wait}s"
        docker compose -f compose.yml -f compose.prod.yml logs db
        exit 1
    fi
    log_info "[PROD] Db healthy"

    # Migrações
    log_info "[PROD] Aplicando migrações..."
    if ! docker compose -f compose.yml -f compose.prod.yml exec -T web uv run --no-sync python manage.py migrate --noinput; then
        log_error "[PROD] Migrações falharam!"
        exit 1
    fi

    # Check
    log_info "[PROD] Executando manage.py check..."
    if ! docker compose -f compose.yml -f compose.prod.yml exec -T web uv run --no-sync python manage.py check; then
        log_error "[PROD] manage.py check falhou!"
        exit 1
    fi

    # Health check
    log_info "[PROD] Verificando /health/..."
    local max_wait=30
    local count=0
    while [ $count -lt $max_wait ]; do
        if curl -sf http://localhost:8000/health/ &>/dev/null; then
            break
        fi
        sleep 1
        count=$((count + 1))
    done
    if [ $count -ge $max_wait ]; then
        log_error "[PROD] /health/ não respondeu após ${max_wait}s"
        docker compose -f compose.yml -f compose.prod.yml logs web
        exit 1
    fi

    # Captura resposta do health
    local health_response
    health_response=$(curl -sf http://localhost:8000/health/)
    log_info "[PROD] Health response: $health_response"

    # PS
    log_info "[PROD] Status dos serviços:"
    docker compose -f compose.yml -f compose.prod.yml ps

    # Logs do web - verifica ausência de Permission denied
    log_info "[PROD] Logs do web (últimas 50 linhas):"
    docker compose -f compose.yml -f compose.prod.yml logs web --tail=50

    # GATE CRÍTICO: Verifica ausência de Permission denied para /.gunicorn
    log_info "[PROD] GATE: Verificando ausência de 'Permission denied: /.gunicorn'..."
    if docker compose -f compose.yml -f compose.prod.yml logs web --tail=200 2>&1 | grep -F "Permission denied: '/.gunicorn'" >/dev/null 2>&1; then
        log_error "[PROD] GATE FALHOU: Encontrado 'Permission denied: /.gunicorn' nos logs!"
        docker compose -f compose.yml -f compose.prod.yml logs web --tail=200 | grep -F "Permission denied"
        exit 1
    fi
    log_info "[PROD] GATE PASSOU: Sem 'Permission denied: /.gunicorn' nos logs"

    # Logs do worker
    log_info "[PROD] Logs do worker (últimas 20 linhas):"
    docker compose -f compose.yml -f compose.prod.yml logs worker --tail=20

    # Down
    log_info "[PROD] Encerrando stack..."
    if ! docker compose -f compose.yml -f compose.prod.yml down -v --remove-orphans; then
        log_error "[PROD] Down falhou!"
        exit 1
    fi

    # Verifica que não há containers ativos
    log_info "[PROD] Verificando containers removidos..."
    local active_prod
    active_prod=$(docker ps -aq --filter "name=sirhosp" 2>/dev/null || echo "")
    if [ -n "$active_prod" ]; then
        log_warn "[PROD] Ainda há containers ativos: $active_prod"
    else
        log_info "[PROD] Nenhum container ativo da stack prod"
    fi

    log_info "[PROD] SMOKE PROD CONCLUÍDO COM SUCESSO"
}

# MAIN
main() {
    log_info "=========================================="
    log_info "SIRHOSP - Container Smoke Test"
    log_info "=========================================="

    check_deps

    # Executa smoke dev
    smoke_dev

    # Executa smoke prod
    smoke_prod

    log_info "=========================================="
    log_info "TODOS OS SMOKE TESTS PASSARAM!"
    log_info "=========================================="
    exit 0
}

main "$@"