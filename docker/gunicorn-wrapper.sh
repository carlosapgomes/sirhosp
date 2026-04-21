#!/bin/bash
# =============================================================================
# Wrapper para Gunicorn com variáveis de ambiente críticas
# Resolve problemas de permission denied em ambientes rootless
# =============================================================================

set -e

# Garante diretório de trabalho
mkdir -p /app

# Garante que o diretório de socket do Gunicorn existe (para rootless)
if [ -n "$GUNICORN_WORKER_TMP_DIR" ]; then
    echo "[gunicorn-wrapper] Ensuring GUNICORN_WORKER_TMP_DIR=$GUNICORN_WORKER_TMP_DIR exists"
    mkdir -p "$GUNICORN_WORKER_TMP_DIR"
    # Garante que o usuário não-root pode escrever (sticky bit)
    chmod 1777 "$GUNICORN_WORKER_TMP_DIR" 2>/dev/null || true
fi

# Para rootless, desabilitamos o control socket completamente
# para evitar o erro "Permission denied: '/.gunicorn'"
echo "[gunicorn-wrapper] Disabling control socket (--no-control-socket) for rootless compatibility"

# Executa Gunicorn com configuração do config/gunicorn.conf.py
# --no-control-socket é CRÍTICO para rootless: evita tentar criar /.gunicorn
# --graceful-timeout 0 desabilita graceful restart
# --worker-tmp-dir define diretório para arquivos temporários dos workers

exec uv run gunicorn \
    --config config/gunicorn.conf.py \
    --bind "0.0.0.0:8000" \
    --workers "${GUNICORN_WORKERS:-2}" \
    --threads "${GUNICORN_THREADS:-2}" \
    --worker-tmp-dir "${GUNICORN_WORKER_TMP_DIR:-/tmp/gunicorn}" \
    --graceful-timeout 0 \
    --timeout 120 \
    --no-control-socket \
    --access-logfile - \
    --error-logfile - \
    config.wsgi:application