#!/usr/bin/env bash
# =============================================================================
# SIRHOSP — Preflight de ativação do relatório estatístico diário
#                     (host-level, somente leitura, fail-closed)
#
# Checkpoint executado no host do hospital imediatamente ANTES do checkpoint
# humano de ativação de `sirhosp-daily-statistics.timer` (runbook em
# deploy/README.md, seção 5c). Ele não é autorização para ativar produção:
# comprova procedência imutável, fronteira de ativação futura e frescor
# agregado das cadências de saída, e termina sem alterar estado algum.
#
# Uso: daily-statistics-activation-preflight.sh <release-tag-exata>
#
# Verificações (todas somente leitura):
#
#   release              a tag existe, está publicada (não é draft) e a
#                        release é imutável;
#   asset_match          cada asset obrigatório da própria release é baixado
#                        e comparado byte a byte com a cópia instalada —
#                        este preflight e o scheduler em <hospital>/deploy/,
#                        além dos units de finalização e das cadências de
#                        saída em <systemd>/ (a comparação byte a byte dos
#                        units instalados é o que prova que os calendários
#                        systemd correspondem à release);
#   image_version        SIRHOSP_VERSION do .env é igual à tag exata. É a
#                        única prova disponível no host de que a imagem
#                        configurada no Compose pertence à release: a imagem
#                        não é baixada, iniciada nem inspecionada aqui;
#   scheduler_contract   valida o código executável do scheduler da release:
#                        os branches rotulados pelas variáveis cujo valor é
#                        `d1-recovery`/`hourly-discharges` devem atribuir
#                        `RUNNER_COMMAND` a
#                        `run_exit_reconciliation_runtime --mode d1|hourly`,
#                        o runtime canônico de quatro extratores (discharges,
#                        admissions, deaths, official_census) que sustenta o
#                        sucesso D-1. Comentários, dead code e texto solto
#                        nunca satisfazem o contrato;
#   activation_date      STATISTICS_ACTIVATION_DATE declarada de forma
#                        inequívoca e estritamente futura em America/Bahia;
#   daily_timer_state    o timer de estatísticas continua desabilitado e
#                        inativo (baseline pré-ativação);
#   upstream_timer_state os timers de altas intradiárias e de recuperação
#                        D-1 estão habilitados e ativos;
#   cadence_hourly_discharges / cadence_d1_recovery
#                        existem os marcadores agregados `mode=<modo>
#                        result=success` no journal, dentro das janelas de 2
#                        e 30 horas respectivamente.
#
# Nenhum `enable`, `start`, `restart` ou `stop` é executado; nenhum container
# Docker, comando Django, extrator, materialização, cliente de banco ou
# backfill é acionado; nenhum estado do host é alterado. Qualquer
# pré-condição ausente ou divergente falha fechado com motivo técnico
# enumerado.
#
# Saída: apenas linhas `[preflight] ...` com tag, nomes de check, estados,
# modos, janelas e motivos enumerados — é o artefato agregado que o operador
# anexa ao registro de mudança. O conteúdo do journal é usado somente como
# predicado interno: mensagens brutas, credenciais e identidade clínica nunca
# são impressas.
#
# Dependências explícitas do host: bash, curl, python3, cmp, systemctl,
# journalctl, date, grep, mktemp, rm.
# =============================================================================
set -euo pipefail
# Ordenação determinística (comparação lexicográfica de datas ISO-8601) e
# parsing estável de listas de assets.
export LC_ALL=C

# Defaults de produção. As quatro variáveis seguintes existem como ponto de
# injeção exclusivamente para os testes sintéticos do repositório (diretórios
# e endpoints controlados); em produção valem sempre os valores padrão.
HOSPITAL_DIR="${HOSPITAL_DIR:-/srv/apps/prisma}"
SYSTEMD_UNIT_DIR="${SYSTEMD_UNIT_DIR:-/etc/systemd/system}"
RELEASE_BASE_URL="${RELEASE_BASE_URL:-https://github.com/carlosapgomes/sirhosp/releases/download}"
RELEASE_API_URL="${RELEASE_API_URL:-https://api.github.com/repos/carlosapgomes/sirhosp/releases/tags}"

ENV_FILE="${HOSPITAL_DIR}/.env"
DEPLOY_DIR="${HOSPITAL_DIR}/deploy"

SCHEDULER_ASSET="exit-reconciliation-scheduler.sh"
PREFLIGHT_ASSET="daily-statistics-activation-preflight.sh"

DAILY_SERVICE="sirhosp-daily-statistics.service"
DAILY_TIMER="sirhosp-daily-statistics.timer"
HOURLY_SERVICE="sirhosp-discharges.service"
HOURLY_TIMER="sirhosp-discharges.timer"
D1_SERVICE="sirhosp-historical-recovery.service"
D1_TIMER="sirhosp-historical-recovery.timer"
STALE_SERVICE="sirhosp-stale-reconciliation.service"
STALE_TIMER="sirhosp-stale-reconciliation.timer"

# `asset|local-path` — bytes que devem coincidir com a release imutável.
FILE_ASSETS=(
    "${SCHEDULER_ASSET}|${DEPLOY_DIR}/${SCHEDULER_ASSET}"
    "${PREFLIGHT_ASSET}|${DEPLOY_DIR}/${PREFLIGHT_ASSET}"
    "${DAILY_SERVICE}|${SYSTEMD_UNIT_DIR}/${DAILY_SERVICE}"
    "${DAILY_TIMER}|${SYSTEMD_UNIT_DIR}/${DAILY_TIMER}"
    "${HOURLY_SERVICE}|${SYSTEMD_UNIT_DIR}/${HOURLY_SERVICE}"
    "${HOURLY_TIMER}|${SYSTEMD_UNIT_DIR}/${HOURLY_TIMER}"
    "${D1_SERVICE}|${SYSTEMD_UNIT_DIR}/${D1_SERVICE}"
    "${D1_TIMER}|${SYSTEMD_UNIT_DIR}/${D1_TIMER}"
    "${STALE_SERVICE}|${SYSTEMD_UNIT_DIR}/${STALE_SERVICE}"
    "${STALE_TIMER}|${SYSTEMD_UNIT_DIR}/${STALE_TIMER}"
)

REQUIRED_ASSETS=()
for file_asset_entry in "${FILE_ASSETS[@]}"; do
    REQUIRED_ASSETS+=("${file_asset_entry%%|*}")
done

# Contrato canônico do runtime de saída, como `modo:dispatch`. Cada branch de
# `case` rotulado pela variável `MODE_*` cujo valor é o modo deve atribuir
# `RUNNER_COMMAND` exatamente a esse dispatch. São dados de contrato
# comparados estruturalmente contra o asset da release (ver
# `check_scheduler_contract`), nunca comandos executados por este preflight.
D1_RUNTIME_DISPATCH="run_exit_reconciliation_runtime --mode d1"
HOURLY_RUNTIME_DISPATCH="run_exit_reconciliation_runtime --mode hourly"
CANONICAL_RUNTIME_BRANCHES=(
    "d1-recovery:${D1_RUNTIME_DISPATCH}"
    "hourly-discharges:${HOURLY_RUNTIME_DISPATCH}"
)

# Marcadores agregados emitidos pelo scheduler (nunca reproduzidos na saída).
HOURLY_MARKER="mode=hourly-discharges result=success"
D1_MARKER="mode=d1-recovery result=success"
HOURLY_WINDOW="-2 hours"
D1_WINDOW="-30 hours"

HOST_DEPENDENCIES=(bash curl python3 cmp systemctl journalctl date grep mktemp rm)

TAG=""
TMP_DIR=""
DOWNLOAD_DIR=""
RELEASE_JSON_FILE=""
RELEASE_VERIFIED=0
FAILURES=0
CHECKS=0
ENV_STATUS="missing"
ENV_VALUE=""

record() {
    local check="$1" status="$2"
    shift 2
    local detail
    CHECKS=$((CHECKS + 1))
    printf '[preflight] check=%s status=%s' "${check}" "${status}"
    for detail in "$@"; do
        printf ' %s' "${detail}"
    done
    printf '\n'
}

pass() {
    record "$1" PASS "${@:2}"
}

fail() {
    local check="$1" reason="$2"
    shift 2
    FAILURES=$((FAILURES + 1))
    record "${check}" FAIL "reason=${reason}" "$@"
}

usage() {
    cat >&2 <<'EOF'
Uso: daily-statistics-activation-preflight.sh <release-tag-exata>

Preflight somente leitura do fechamento estatístico diário: valida a tag
publicada e imutável, a procedência byte a byte dos assets instalados, a
fronteira de ativação futura, o baseline desabilitado do timer de estatísticas
e a evidência agregada recente das cadências de saída.

Nenhum estado do host é alterado e o preflight não autoriza ativação.
EOF
}

finish() {
    local code="$1"
    if [ "${code}" -eq 0 ]; then
        printf '[preflight] result=PASS tag=%s checks=%d\n' "${TAG}" "${CHECKS}"
    else
        printf '[preflight] result=FAIL tag=%s failures=%d\n' "${TAG}" "${FAILURES}"
    fi
    exit "${code}"
}

# Lê somente as duas chaves allowlisted do .env, sem `source` e sem expandir
# qualquer outro valor. Define ENV_STATUS (ok|unreadable|missing|duplicate|
# ambiguous) e ENV_VALUE.
read_env_value() {
    local key="$1" line
    local -a matched_lines=()
    ENV_STATUS="missing"
    ENV_VALUE=""
    if [ ! -f "${ENV_FILE}" ]; then
        ENV_STATUS="unreadable"
        return 0
    fi
    mapfile -t matched_lines < <(
        grep -E "^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=" "${ENV_FILE}" 2>/dev/null || true
    )
    if [ "${#matched_lines[@]}" -eq 0 ]; then
        return 0
    fi
    if [ "${#matched_lines[@]}" -gt 1 ]; then
        ENV_STATUS="duplicate"
        return 0
    fi
    line="${matched_lines[0]}"
    if [[ "${line}" != "${key}="* ]]; then
        ENV_STATUS="ambiguous"
        return 0
    fi
    ENV_VALUE="${line#"${key}="}"
    if [ -z "${ENV_VALUE}" ]; then
        ENV_STATUS="missing"
        return 0
    fi
    if [[ ! "${ENV_VALUE}" =~ ^[A-Za-z0-9][A-Za-z0-9._-]*$ ]]; then
        ENV_VALUE=""
        ENV_STATUS="ambiguous"
        return 0
    fi
    ENV_STATUS="ok"
    return 0
}

env_failure_reason() {
    case "${ENV_STATUS}" in
        unreadable) printf '%s' "env_file_unreadable" ;;
        missing) printf '%s' "env_value_missing" ;;
        duplicate) printf '%s' "env_value_duplicate" ;;
        *) printf '%s' "env_value_ambiguous" ;;
    esac
}

# Extrai somente os campos allowlisted do JSON da release. Imprime chaves
# técnicas (nunca o JSON bruto).
read_release_fields() {
    python3 - "${RELEASE_JSON_FILE}" "${TAG}" "${REQUIRED_ASSETS[@]}" <<'PY'
"""Campos allowlisted da release imutável consultada pela API."""
import json
import sys

path = sys.argv[1]
tag = sys.argv[2]
required = sys.argv[3:]

try:
    with open(path, encoding="utf-8") as handle:
        release = json.load(handle)
except (OSError, ValueError):
    raise SystemExit(2)

if not isinstance(release, dict):
    raise SystemExit(2)

published_names = {
    asset.get("name")
    for asset in release.get("assets", [])
    if isinstance(asset, dict)
}
missing_names = sorted(name for name in required if name not in published_names)

print("tag_match=1" if release.get("tag_name") == tag else "tag_match=0")
print("draft=1" if release.get("draft") is True else "draft=0")
print("immutable=1" if release.get("immutable") is True else "immutable=0")
print("published=1" if release.get("published_at") else "published=0")
print("assets_missing=" + ",".join(missing_names))
PY
}

release_field() {
    local fields="$1" key="$2" line
    while IFS= read -r line; do
        case "${line}" in
            "${key}="*) printf '%s\n' "${line#"${key}="}"; return 0 ;;
        esac
    done <<< "${fields}"
    return 1
}

check_dependencies() {
    local tool
    local missing=0
    for tool in "${HOST_DEPENDENCIES[@]}"; do
        if ! command -v "${tool}" >/dev/null 2>&1; then
            fail dependency missing_dependency "tool=${tool}"
            missing=1
        fi
    done
    if [ "${missing}" -eq 0 ]; then
        pass dependency "tools=${#HOST_DEPENDENCIES[@]}"
    fi
}

check_release() {
    local fields
    if ! curl -fsSL -H 'Accept: application/vnd.github+json' \
        -o "${RELEASE_JSON_FILE}" "${RELEASE_API_URL}/${TAG}" >/dev/null 2>&1; then
        fail release release_unavailable
        return 0
    fi
    if ! fields="$(read_release_fields)"; then
        fail release release_unavailable
        return 0
    fi
    if [ "$(release_field "${fields}" tag_match)" != "1" ]; then
        fail release release_tag_mismatch
        return 0
    fi
    if [ "$(release_field "${fields}" draft)" = "1" ]; then
        fail release release_is_draft
        return 0
    fi
    if [ "$(release_field "${fields}" immutable)" != "1" ]; then
        fail release release_not_immutable
        return 0
    fi
    if [ "$(release_field "${fields}" published)" != "1" ]; then
        fail release release_not_published
        return 0
    fi
    if [ -n "$(release_field "${fields}" assets_missing)" ]; then
        fail release release_asset_missing
        return 0
    fi
    pass release "tag=${TAG}"
    RELEASE_VERIFIED=1
}

check_assets() {
    if [ "${RELEASE_VERIFIED}" -ne 1 ]; then
        fail asset_match release_unverified "assets=${#FILE_ASSETS[@]}"
        return 0
    fi
    local entry asset local_path downloaded
    local mismatch=0
    for entry in "${FILE_ASSETS[@]}"; do
        asset="${entry%%|*}"
        local_path="${entry#*|}"
        downloaded="${DOWNLOAD_DIR}/${asset}"
        if ! curl -fsSL -o "${downloaded}" \
            "${RELEASE_BASE_URL}/${TAG}/${asset}" >/dev/null 2>&1; then
            fail asset_match release_asset_unavailable "asset=${asset}"
            mismatch=1
            continue
        fi
        if [ ! -f "${local_path}" ]; then
            fail asset_match local_asset_missing "asset=${asset}"
            mismatch=1
            continue
        fi
        if ! cmp -s "${downloaded}" "${local_path}"; then
            fail asset_match local_asset_mismatch "asset=${asset}"
            mismatch=1
        fi
    done
    if [ "${mismatch}" -eq 0 ]; then
        pass asset_match "assets=${#FILE_ASSETS[@]}"
    fi
}

# Valida o contrato executável do asset do scheduler sem executá-lo. O asset
# é lido como texto com os comentários removidos; só o `case` de topo (fora de
# qualquer função) conta como evidência: cada branch rotulado pela variável
# `MODE_*` cujo valor é o modo canônico deve, do rótulo até o `;;` que o
# encerra, conter exatamente a atribuição direta canônica de `RUNNER_COMMAND`.
# Comentários, função não chamada, dead code, dispatch indireto e qualquer
# outro statement executável no branch reprovam o contrato.
check_scheduler_contract() {
    local asset_file="${DOWNLOAD_DIR}/${SCHEDULER_ASSET}"
    if [ "${RELEASE_VERIFIED}" -ne 1 ]; then
        fail scheduler_contract release_unverified "asset=${SCHEDULER_ASSET}"
        return 0
    fi
    if [ ! -f "${asset_file}" ]; then
        fail scheduler_contract release_asset_unavailable "asset=${SCHEDULER_ASSET}"
        return 0
    fi
    local summary
    summary="$(python3 - "${asset_file}" "${CANONICAL_RUNTIME_BRANCHES[@]}" <<'PY'
"""Contrato executável do scheduler da release, sem executar o asset.

Valida somente o `case` de topo (não aninhado em função) que despacha o modo.
Cada branch rotulado pela variável `MODE_*` cujo valor é o modo canônico deve,
do rótulo até o `;;` que o encerra, conter exatamente uma atribuição direta de
`RUNNER_COMMAND` ao dispatch canônico. Comentários, texto canônico em função
não chamada/dead code, dispatch indireto e qualquer outro statement executável
no branch nunca satisfazem o contrato.
"""
import re
import sys

MODE_ASSIGNMENT = re.compile(
    r'^\s*(MODE_[A-Z0-9_]+)=["\']?([A-Za-z0-9._-]+)["\']?\s*$'
)
VARIABLE_LABEL = re.compile(r'^\s*"?\$\{(\w+)\}"?\)\s*$')
LITERAL_LABEL = re.compile(r'^\s*([A-Za-z0-9._-]+)\)\s*$')
RUNNER_ASSIGNMENT = re.compile(r'^\s*RUNNER_COMMAND=\((.*)\)\s*$')
CASE_OPEN = re.compile(r'^\s*case\b.*\bin\s*$')
ESAC_CLOSE = re.compile(r'^\s*esac\b')
BRANCH_END = re.compile(r'^\s*;;')


def without_comments(line):
    kept = []
    quote = ""
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = ""
            kept.append(char)
        elif char in ("'", '"'):
            quote = char
            kept.append(char)
        elif char == "#" and (index == 0 or line[index - 1] in " \t"):
            break
        else:
            kept.append(char)
    return "".join(kept)


def executable_lines(text):
    joined = []
    pending = ""
    for raw in text.splitlines():
        line = without_comments(raw).rstrip()
        if line.endswith("\\"):
            pending += line[:-1]
            continue
        joined.append(pending + line)
        pending = ""
    if pending:
        joined.append(pending)
    return [line.strip() for line in joined if line.strip()]


def read_lines(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return executable_lines(handle.read())
    except (OSError, UnicodeDecodeError):
        return None


def strip_expansions(line):
    """Drop ``${...}``/``$(...)`` so brace counting ignores expansions."""
    kept = []
    index = 0
    length = len(line)
    while index < length:
        char = line[index]
        if char == "$" and index + 1 < length and line[index + 1] in "{(":
            opener = line[index + 1]
            closer = "}" if opener == "{" else ")"
            depth = 0
            cursor = index + 1
            quote = ""
            while cursor < length:
                inner = line[cursor]
                if quote:
                    if inner == quote:
                        quote = ""
                elif inner in ("'", '"'):
                    quote = inner
                elif inner == opener:
                    depth += 1
                elif inner == closer:
                    depth -= 1
                    if depth == 0:
                        break
                cursor += 1
            index = cursor + 1
            continue
        kept.append(char)
        index += 1
    return "".join(kept)


def brace_delta(line):
    """Net ``{``/``}`` of a line, ignoring quotes and shell expansions."""
    depth = 0
    quote = ""
    for char in strip_expansions(line):
        if quote:
            if char == quote:
                quote = ""
        elif char in ("'", '"'):
            quote = char
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
    return depth


def branch_label(line):
    variable = VARIABLE_LABEL.match(line)
    if variable:
        return ("variable", variable.group(1))
    literal = LITERAL_LABEL.match(line)
    if literal:
        return ("literal", literal.group(1))
    return None


def top_level_case(lines):
    """Executable lines of the single top-level `case` body, else ``None``.

    A top-level statement is one at brace depth zero, so anything inside a
    function body (uncalled or not) is never part of the returned body.
    """
    depth = 0
    entries = []
    for line in lines:
        entries.append((depth, line))
        depth += brace_delta(line)

    openings = [
        index
        for index, (level, line) in enumerate(entries)
        if level == 0 and CASE_OPEN.match(line)
    ]
    if len(openings) != 1:
        return None

    nested = 0
    body = []
    for level, line in entries[openings[0] + 1:]:
        if level != 0:
            continue
        if CASE_OPEN.match(line):
            nested += 1
        if ESAC_CLOSE.match(line):
            if nested == 0:
                break
            nested -= 1
        body.append(line)
    return body


def case_branches(body):
    """Map each branch label of a `case` body to its label-to-``;;`` lines."""
    branches = []
    label = None
    statements = []
    for line in body:
        found = branch_label(line)
        if found is not None:
            label = found
            statements = []
            continue
        if BRANCH_END.match(line):
            if label is not None:
                branches.append((label, statements))
            label = None
            statements = []
            continue
        if label is not None:
            statements.append(line)
    return branches


def main():
    if len(sys.argv) < 2:
        print("status=unreadable")
        return 0
    lines = read_lines(sys.argv[1])
    if lines is None:
        print("status=unreadable")
        return 0

    requested = []
    for entry in sys.argv[2:]:
        mode, separator, dispatch = entry.partition(":")
        if not separator or not mode:
            print("status=unreadable")
            return 0
        requested.append((mode, dispatch.split()))
    if not requested:
        print("status=unreadable")
        return 0

    depth = 0
    mode_values = {}
    for line in lines:
        if depth == 0:
            match = MODE_ASSIGNMENT.match(line)
            if match:
                mode_values.setdefault(match.group(1), []).append(match.group(2))
        depth += brace_delta(line)

    body = top_level_case(lines)
    if body is None:
        print("status=missing mode=" + requested[0][0])
        return 0
    branches = case_branches(body)

    validated = []
    for mode, tokens in requested:
        variables = [
            name for name, values in mode_values.items() if values == [mode]
        ]
        if len(variables) != 1:
            print("status=missing mode=" + mode)
            return 0
        variable = variables[0]
        matched = [
            statements
            for label, statements in branches
            if label in (("variable", variable), ("literal", mode))
        ]
        if len(matched) != 1 or len(matched[0]) != 1:
            print("status=missing mode=" + mode)
            return 0
        assignment = RUNNER_ASSIGNMENT.match(matched[0][0])
        if not assignment or assignment.group(1).split() != tokens:
            print("status=missing mode=" + mode)
            return 0
        validated.append(mode)

    print("status=ok modes=" + ",".join(validated))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
PY
)" || summary="status=unreadable"

    if [[ "${summary}" == "status=ok modes="* ]]; then
        pass scheduler_contract "modes=${summary#status=ok modes=}"
    elif [[ "${summary}" == "status=missing mode="* ]]; then
        fail scheduler_contract scheduler_contract_missing \
            "mode=${summary#status=missing mode=}"
    else
        fail scheduler_contract scheduler_contract_unreadable \
            "asset=${SCHEDULER_ASSET}"
    fi
}

check_image_version() {
    read_env_value SIRHOSP_VERSION
    if [ "${ENV_STATUS}" != "ok" ]; then
        fail image_version "$(env_failure_reason)" "key=SIRHOSP_VERSION"
        return 0
    fi
    if [ "${ENV_VALUE}" != "${TAG}" ]; then
        fail image_version image_tag_mismatch
        return 0
    fi
    pass image_version "tag=${TAG}"
}

check_activation_date() {
    local value today normalized
    read_env_value STATISTICS_ACTIVATION_DATE
    if [ "${ENV_STATUS}" != "ok" ]; then
        fail activation_date "$(env_failure_reason)" "key=STATISTICS_ACTIVATION_DATE"
        return 0
    fi
    value="${ENV_VALUE}"
    if [[ ! "${value}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
        fail activation_date env_date_invalid
        return 0
    fi
    normalized="$(TZ=America/Bahia date -d "${value}" '+%F' 2>/dev/null || true)"
    if [ "${normalized}" != "${value}" ]; then
        fail activation_date env_date_invalid
        return 0
    fi
    today="$(TZ=America/Bahia date '+%F')"
    if [[ "${value}" > "${today}" ]]; then
        pass activation_date "window=strictly_future"
        return 0
    fi
    fail activation_date activation_date_not_future
    return 0
}

# Somente consultas read-only: qualquer outro verbo é recusado aqui.
systemctl_state() {
    local verb="$1" unit="$2"
    case "${verb}" in
        is-enabled|is-active) ;;
        *) return 1 ;;
    esac
    systemctl "${verb}" "${unit}" 2>/dev/null || true
}

check_daily_timer_state() {
    local enabled active
    enabled="$(systemctl_state is-enabled "${DAILY_TIMER}")"
    active="$(systemctl_state is-active "${DAILY_TIMER}")"
    if [ -z "${enabled}" ] || [ -z "${active}" ]; then
        fail daily_timer_state unit_state_unavailable "unit=${DAILY_TIMER}"
        return 0
    fi
    if [ "${enabled}" != "disabled" ]; then
        fail daily_timer_state timer_not_disabled "unit=${DAILY_TIMER}"
        return 0
    fi
    if [ "${active}" != "inactive" ]; then
        fail daily_timer_state timer_not_inactive "unit=${DAILY_TIMER}"
        return 0
    fi
    pass daily_timer_state "unit=${DAILY_TIMER}"
}

check_upstream_timers() {
    local unit enabled active
    for unit in "${HOURLY_TIMER}" "${D1_TIMER}"; do
        enabled="$(systemctl_state is-enabled "${unit}")"
        active="$(systemctl_state is-active "${unit}")"
        if [ -z "${enabled}" ] || [ -z "${active}" ]; then
            fail upstream_timer_state unit_state_unavailable "unit=${unit}"
            continue
        fi
        if [ "${enabled}" != "enabled" ]; then
            fail upstream_timer_state upstream_timer_not_enabled "unit=${unit}"
            continue
        fi
        if [ "${active}" != "active" ]; then
            fail upstream_timer_state upstream_timer_not_active "unit=${unit}"
            continue
        fi
        pass upstream_timer_state "unit=${unit}"
    done
}

# 0 = marcador presente, 1 = ausente, 2 = journal indisponível. O conteúdo é
# escrito em arquivo temporário e nunca ecoado.
journal_has_marker() {
    local unit="$1" since="$2" marker="$3" journal_file="$4"
    if ! journalctl -q --no-pager --since "${since}" -u "${unit}" -o cat \
        >"${journal_file}" 2>/dev/null; then
        return 2
    fi
    if grep -qF -- "${marker}" "${journal_file}"; then
        return 0
    fi
    return 1
}

check_cadence() {
    local check="$1" unit="$2" since="$3" marker="$4" window="$5"
    local outcome=0
    journal_has_marker "${unit}" "${since}" "${marker}" \
        "${DOWNLOAD_DIR}/${check}.journal" || outcome=$?
    case "${outcome}" in
        0) pass "${check}" "unit=${unit}" "window=${window}" ;;
        1) fail "${check}" cadence_stale "unit=${unit}" "window=${window}" ;;
        *) fail "${check}" journal_unavailable "unit=${unit}" "window=${window}" ;;
    esac
}

check_cadences() {
    check_cadence cadence_hourly_discharges "${HOURLY_SERVICE}" "${HOURLY_WINDOW}" \
        "${HOURLY_MARKER}" "2h"
    check_cadence cadence_d1_recovery "${D1_SERVICE}" "${D1_WINDOW}" \
        "${D1_MARKER}" "30h"
}

main() {
    if [ "$#" -ne 1 ]; then
        usage
        exit 2
    fi
    TAG="$1"
    if [[ ! "${TAG}" =~ ^[A-Za-z0-9]([A-Za-z0-9._-]*[A-Za-z0-9])?$ ]]; then
        usage
        exit 2
    fi

    TMP_DIR="$(mktemp -d)"
    DOWNLOAD_DIR="${TMP_DIR}"
    RELEASE_JSON_FILE="${TMP_DIR}/release.json"
    trap 'rm -rf -- "${TMP_DIR}"' EXIT

    check_dependencies
    if [ "${FAILURES}" -gt 0 ]; then
        finish 3
    fi

    check_release
    check_assets
    check_scheduler_contract
    check_image_version
    check_activation_date
    check_daily_timer_state
    check_upstream_timers
    check_cadences

    if [ "${FAILURES}" -gt 0 ]; then
        finish 1
    fi
    finish 0
}

main "$@"
