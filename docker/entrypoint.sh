#!/bin/bash
# =============================================================================
# Entrypoint para SIRHOSP containerizado
# Argumentos: comando fallback (ex: runserver ou gunicorn)
# =============================================================================

set -e

echo "[entrypoint] Starting SIRHOSP container..."

# Garante que o diretório de trabalho existe
mkdir -p /app

# Garante que o diretório de socket do Gunicorn existe (para rootless)
if [ -n "$GUNICORN_WORKER_TMP_DIR" ]; then
    echo "[entrypoint] Ensuring GUNICORN_WORKER_TMP_DIR=$GUNICORN_WORKER_TMP_DIR exists"
    mkdir -p "$GUNICORN_WORKER_TMP_DIR"
    # Garante que o usuário não-root pode escrever
    chmod 1777 "$GUNICORN_WORKER_TMP_DIR" 2>/dev/null || true
fi

# Carrega /app/.env APENAS para variáveis ausentes (não sobrescreve vars do Compose).
# Precedência: vars do Compose > vars exportadas pelo shell > /app/.env
# Isso permite que o Compose defina valores canônicos (ex: DATABASE_URL, SECRET_KEY)
# enquanto .env local adiciona apenas o que faltar.
if [ -f /app/.env ]; then
    echo "[entrypoint] Loading defaults from /app/.env (only if not already set)"
    while IFS='=' read -r key value; do
        # Ignora linhas vazias e comentários (linhas que começam com #)
        if [ -z "$key" ] || [ "${key#\#}" != "$key" ]; then
            continue
        fi
        # Remove aspas do valor
        value="${value%\"}"
        value="${value#\"}"
        # Define apenas se não existir
        eval "[ -z \${$key+x} ]" && export "$key=$value"
    done < /app/.env
fi

# Aguarda PostgreSQL estar disponível (via variáveis de ambiente)
# Somente se POSTGRES_HOST ou DATABASE_URL estiver definido
if [ -n "$DATABASE_URL" ] || [ -n "$POSTGRES_HOST" ]; then
    echo "[entrypoint] Waiting for database..."

    # Construir comando de verificação de conexão
    PGHOST="${POSTGRES_HOST:-${DATABASE_URL#*@}}"
    PGHOST="${PGHOST%%:*}"
    PGPORT="${POSTGRES_PORT:-5432}"
    PGPASSWORD="${POSTGRES_PASSWORD:-}"
    PGUSER="${POSTGRES_USER:-postgres}"

    WAIT_INTERVAL=2
    WAIT_TIMEOUT=60
    ELAPSED=0

    # Loop de healthcheck
    while [ $ELAPSED -lt $WAIT_TIMEOUT ]; do
        if timeout 2 bash -c "echo > /dev/tcp/$PGHOST/$PGPORT" 2>/dev/null; then
            echo "[entrypoint] Database is ready!"
            break
        fi
        echo "[entrypoint] Waiting for database... (${ELAPSED}s/${WAIT_TIMEOUT}s)"
        sleep $WAIT_INTERVAL
        ELAPSED=$((ELAPSED + WAIT_INTERVAL))
    done

    if [ $ELAPSED -ge $WAIT_TIMEOUT ]; then
        echo "[entrypoint] WARNING: Database not ready after ${WAIT_TIMEOUT}s, continuing anyway..."
    fi
fi

# Executa comando recebido do CMD/compose
if [ "$#" -eq 0 ]; then
    echo "[entrypoint] ERROR: no command provided to entrypoint"
    exit 1
fi

# Nota: /app pode vir de bind mount do host e conter .venv local.
# Isso não é problema se UV_PROJECT_ENVIRONMENT apontar para /opt/venv.
echo "[entrypoint] Executing: $*"
exec "$@"
