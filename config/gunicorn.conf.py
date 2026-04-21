"""
Gunicorn configuration for production.

Configurações otimizadas para ambiente rootless com:
- worker_tmp_dir configurado para diretório gravável
- graceful_timeout = 0 para evitar criação de control socket em /.
- threads = 2 para melhor performance com gthread worker

Usar via:
  docker compose -f compose.yml -f compose.prod.yml up -d web
"""
import os

# =============================================================================
# Server socket
# =============================================================================

# Binding padrão - TCP em todas as interfaces
bind = os.getenv("GUNICORN_BIND", "0.0.0.0:8000")

# =============================================================================
# Worker processes
# =============================================================================

# Usar gthread (thread-based) em vez de sync para melhor performance
# e compatibilidade com rootless onde control socket pode ter problemas
worker_class = os.getenv("GUNICORN_WORKER_CLASS", "gthread")

# Número de workers
workers = int(os.getenv("GUNICORN_WORKERS", "2"))

# Número de threads por worker (para gthread workers)
threads = int(os.getenv("GUNICORN_THREADS", "2"))

# =============================================================================
# Worker tmp dir - CRÍTICO PARA ROOTLESS
# =============================================================================

# O diretório temporário para workers deve ser configurável
_worker_tmp_dir = os.getenv("GUNICORN_WORKER_TMP_DIR", "/tmp/gunicorn")
worker_tmp_dir = _worker_tmp_dir

# =============================================================================
# Timeouts
# =============================================================================

# CRÍTICO para rootless: graceful_timeout = 0 evita que Gunicorn tente
# criar control socket em /.gunicorn que causa Permission denied
graceful_timeout = 0

# Timeout de requisição
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))

# =============================================================================
# Logging
# =============================================================================

# Logs para stdout/stderr (capturados pelo Docker)
accesslog = os.getenv("GUNICORN_ACCESS_LOG", "-")
errorlog = os.getenv("GUNICORN_ERROR_LOG", "-")
loglevel = os.getenv("GUNICORN_LOG_LEVEL", "info")

# =============================================================================
# Process naming
# =============================================================================

proc_name = "sirhosp-gunicorn"

# =============================================================================
# Server mechanics
# =============================================================================

# Keepalive
keepalive = 5

# Max requests por worker (previne memory leaks)
max_requests = int(os.getenv("GUNICORN_MAX_REQUESTS", "1000"))
max_requests_jitter = int(os.getenv("GUNICORN_MAX_REQUESTS_JITTER", "50"))

# Forwarded for (para proxies)
forwarded_allow_ips = os.getenv("GUNICORN_FORWARDED_IPS", "*")

# Preload app
preload_app = True

# =============================================================================
# Security
# =============================================================================

# Desabilitar sendfile para evitar problemas com sockets
# Isso também pode ajudar a evitar o problema do control socket
def on_starting(server):
    """Called just before the master process is initialized."""
    pass

def post_fork(server, worker):
    """Called just after a worker has been forked."""
    pass