# Design: extract-discharges

## Context

O sistema fonte expõe a página **"Altas do Dia"** como um ícone no dashboard
principal (classe CSS `.silk-new-internacao-altas-do-dia`). Ao clicar, abre
um iframe com a lista de pacientes que receberam alta na data atual. O botão
"Visualizar Impressão" gera um PDF que contém a tabela completa de pacientes.

O script `pontelo/busca-altas-hoje.py` já domina esse fluxo: login → clique no
ícone → Visualizar Impressão → download do PDF → extração com PyMuPDF (análise
por bandas de coordenadas X/Y, pois o PDF é landscape rotacionado 90°).

O SIRHOSP já tem o campo `Admission.discharge_date` e a query `altas_24h` no
dashboard, mas o campo nunca é populado de forma sistemática.

## Design Goals

1. Reaproveitar o script `busca-altas-hoje.py` com adaptação mínima ao padrão SIRHOSP.
2. Usar o bridge module `automation/source_system/source_system.py` (sem dependências do `pontelo/`).
3. Ser idempotente: rodar 3x/dia sem duplicar dados.
4. Ser seguro: não criar `Patient` se não existir; pular admissions já com `discharge_date`.
5. Match de admissão por `data_internacao` (extraída do PDF), com fallback para a mais recente.

## Architecture Overview

````text
┌──────────────────────────────────────────────────────────────┐
│ systemd timer: 11:00, 19:00, 23:55                           │
│   │                                                          │
│   ▼                                                          │
│ deploy/discharges-scheduler.sh                               │
│   └─▶ docker compose exec web uv run python manage.py        │
│        extract_discharges                                    │
│           │                                                  │
│           ├─▶ IngestionRun(intent="discharge_extraction")    │
│           │                                                  │
│           ├─▶ subprocess: extract_discharges.py              │
│           │     ├─ Playwright → login                        │
│           │     ├─ Clica ícone Altas do Dia                  │
│           │     │  (seletor: .silk-new-internacao-altas-do-dia) │
│           │     ├─ Visualizar Impressão                      │
│           │     ├─ Download PDF autenticado                  │
│           │     ├─ PyMuPDF → parse tabela                    │
│           │     └─ Output: JSON { pacientes: [...] }         │
│           │                                                  │
│           └─▶ DischargeService.process_discharges()          │
│                 │                                            │
│                 Para cada paciente:                          │
│                 ├─ Patient.objects.filter(                   │
│                 │     patient_source_key=prontuario           │
│                 │   ).first()                                │
│                 ├─ Se None → SKIP (patient_not_found++)     │
│                 ├─ Busca Admission por data_internacao       │
│                 │   (admission_date__date == data_int)       │
│                 ├─ Fallback: mais recente sem discharge_date │
│                 ├─ Se None → SKIP (admission_not_found++)   │
│                 ├─ Se já tem discharge_date → SKIP          │
│                 │   (already_discharged++)                   │
│                 └─ Seta discharge_date = timezone.now()     │
│                    (discharge_set++)                         │
│                                                              │
│ Registra métricas no IngestionRun                            │
└──────────────────────────────────────────────────────────────┘
````

## Data Flow

### Entrada: JSON do script Playwright

```json
{
  "data": "2026-04-27",
  "total": 12,
  "pacientes": [
    {
      "prontuario": "14160147",
      "nome": "JOSE AUGUSTO MERCES",
      "leito": "UG01A",
      "especialidade": "NEF",
      "data_internacao": "15/04/2026"
    }
  ]
}
```

### Processamento: `DischargeService.process_discharges()`

```python
def process_discharges(patients: list[dict]) -> dict:
    """
    Returns:
        {
            "total_pdf": 12,           # total de pacientes no PDF
            "patient_not_found": 2,    # prontuário não está no SIRHOSP
            "admission_not_found": 1,  # paciente existe mas admissão não
            "already_discharged": 3,   # admissão já tinha discharge_date
            "discharge_set": 6,        # altas efetivamente registradas
        }
    """
```

Match de admissão (em ordem de prioridade):

1. **Match exato por `data_internacao`**: `Admission.objects.filter(patient=patient, admission_date__date=data_internacao.date(), discharge_date__isnull=True).first()`
2. **Fallback**: `Admission.objects.filter(patient=patient, discharge_date__isnull=True).order_by("-admission_date").first()`
3. Se nenhum match → `admission_not_found`

### `discharge_date`: usar `timezone.now()`

A página de altas **sempre** filtra pela data atual. O PDF não contém uma coluna
explícita de "data da alta" por paciente — apenas a lista de quem saiu "hoje".
Portanto, `discharge_date` é sempre a data/hora da execução.

## Script Adaptation

### O que muda do `busca-altas-hoje.py` original

| Elemento | Original (`pontelo/`) | Adaptado (SIRHOSP) |
| --- | --- | --- |
| Módulo `source_system` | `from source_system import ...` (com `config`, `processa_evolucoes_txt`) | `from source_system import aguardar_pagina_estavel, fechar_dialogos_iniciais` (bridge module) |
| Seletor do ícone | `page.locator('[id="_icon_img_20352"]')` | `page.locator('.silk-new-internacao-altas-do-dia')` |
| Variáveis de ambiente | `load_dotenv()` + `required_env()` | Lidas pelo management command e passadas via CLI args |
| CLI | `--headless` apenas | `--headless`, `--output-dir`, `--source-url`, `--username`, `--password` |
| Output | `downloads/altas-hoje-<ts>.json` | `downloads/discharges-<ts>.json` (via `--output-dir`) |

### O que NÃO muda

- Lógica de extração do PDF (PyMuPDF + bandas X/Y)
- Funções `extract_patients_from_pdf()`, `_extract_patients_by_x_bands()`, `_parse_patient_band()`
- Regex de parsing (`_RE_PRONTUARIO`, `_RE_DATA_CURTA`, etc.)
- Função `capturar_altas_hoje()` (assinatura ajustada para receber credenciais como parâmetro)

### Estrutura do script adaptado

```text
automation/source_system/discharges/
├── __init__.py
└── extract_discharges.py
    ├── Constantes (ALTAS_IFRAME_NAME, seletores)
    ├── Helpers (wait_visible, safe_click, get_altas_frame_locator, etc.)
    ├── Extração do PDF (extract_patients_from_pdf + funções de banda)
    ├── API pública (capturar_altas_hoje)
    └── CLI (main + parse_args)
```

## App `discharges`

### `apps/discharges/apps.py`

```python
class DischargesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.discharges"
    verbose_name = "Discharges"
```

### `apps/discharges/services.py`

Função pura `process_discharges(patients: list[dict]) -> dict`. Sem dependência
de modelos além de `Patient` e `Admission`. Sem acesso a request/response.

### `apps/discharges/management/commands/extract_discharges.py`

Mesmo padrão do `extract_census`:

1. Cria `IngestionRun(intent="discharge_extraction", status="running")`
2. Executa subprocess com timeout de 10 minutos
3. Lê JSON de saída
4. Chama `process_discharges()`
5. Registra `IngestionRunStageMetric` para extração e processamento
6. Finaliza run como `succeeded` ou `failed`

### Sem modelos

O app `discharges` **não cria modelos** nesta fase. Toda a persistência é feita
nos modelos existentes (`Admission.discharge_date`). Se no futuro houver
necessidade de auditoria ou rastreabilidade adicional, um modelo pode ser
adicionado.

## Systemd Scheduling

### Timer: `sirhosp-discharges.timer`

```ini
[Timer]
OnCalendar=*-*-* 11:00:00
OnCalendar=*-*-* 19:00:00
OnCalendar=*-*-* 23:55:00
RandomizedDelaySec=120
Persistent=true
```

Horários escolhidos:

- **11:00** — primeiras altas do dia (geralmente após 9h-10h)
- **19:00** — cobre altas da tarde
- **23:55** — captura o restante, rente à virada do dia

### Service: `sirhosp-discharges.service`

```ini
[Service]
Type=oneshot
WorkingDirectory=/opt/sirhosp
ExecStart=/opt/sirhosp/deploy/discharges-scheduler.sh
TimeoutStartSec=600
```

Timeout de 10 minutos (suficiente para login + download PDF + parse).

### Script: `deploy/discharges-scheduler.sh`

```bash
#!/usr/bin/env bash
set -euo pipefail
PROJECT_DIR="/opt/sirhosp"
COMPOSE_FILES=(-f compose.yml -f compose.prod.yml)

cd "$PROJECT_DIR"
docker compose "${COMPOSE_FILES[@]}" exec -T web \
    uv run --no-sync python manage.py extract_discharges
```

## Idempotência

O sistema pode rodar 3x/dia sem risco:

1. Se a admissão já tem `discharge_date` → conta como `already_discharged`, não altera nada
2. Se o paciente não está no SIRHOSP → skip, não cria registro
3. Se a admissão não é encontrada → skip, registra warning
4. O `discharge_date` é sempre setado para `timezone.now()`, então mesmo
   que seja sobrescrito, o valor é o mesmo (data de hoje)

## Riscos e Mitigações

### Risco: ícone de Altas do Dia mudar de classe CSS

**Mitigação**: seletor por classe CSS (`.silk-new-internacao-altas-do-dia`) é
mais estável que ID gerado por JSF. Se falhar, o modo debug salva screenshot
e HTML para diagnóstico.

### Risco: PDF não gerado (sistema fonte lento)

**Mitigação**: timeout generoso (2 min para Visualizar Impressão). Falha
registrada no `IngestionRun` com `failure_reason`.

### Risco: paciente teve alta mas `data_internacao` não bate com nenhuma admission

**Mitigação**: fallback para a admission mais recente sem `discharge_date`.
Se ainda assim não encontrar, registra `admission_not_found` e o operador
pode investigar.

### Risco: execução às 23:55 captura altas que "viram" o dia

**Mitigação**: `discharge_date = timezone.now()` usa o horário exato da
execução. Uma alta capturada às 23:55 terá `discharge_date` do dia 27,
não do dia 28. Correto, pois a alta ocorreu no dia 27.

## Validation Strategy

- **Unit tests**: `process_discharges()` com pacientes encontrados, não encontrados,
  admissions com/sem match, já com `discharge_date`
- **Integration tests**: management command com fixture sintética (JSON mock),
  verificação de `IngestionRun` e métricas
- **Gates**: `check`, `unit`, `lint`, `typecheck` em container
