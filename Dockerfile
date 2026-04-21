# syntax=docker/dockerfile:1
# =============================================================================
# Multi-stage Dockerfile for SIRHOSP
# Targets: dev (hot reload) | prod (Gunicorn)
# =============================================================================

# ---- Base stage (comum a ambos) -------------------------------------------
FROM python:3.12-slim-bookworm AS base

# Evitar interactividade do apt
ENV DEBIAN_FRONTEND=noninteractive
# Usar uv como package manager padrão
ENV UV_SYSTEM=1
# Configuração mínima do Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install container entrypoint in a stable path
COPY docker/entrypoint.sh /usr/local/bin/sirhosp-entrypoint
RUN chmod +x /usr/local/bin/sirhosp-entrypoint

WORKDIR /app

# Copia lockfile para cache de dependências
COPY pyproject.toml uv.lock* ./

# ---- Dev stage ------------------------------------------------------------
FROM base AS dev

# Instalação de ferramentas de desenvolvimento (debug, etc.)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Cria ambiente virtual em diretório fora do bind mount (/opt)
# Isso evita problemas de permissão com .venv em /app (bind mount do host)
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
# Cache em diretório gravável pelo usuário não-root
ENV UV_CACHE_DIR=/home/10001/.uv_cache

# Instala dependências via lockfile no ambiente virtual
# --no-install-project: não instala o projeto em si (código vem do bind mount)
# --no-dev: não instala dependências de desenvolvimento (opcional, manter para dev)
RUN uv sync --frozen --no-install-project --no-dev

# Usuário não-root para compatibilidade rootless
# Cria diretório de cache antes de mudar owner
RUN mkdir -p /home/10001/.uv_cache && chown -R 10001:10001 /home/10001
USER 10001:10001

# Portas e metadata
EXPOSE 8000
ENV DJANGO_SETTINGS_MODULE=config.settings
ENV DEBUG=1

ENTRYPOINT ["/usr/local/bin/sirhosp-entrypoint"]
CMD ["uv", "run", "--no-sync", "python", "manage.py", "runserver", "0.0.0.0:8000"]

# ---- Prod stage ------------------------------------------------------------
FROM base AS prod

# Copia o projeto completo (sem .dockerignore exclui o que precisa)
COPY . .

# Ambiente virtual em /opt/venv para consistência
ENV UV_PROJECT_ENVIRONMENT=/opt/venv
ENV UV_CACHE_DIR=/opt/.uv_cache

# Cria diretório de cache com permissões para usuário não-root
RUN mkdir -p /opt/.uv_cache && chown -R 10001:10001 /opt/.uv_cache

# Cria diretório para socket de controle do Gunicorn (rootless compatible)
RUN mkdir -p /tmp/gunicorn && chown -R 10001:10001 /tmp/gunicorn

# Copia wrapper do Gunicorn
COPY docker/gunicorn-wrapper.sh /usr/local/bin/sirhosp-gunicorn-wrapper
RUN chmod +x /usr/local/bin/sirhosp-gunicorn-wrapper

# Instala projeto com todas as dependências incluindo dev (para fixtures de test)
# UV_NO_GIT: evita criar arquivos .git no cache
RUN UV_NO_GIT=1 uv sync --frozen --all-extras

# Coleta staticfiles para servir via Nginx/Gunicorn
RUN uv run python manage.py collectstatic --noinput || true

# Usuário não-root
USER 10001:10001

# Portas e metadata
EXPOSE 8000
ENV DJANGO_SETTINGS_MODULE=config.settings
ENV DEBUG=0

# Gunicorn: diretório para socket de controle dos workers (rootless compatible)
ENV GUNICORN_WORKER_TMP_DIR=/tmp/gunicorn

ENTRYPOINT ["/usr/local/bin/sirhosp-entrypoint"]
CMD ["/usr/local/bin/sirhosp-gunicorn-wrapper"]
