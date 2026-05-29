# Design: patient-movement-tracking

## Current State

- `CensusSnapshot` já possui os campos `data_movimentacao`, `tipo_alta` e
  `origem` (adicionados em change anterior).
- `process_census_snapshot` cria/atualiza `Patient` e enfileira `IngestionRun`
  de admissões e demografia.
- `Admission` armazena `ward` e `bed` atuais do paciente (sincronizados pelo
  `process_census_snapshot`).
- O dashboard mostra snapshot instantâneo de ocupação, sem dimensão temporal.
- Não existe mecanismo para rastrear o histórico de setores de um paciente
  durante a internação.
- A página de detalhes da internação (`admission_detail.html`) mostra dados
  estáticos e não inclui trajetória.

## Goals / Non-Goals

### Goals

1. Modelar `PatientMovement` com upsert por `(patient, movement_date, sector)`
   e campo `sequence` para ordenação.
2. Criar serviço que detecta mudanças efetivas de setor comparando com o
   registro anterior.
3. Exibir trajetória do paciente nos detalhes da internação.
4. Criar páginas de Ocupação e Indicadores sob o menu `Setores`.
5. Implementar com TDD em slices pequenos e independentes.

### Non-Goals

- Reprocessamento de snapshots históricos.
- API REST para consulta externa.
- Gráficos nas páginas de setores (MVP com cards e tabelas).
- Alteração do Playwright ou do parser XLSX.

## Decisions

### 1) Modelo `PatientMovement`

```python
class PatientMovement(models.Model):
    patient = models.ForeignKey("patients.Patient", on_delete=models.CASCADE,
                                related_name="movements")
    admission = models.ForeignKey("patients.Admission", on_delete=models.SET_NULL,
                                  null=True, blank=True, related_name="movements")
    movement_date = models.DateField(help_text="Data da movimentação (do censo)")
    sector = models.CharField(max_length=255, help_text="Setor atual")
    bed = models.CharField(max_length=50, blank=True, default="")
    origin = models.CharField(max_length=100, blank=True, default="",
                              help_text="Setor de origem (campo Origem do censo)")
    discharge_type = models.CharField(max_length=50, blank=True, default="",
                                      help_text="Tipo de alta (vazio = ativo)")
    sequence = models.IntegerField(default=0,
                                   help_text="Ordem cronológica dentro da admissão")
    first_seen_at = models.DateTimeField(help_text="Primeiro snapshot que capturou este estado")
    last_seen_at = models.DateTimeField(help_text="Último snapshot (atualizado a cada repetição)")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["patient", "movement_date", "sector"],
                name="uq_patient_movement_date_sector",
            ),
        ]
        ordering = ["patient", "sequence"]
        indexes = [
            models.Index(fields=["sector", "last_seen_at"]),
            models.Index(fields=["patient", "sequence"]),
            models.Index(fields=["discharge_type"]),
        ]
```

**Justificativa da unique key:** `(patient, movement_date, sector)` permite
que um paciente tenha múltiplos setores no mesmo dia (ex: PS → UTI → Enf) mas
evita duplicação do mesmo estado capturado em snapshots consecutivos.

### 2) Algoritmo de upsert (`upsert_patient_movements`)

Executado após `process_census_snapshot`, para cada paciente ocupado no último
snapshot:

```text
para cada paciente no último CensusSnapshot (bed_status=OCCUPIED):
    data = parse_data_movimentacao(snap.data_movimentacao)
    setor = snap.setor
    origem = snap.origem
    alta = snap.tipo_alta

    movement, created = PatientMovement.objects.get_or_create(
        patient=patient,
        movement_date=data,
        sector=setor,
        defaults={
            "origin": origem,
            "bed": snap.leito,
            "discharge_type": alta,
            "first_seen_at": now,
            "last_seen_at": now,
        }
    )

    if not created:
        # Já existe: só atualiza last_seen_at
        movement.last_seen_at = now
        movement.save(update_fields=["last_seen_at"])

    # Recalcula sequence para todos os movimentos deste paciente
    _recalc_sequences(patient)
```

**Parse de `data_movimentacao`:** usa `_parse_dt_int` (já existente em
`services.py`) que converte `DD/MM` → `DD/MM/AAAA` inferindo o ano.

**Recálculo de `sequence`:** após cada upsert, reordena todos os movimentos
do paciente por `movement_date` e `first_seen_at`, atribuindo `sequence`
sequencial. Movimentos com mesmo `movement_date` são ordenados por
`first_seen_at` (quem apareceu primeiro no dia vem antes). Se `first_seen_at`
também for igual (raro), usa `pk`.

### 3) Vinculação com `Admission`

O campo `admission` em `PatientMovement` é opcional (nullable). A vinculação
pode ser feita de duas formas:

- **Heurística automática:** ao criar um `PatientMovement` com `origem` vazio
  e `movement_date` próximo da `admission_date`, vincula à admissão ativa.
- **Manual/assíncrona:** um comando `link_movements_to_admissions` que varre
  `PatientMovement` sem `admission` e tenta vincular.

No MVP, a vinculação será via heurística automática no momento do upsert:
busca a `Admission` ativa (`discharge_date__isnull=True`) cuja
`admission_date` seja ≤ `movement_date`.

### 4) Página de detalhes da internação

Adicionar uma partial `_patient_trajectory.html` incluída em
`admission_detail.html` (ou equivalente). A partial recebe
`movements` (queryset de `PatientMovement` filtrado por paciente e período da
admissão) e renderiza:

- **Linha do tempo horizontal:** cards por setor com datas e setas de
  transição.
- **Tabela resumo:** setor, data de entrada, dias, destino/status.

Se não houver movimentos registrados, exibe mensagem informativa.

```text
📍 Trajetória
PS PED ── 1 dia ──▶ ENF PED ── 6 dias ──▶ (ativa)
20/05              21/05
```

### 5) Páginas do menu Setores

**Subpágina Ocupação (`/setores/ocupacao/`)**:

- Filtros: dropdown de setor (extraído do último snapshot) + seletor de período
  (`7d`, `30d`, `90d`).
- Cards de resumo: total de pacientes que passaram, ainda no setor, já saíram,
  permanência média.
- Tabela: nome, prontuário, data de entrada no setor, dias no setor,
  destino/status (setor seguinte ou tipo de alta).

Query principal:

```python
PatientMovement.objects.filter(
    sector=selected_sector,
    last_seen_at__gte=period_start,
).select_related("patient").order_by("movement_date")
```

**Subpágina Indicadores (`/setores/indicadores/`)**:

- Seletor de período global (`7d`, `30d`, `90d`, `180d`).
- 4 cards/métricas lado a lado (2x2 grid):

> **Permanência média por setor** | `AVG(diff movement_date) GROUP BY sector` com `LAG` window function |
> **Setores que mais recebem de X** | `COUNT(*) WHERE origin LIKE '%X%' GROUP BY sector ORDER BY COUNT DESC` — com dropdown para escolher setor de origem |
> **Pacientes >15 dias no mesmo setor** | `WHERE discharge_type='' AND last_seen_at - first_seen_at > 15 days` agrupado por setor |
> **Gargalos: entradas > saídas** | Comparar `COUNT` de `first_seen_at` no período vs `COUNT` de `discharge_type != ''` no período, por setor |

### 6) Sidebar

Adicionar ao sidebar (`base_sidebar.html`), abaixo de "Censo", um item
expansível "Setores" com sublinks:

```text
📊 Dashboard
🛏️ Censo
📍 Setores          ← NOVO (expansível)
   ├─ Ocupação
   └─ Indicadores
📈 Métricas de Ingestão
👥 Pacientes
```

### 7) TDD Strategy

**Slice PMT-S1 — Modelo e migração:**
- RED: teste de criação de `PatientMovement`, unique constraint,
  ordenação por sequence.
- GREEN: modelo + migration.
- REFACTOR: nomes, índices.

**Slice PMT-S2 — Serviço de upsert:**
- RED: teste de `upsert_patient_movements` com snapshot sintético.
  - Cria novo movimento.
  - Não duplica movimento idêntico (mesmo patient, data, setor).
  - Atualiza `last_seen_at` em repetição.
  - Recalcula `sequence` corretamente.
- GREEN: implementação do serviço + hook no `process_census_snapshot`.
- REFACTOR: extrair helpers.

**Slice PMT-S3 — Trajetória na internação:**
- RED: teste de view de detalhes da internação com movimentos no contexto.
  - Template inclui timeline quando há movimentos.
  - Template mostra mensagem quando não há movimentos.
  - Dias por setor são calculados corretamente.
- GREEN: partial `_patient_trajectory.html` + view atualizada.
- REFACTOR: estilos, acessibilidade.

**Slice PMT-S4 — Página de Ocupação:**
- RED: testes de view com filtros e contexto.
  - Filtro por setor e período.
  - Cards de resumo com totais corretos.
  - Tabela de pacientes ordenada.
- GREEN: view + template + sidebar update.
- REFACTOR: queries otimizadas.

**Slice PMT-S5 — Página de Indicadores:**
- RED: testes para cada um dos 4 cards de indicadores.
  - Permanência média por setor.
  - Setores que mais recebem de origem X.
  - Pacientes longa permanência.
  - Gargalos (entradas > saídas).
- GREEN: view + template + sidebar update.
- REFACTOR: extrair queries para métodos do modelo ou manager.

## Files Expected to Change

| Arquivo | Tipo |
| --- | --- |
| `apps/census/models.py` | Adicionar `PatientMovement` |
| `apps/census/migrations/0013_patientmovement.py` | Migration |
| `apps/census/services.py` | Adicionar `upsert_patient_movements` e helpers |
| `apps/census/management/commands/sync_patient_movements.py` | Comando standalone (opcional, ou hook em `process_census_snapshot`) |
| `apps/services_portal/views.py` | Views de ocupação, indicadores, trajetória |
| `apps/services_portal/urls.py` | Rotas `/setores/ocupacao/`, `/setores/indicadores/` |
| `apps/services_portal/templates/services_portal/sector_occupation.html` | Página de ocupação |
| `apps/services_portal/templates/services_portal/sector_indicators.html` | Página de indicadores |
| `apps/patients/templates/patients/_patient_trajectory.html` | Partial de trajetória |
| `apps/patients/templates/patients/admission_detail.html` | Incluir partial de trajetória |
| `apps/services_portal/templates/base_sidebar.html` | Menu Setores |
| `tests/unit/test_patient_movement_model.py` | Testes do modelo |
| `tests/unit/test_patient_movement_service.py` | Testes do serviço |
| `tests/unit/test_services_portal_sectors.py` | Testes das views |
| `tests/integration/test_patient_movement_command.py` | Testes de integração |

## Risks and Trade-Offs

- **Granularidade de `movement_date`:** sem hora, duas movimentações no mesmo
  dia são ordenadas por `first_seen_at`. Isso é aceitável para o caso de uso
  (dias por setor), mas pode inverter a ordem real de movimentos intra-dia.
- **Dependência de `tipo_alta`:** se o campo não for preenchido de forma
  confiável pelo sistema fonte, movimentos podem não ser fechados corretamente.
  O campo `discharge_type` é tratado como string opcional para acomodar
  variações futuras.
- **Acoplamento com `process_census_snapshot`:** o upsert pode ser um passo
  separado ou hook no comando existente. Prefere-se hook para garantir
  atomicidade do ciclo de censo, mas será avaliado durante implementação.
- **Volume de dados:** ~850 pacientes/snapshot × 4 snapshots/dia = 3400
  upserts/dia. Com unique constraint, a maioria será `last_seen_at` update
  (barato). Growth anual de ~50K registros, bem dentro da capacidade do
  PostgreSQL.
