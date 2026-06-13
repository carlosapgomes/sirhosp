#!/usr/bin/env bash
#
# recover-historical-data.sh  [LEGACY]
#
# =============================================================================
# CANONICAL ENTRY POINT
#
# The official recovery command is:
#
#   python manage.py recover_historical_data --date DD/MM/AAAA
#
# This shell script is a LEGACY HELPER that predates the Django command. It
# remains available for operators with existing automation or documentation
# that references it directly. New workflows should use the Django command.
#
# The Django command supports:
# - Single date (--date DD/MM/AAAA) or inclusive range
# - Extractor selection (--extractor admissions --extractor deaths)
# - Dry-run planning (--dry-run), fail-fast (--fail-fast)
# - Direct Python service calls (no subprocess/management-command boundary)
# =============================================================================
#
# Re-executa os comandos de extração de altas, admissões, óbitos e censo
# oficial para um intervalo de datas, dia a dia.
#
# Uso:
#   ./scripts/recover-historical-data.sh              # intervalo padrão (01/05/2026 a 17/05/2026)
#   ./scripts/recover-historical-data.sh 01/04/2026   # data única
#   ./scripts/recover-historical-data.sh 01/04/2026 30/04/2026  # intervalo customizado
#
# Assume execução da raiz do projeto.
# Requer: docker compose, containers UP (compose.yml + compose.dev.yml).

set -euo pipefail

SCRIPT_NAME=$(basename "$0")
DOCKER_BASE=(docker compose -f compose.yml -f compose.dev.yml exec -T web)

# --- Utilitário: converte DD/MM/YYYY -> YYYY-MM-DD para date(1) ---
to_iso() {
    local d m y
    IFS=/ read -r d m y <<< "$1"
    # strip leading zeros to avoid octal interpretation by printf %d
    d=${d#0}
    m=${m#0}
    printf "%04d-%02d-%02d" "$y" "$m" "$d"
}

# --- Utilitário: converte YYYY-MM-DD -> DD/MM/YYYY ---
to_br() {
    local y m d
    IFS=- read -r y m d <<< "$1"
    # strip leading zeros to avoid octal interpretation by printf %d
    y=${y#0}
    m=${m#0}
    d=${d#0}
    printf "%02d/%02d/%04d" "$d" "$m" "$y"
}

# --- Parsing de argumentos ---
START_BR="${1:-01/05/2026}"
END_BR="${2:-17/05/2026}"

START_ISO=$(to_iso "$START_BR")
END_ISO=$(to_iso "$END_BR")

echo "=== $SCRIPT_NAME ==="
echo "Intervalo: $START_BR a $END_BR"
echo ""

# --- Validação simples ---
if ! date -d "$START_ISO" > /dev/null 2>&1; then
    echo "ERRO: data inicial inválida '$START_BR'"
    exit 1
fi
if ! date -d "$END_ISO" > /dev/null 2>&1; then
    echo "ERRO: data final inválida '$END_BR'"
    exit 1
fi

# --- Loop dia a dia ---
CURRENT_ISO="$START_ISO"
TOTAL=0
FAIL=0

while [[ "$(date -d "$CURRENT_ISO" +%Y%m%d)" -le "$(date -d "$END_ISO" +%Y%m%d)" ]]; do
    CUR_BR=$(to_br "$CURRENT_ISO")
    echo "----------------------------------------"
    echo ">>> Data: $CUR_BR"
    echo "----------------------------------------"

    # Discharges (altas)
    echo "  [1/4] extract_discharges --date $CUR_BR"
    if "${DOCKER_BASE[@]}" uv run --no-sync python manage.py extract_discharges --headless --date "$CUR_BR"; then
        echo "    ✓ discharges ok"
    else
        echo "    ✗ discharges FALHOU (continuando)"
        FAIL=$((FAIL + 1))
    fi

    # Admissions (internações)
    echo "  [2/4] extract_admissions --date $CUR_BR"
    if "${DOCKER_BASE[@]}" uv run --no-sync python manage.py extract_admissions --date "$CUR_BR"; then
        echo "    ✓ admissions ok"
    else
        echo "    ✗ admissions FALHOU (continuando)"
        FAIL=$((FAIL + 1))
    fi

    # Deaths (óbitos)
    echo "  [3/4] extract_deaths --date $CUR_BR"
    if "${DOCKER_BASE[@]}" uv run --no-sync python manage.py extract_deaths --date "$CUR_BR"; then
        echo "    ✓ deaths ok"
    else
        echo "    ✗ deaths FALHOU (continuando)"
        FAIL=$((FAIL + 1))
    fi

    # Official census
    echo "  [4/4] extract_official_census --date $CUR_BR"
    if "${DOCKER_BASE[@]}" uv run --no-sync python manage.py extract_official_census --date "$CUR_BR"; then
        echo "    ✓ official_census ok"
    else
        echo "    ✗ official_census FALHOU (continuando)"
        FAIL=$((FAIL + 1))
    fi

    echo ""
    TOTAL=$((TOTAL + 1))

    # Próximo dia
    CURRENT_ISO=$(date -d "$CURRENT_ISO + 1 day" +%Y-%m-%d)
done

# --- Resumo ---
echo "========================================"
echo "  Finalizado: $TOTAL dia(s) processado(s)"
if [[ $FAIL -gt 0 ]]; then
    echo "  Falhas:     $FAIL comando(s)"
    echo "  ⚠  Revise as saídas acima."
else
    echo "  Falhas:     0 — tudo ok ✓"
fi
echo "========================================"
