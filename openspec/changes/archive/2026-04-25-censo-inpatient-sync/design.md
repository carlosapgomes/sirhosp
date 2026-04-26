# Design: censo-inpatient-sync

## Context

O sistema fonte expõe o **Censo Diário de Pacientes** via iframe JSF/PrimeFaces. O MVP `busca_todos_pacientes_slim.py` (projeto `pontelo/`) já domina a navegação: abre dropdown de setores, itera um a um, seleciona, pesquisa, extrai pacientes com paginação.

O SIRHOSP hoje só ingere dados de pacientes cujo prontuário é informado manualmente. Este change automatiza a descoberta de pacientes e adiciona visibilidade de ocupação de leitos.

## Design Goals

1. Reaproveitar o MVP de scraping com adaptação mínima ao padrão sirhosp (subprocess).
2. Armazenar cada execução do censo como snapshot histórico.
3. Classificar automaticamente o status de cada leito.
4. Para cada paciente descoberto: criar `Patient`, enfileirar captura de admissions, e automaticamente disparar extração de evoluções da admissão mais recente.
5. Oferecer ferramenta de merge manual para duplicatas de registro.
6. Expor página de visualização de leitos.

## Architecture Overview

```text
┌─────────────────────────────────────────────────────────────┐
│ systemd timer (3x/day)                                      │
│   │                                                         │
│   ▼                                                         │
│ manage.py extract_census                                    │
│   │                                                         │
│   ├──▶ subprocess: automation/.../extract_census.py         │
│   │      └──▶ Playwright → census CSV/JSON                  │
│   │                                                         │
│   ├──▶ CensusParser: classifica leitos, normaliza dados     │
│   │                                                         │
│   └──▶ CensusSnapshot.objects.bulk_create()                 │
│                                                              │
│ manage.py process_census_snapshot                           │
│   │                                                         │
│   ├──▶ Lê CensusSnapshot do último run                      │
│   ├──▶ Para cada prontuário ocupado:                        │
│   │     ├── Patient.objects.get_or_create()                 │
│   │     ├── Atualiza nome se diferente                      │
│   │     └── IngestionRun.objects.create(                    │
│   │           intent="admissions_only",                     │
│   │           status="queued"                               │
│   │         )                                               │
│   │                                                         │
│   └──▶ Opcional: dispara process_ingestion_runs             │
│                                                         │
│ Worker: process_ingestion_runs (modificado)                 │
│   │                                                         │
│   ├──▶ _process_admissions_only()                           │
│   │     ├──▶ Captura admissions snapshot                    │
│   │     ├──▶ Upsert admissions                              │
│   │     ├──▶ Detecta admissão mais recente                  │
│   │     └──▶ Enfileira full_sync para essa admissão         │
│   │                                                         │
│   └──▶ _process_full_sync() (existente)                     │
│         └──▶ Extrai evoluções para a admissão               │
└─────────────────────────────────────────────────────────────┘
```

## Data Model

### `CensusSnapshot` (app `census`)

```python
class BedStatus(models.TextChoices):
    OCCUPIED = "occupied", "Ocupado"
    EMPTY = "empty", "Vago"
    MAINTENANCE = "maintenance", "Em Manutenção"
    RESERVED = "reserved", "Reservado"
    ISOLATION = "isolation", "Isolamento"

class CensusSnapshot(models.Model):
    captured_at = models.DateTimeField()
    ingestion_run = models.ForeignKey(IngestionRun, null=True, ...)

    setor = models.CharField(max_length=255)
    leito = models.CharField(max_length=50)
    prontuario = models.CharField(max_length=255, blank=True, default="")
    nome = models.CharField(max_length=512, blank=True, default="")
    especialidade = models.CharField(max_length=100, blank=True, default="")
    bed_status = models.CharField(max_length=20, choices=BedStatus.choices)

    class Meta:
        indexes = [
            models.Index(fields=["captured_at"]),
            models.Index(fields=["setor"]),
            models.Index(fields=["prontuario"]),
        ]
```

**Nota**: `prontuario` pode ser vazio (leito não ocupado). `nome` contém o texto bruto do censo (nome do paciente ou termo como "DESOCUPADO", "RESERVA INTERNA", "LIMPEZA", "ISOLAMENTO MÉDICO").

### Classificação de `bed_status`

| Padrão no campo `nome`                                                                                     | `bed_status`                                   |
| ---------------------------------------------------------------------------------------------------------- | ---------------------------------------------- |
| Prontuário numérico presente                                                                               | `occupied`                                     |
| `DESOCUPADO`, `VAZIO`, `vazio`                                                                             | `empty`                                        |
| `LIMPEZA`, `limpeza`                                                                                       | `maintenance`                                  |
| `RESERVA INTERNA`, `RESERVA CIRÚRGICA`, `RESERVA REGULAÇÃO`, `RESERVA HEMODINÂMICA`, `RESERVA AMBULATORIO` | `reserved`                                     |
| `ISOLAMENTO MÉDICO`, `ISOLAMENTO SOCIAL`, `ISOLAMENTO`                                                     | `isolation`                                    |
| `IGNORADO`, `PACIENTE IGNORADO`                                                                            | `occupied` (tem prontuário)                    |
| Nome de pessoa sem prontuário (ex.: centro cirúrgico)                                                      | `occupied` se tem prontuário, `empty` se vazio |

**Regra de ouro**: `prontuario` não-vazio e numérico → `occupied`. Se `prontuario` vazio → classifica por `nome`.

## Script de Extração

O script `extract_census.py` será copiado/adaptado de `busca_todos_pacientes_slim.py` para:

```text
automation/source_system/current_inpatients/extract_census.py
```

**Adaptações necessárias**:

1. Importar `source_system` compartilhado de `automation/source_system/medical_evolution/source_system.py` (login, helpers)
2. Usar `pathlib.Path` para diretórios de saída relativos ao projeto
3. Parâmetros via CLI: `--headless`, `--output-dir`, `--max-setores`, `--timeout`
4. Output: CSV + JSON com timestamp no nome (formato existente mantido)

**Contrato de saída**:

CSV com colunas: `setor`, `qrt_leito`, `prontuario`, `nome`, `esp`

## Fluxo de Processamento do Censo

### Passo 1: Extração (`extract_census`)

```text
manage.py extract_census [--headless] [--max-setores N]
  → executa subprocess: extract_census.py
  → parse do CSV gerado
  → classifica bed_status
  → bulk_create CensusSnapshot
  → registra IngestionRun com intent="census_extraction"
```

### Passo 2: Processamento (`process_census_snapshot`)

```text
manage.py process_census_snapshot [--run-id N]
  → lê CensusSnapshot do último run (ou run específico)
  → filtra apenas bed_status="occupied"
  → deduplica por prontuario (pega última ocorrência no run)
  → para cada prontuario:
      • get_or_create Patient(name=nome, patient_source_key=prontuario)
      • se já existia e nome mudou → atualiza nome
      • cria IngestionRun(intent="admissions_only", status="queued")
```

**Por que `admissions_only` e não `full_sync` direto?** Porque o censo não informa datas de admissão. Precisamos primeiro capturar as admissões do paciente para depois saber qual é a mais recente e extrair suas evoluções.

### Passo 3: Worker auto-enfileira full_sync

Modificação no `_process_admissions_only()` do worker (`process_ingestion_runs`):

```python
def _process_admissions_only(self, run, ...):
    # ... existing admissions capture logic ...

    # NEW: auto-enqueue full_sync for most recent admission
    latest = Admission.objects.filter(patient=patient).order_by("-admission_date").first()
    if latest:
        IngestionRun.objects.create(
            status="queued",
            intent="full_sync",
            parameters_json={
                "patient_record": patient.patient_source_key,
                "admission_id": str(latest.id),
                "admission_source_key": latest.source_admission_key,
                "start_date": latest.admission_date.strftime("%Y-%m-%d"),
                "end_date": (latest.discharge_date or timezone.now()).strftime("%Y-%m-%d"),
                "intent": "full_sync",
            },
        )
```

## Página de Leitos (`/beds/`)

Template com tabela agrupada por setor:

| Setor               | Ocupados | Vagas | Reservas | Manutenção | Isolamento | Total |
| ------------------- | -------- | ----- | -------- | ---------- | ---------- | ----- |
| UTI GERAL ADULTO 1  | 18       | 0     | 1        | 0          | 0          | 20    |
| INTERMEDIARIO ALA C | 28       | 1     | 2        | 0          | 0          | 35    |
| ...                 |          |       |          |            |            |       |

Ao clicar num setor, expande para mostrar leitos individuais com status e nome do paciente (se ocupado).

Query: agregação do `CensusSnapshot` mais recente (`captured_at = MAX(captured_at)`), agrupado por setor e bed_status.

## Merge de Pacientes

Função no `apps/patients/services.py`:

```python
def merge_patients(*, keep: Patient, merge: Patient, run: IngestionRun | None = None) -> dict:
    """Merge 'merge' patient into 'keep' patient.

    - Re-points all Admissions from merge to keep
    - Re-points all ClinicalEvents from merge to keep
    - Records identifier history entries for traceability
    - Deletes the 'merge' patient
    """
```

Ação admin: `@admin.action(description="Merge selected patients")` no `PatientAdmin`.

## Riscos e Mitigações

### Risco: script de scraping quebrar por mudança de UI

Mitigação: mesmo padrão do `path2.py` — modo laboratório isolado, debug screenshots, timeouts generosos.

### Risco: volume de `admissions_only` sobrecarregar o sistema fonte

Mitigação: o worker já processa sequencialmente com throttling natural (3x/dia, ~500 pacientes/dia = ~170 pacientes por execução = ~30 min). Limite de concorrência (3 workers max) já definido.

### Risco: duplicatas de registro (troca de prontuário)

Mitigação: merge manual via admin. Detecção automática adiada para change futuro com dados demográficos.

### Risco: `admissions_only` para paciente que já tem admissions

Mitigação: `upsert_admission_snapshot` já é idempotente (merge por período + chave). O custo é apenas o Playwright round-trip.

## Validation Strategy

- **Unit tests**: classificação de bed_status, parser de CSV, `process_census_snapshot`, `merge_patients`
- **Integration tests**: `extract_census` command com fixture sintética, worker auto-enfileiramento
- **Gates**: `check`, `unit`, `lint`, `typecheck` em container
