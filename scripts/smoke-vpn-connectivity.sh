#!/usr/bin/env bash
# =============================================================================
# Smoke de conectividade VPN (dev-only)
#
# Testa conectividade HTTP/HTTPS com o sistema legado hospitalar via proxy
# SOCKS5 do sidecar Tailscale (ou proxy customizado), sem realizar login e
# sem persistir resposta do sistema legado no repositório.
#
# Uso:
#   ./scripts/smoke-vpn-connectivity.sh
#
# Variáveis de ambiente:
#   SOURCE_SYSTEM_URL          Obrigatória. URL do sistema legado.
#   PLAYWRIGHT_PROXY_SERVER    Opcional. Proxy SOCKS5.
#                              Default: socks5h://tailscale-app:1055
#
# Exit codes:
#   0  - Conectividade OK (HTTP 2xx/3xx via proxy)
#   1  - Erro de uso (SOURCE_SYSTEM_URL não definida)
#   2  - Proxy não alcançável (DNS ou conexão recusada)
#   3  - Sistema legado não respondeu ou retornou erro HTTP
# =============================================================================

set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m' # No Color

echo_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
echo_warn()  { echo -e "${YELLOW}[WARN]${NC} $*"; }
echo_error() { echo -e "${RED}[ERROR]${NC} $*"; }

# ---------------------------------------------------------------------------
# 1. Validar variáveis obrigatórias
# ---------------------------------------------------------------------------
SOURCE_SYSTEM_URL="${SOURCE_SYSTEM_URL:-}"
if [ -z "$SOURCE_SYSTEM_URL" ]; then
    echo_error "SOURCE_SYSTEM_URL is not set."
    echo_error "Defina a URL do sistema legado hospitalar no .env ou exporte a variável."
    exit 1
fi

# ---------------------------------------------------------------------------
# 2. Determinar proxy
# ---------------------------------------------------------------------------
PROXY="${PLAYWRIGHT_PROXY_SERVER:-socks5h://tailscale-app:1055}"

echo_info "Target URL : ${SOURCE_SYSTEM_URL}"
echo_info "Proxy      : ${PROXY}"
echo ""

# ---------------------------------------------------------------------------
# 3. Testar conectividade via proxy
# ---------------------------------------------------------------------------
# Usa -k (insecure) pois o certificado é válido apenas na rede interna.
# Usa -o /dev/null para descartar o corpo da resposta.
# Usa -s para modo silencioso (sem progresso).
# Usa -w %{http_code} para capturar apenas o código HTTP.
echo_info "Testing HTTP connectivity via proxy..."
echo ""

# Desativa set -e para tratar exit code do curl manualmente
set +e
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    --proxy "$PROXY" \
    --connect-timeout 10 \
    --max-time 15 \
    -k "$SOURCE_SYSTEM_URL" 2>/dev/null)
CURL_EXIT=$?
set -e

echo ""

# ---------------------------------------------------------------------------
# 4. Interpretar resultado
# ---------------------------------------------------------------------------
case $CURL_EXIT in
    0)
        # curl completou a requisição — verificar código HTTP
        if [ -n "$HTTP_CODE" ] && [ "$HTTP_CODE" -ge 200 ] && [ "$HTTP_CODE" -lt 400 ]; then
            echo_info "Smoke PASSED — HTTP ${HTTP_CODE}"
            exit 0
        else
            echo_error "Smoke FAILED — HTTP ${HTTP_CODE:-<empty>} (expected 2xx/3xx)"
            exit 3
        fi
        ;;
    5|6)
        # Exit 5: Couldn't resolve proxy (curl exit code 5)
        # Exit 6: Couldn't resolve host (curl exit code 6)
        echo_error "Smoke FAILED — proxy DNS resolution failed for ${PROXY}"
        echo_error "Verifique se o sidecar tailscale-app está rodando e acessível neste hostname."
        exit 2
        ;;
    7)
        # Failed to connect to proxy
        echo_error "Smoke FAILED — proxy unreachable at ${PROXY}"
        echo_error "Verifique se o sidecar tailscale-app está rodando."
        echo_error "Comando de diagnóstico: docker compose ps tailscale-app"
        exit 2
        ;;
    28)
        # Timeout
        echo_error "Smoke FAILED — timeout after 15s connecting to ${SOURCE_SYSTEM_URL} via proxy"
        echo_error "Verifique se a subnet route está aprovada no admin console Tailscale."
        exit 3
        ;;
    *)
        # Outro erro
        echo_error "Smoke FAILED — curl exit code ${CURL_EXIT}"
        exit 3
        ;;
esac
