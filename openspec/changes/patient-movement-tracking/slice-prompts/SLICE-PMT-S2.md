# SLICE-PMT-S2: Serviço de upsert PatientMovement

## Handoff para executor LLM (contexto zero)

Você está recebendo este arquivo como única fonte de instrução. Antes de
codificar, leia **obrigatoriamente** nesta ordem:

1. `/projects/dev/sirhosp/AGENTS.md` — stack, comandos, política de testes
2. `/projects/dev/sirhosp/PROJECT_CONTEXT.md` — visão geral do sistema
3. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/proposal.md`
4. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/design.md`
5. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/tasks.md`
6. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/specs/census-snapshot-processing/spec.md`

**Implemente SOMENTE o Slice PMT-S2 e PARE.**

**Pré-requisito:** O Slice PMT-S1 (modelo `PatientMovement`) já deve estar
concluído e com migração aplicada no banco.

---

## Objetivo

Criar a função `upsert_patient_movements()` em `apps/census/services.py` que,
a partir do último `CensusSnapshot` com `bed_status=OCCUPIED`, faz upsert em
`PatientMovement` e recalcula `sequence`.

Adicionar a chamada desse serviço como etapa final do management command
`process_census_snapshot`.

---

## Escopo máximo de arquivos

Você pode alterar **no máximo 3 arquivos**:

| Arquivo | Ação |
| --- | --- |
| `apps/census/services.py` | Adicionar `upsert_patient_movements()` |
| `apps/census/management/commands/process_census_snapshot.py` | Adicionar chamada ao novo serviço após o processamento |
| `tests/unit/test_patient_movement_service.py` | Testes do serviço |

Se precisar alterar qualquer outro arquivo, **pare e reporte bloqueio**.

---

## Especificação da função `upsert_patient_movements()`

A função deve:

1. Buscar o `CensusSnapshot` mais recente (via `Max('captured_at')`).
2. Filtrar apenas `bed_status=BedStatus.OCCUPIED` com `prontuario` não vazio.
3. Para cada snapshot ocupado:
   a. Obter ou criar o `Patient` correspondente via `patient_source_key`.
   b. Parsear `data_movimentacao` usando `_parse_dt_int()` (já existe no
      mesmo arquivo `services.py` — **reuse, não duplique**).
   c. Converter a string parseada (`DD/MM/AAAA`) para `datetime.date`.
   d. Fazer `get_or_create` de `PatientMovement` com chave
      `(patient, movement_date, sector)`.
   e. Se criado: preencher `origin`, `bed`, `discharge_type`, `first_seen_at`,
      `last_seen_at`, e tentar vincular à `Admission` ativa do paciente.
   f. Se já existia: apenas atualizar `last_seen_at`.
4. Após processar todos os pacientes, recalcular `sequence` para cada paciente
   que teve movimentos tocados, ordenando por `movement_date` ASC e
   `first_seen_at` ASC.

### Assinatura sugerida

```python
def upsert_patient_movements() -> dict:
    """Upsert PatientMovement records from the latest census snapshot.

    Returns:
        dict with keys: movements_created, movements_updated,
        patients_processed, errors
    """
```

### Detalhes importantes

**Parse de data:** `_parse_dt_int()` retorna string `DD/MM/AAAA`. Use
`datetime.strptime(value, "%d/%m/%Y").date()` para converter a `date`. Se a
string for vazia ou inválida, pule o paciente (log como warning).

**Vinculação com Admission:** Busque a `Admission` ativa do paciente
(`discharge_date__isnull=True`) ordenada por `-admission_date`. Se houver uma,
associe ao `PatientMovement.admission`. Isso é best-effort — se não houver
admission ativa, deixe `admission=None`.

**Recálculo de sequence:** Função auxiliar `_recalc_sequences(patient)` que:

```python
def _recalc_sequences(patient: Patient) -> None:
    movements = PatientMovement.objects.filter(
        patient=patient,
    ).order_by("movement_date", "first_seen_at", "pk")
    for i, m in enumerate(movements):
        if m.sequence != i:
            m.sequence = i
            m.save(update_fields=["sequence"])
```

**Idempotência:** Se `upsert_patient_movements()` for chamada duas vezes com o
mesmo snapshot, não deve criar registros duplicados — apenas atualizar
`last_seen_at`.

---

## Hook no `process_census_snapshot`

No management command `process_census_snapshot.py`, adicione a chamada ao final
do método `handle()`, **após** o `process_census_snapshot()` existente:

```python
from apps.census.services import upsert_patient_movements

# ... (código existente) ...

# Após process_census_snapshot:
self.stdout.write("Upserting PatientMovement records...")
movement_result = upsert_patient_movements()
self.stdout.write(
    self.style.SUCCESS(
        f"Patient movements: {movement_result['movements_created']} created, "
        f"{movement_result['movements_updated']} updated, "
        f"{movement_result['patients_processed']} patients processed."
    )
)
```

Isso garante que o upsert de movimentos acontece no mesmo ciclo agendado do
censo, sem precisar de um comando separado ou alteração no systemd timer.

---

## Metodologia TDD

### 1. RED — Escreva testes que falham

Crie `tests/unit/test_patient_movement_service.py` com:

| Teste | O que verifica |
| --- | --- |
| `test_creates_movement_for_occupied_patient` | Cria um `CensusSnapshot` com `bed_status=OCCUPIED`, `prontuario="123"`, `data_movimentacao="25/05"`. Cria `Patient` correspondente. Chama `upsert_patient_movements()`. Verifica que 1 `PatientMovement` foi criado. |
| `test_skips_empty_beds` | Cria snapshot com `bed_status=EMPTY`. Chama upsert. Nenhum movimento criado. |
| `test_skips_occupied_without_prontuario` | Snapshot OCCUPIED mas `prontuario=""`. Nenhum movimento. |
| `test_does_not_duplicate_same_state` | Cria snapshot e chama upsert 2x. Apenas 1 movimento existe. `last_seen_at` é atualizado na segunda chamada. |
| `test_creates_new_movement_for_different_sector` | Paciente no setor A, depois snapshot mostra setor B. Dois movimentos criados. |
| `test_creates_new_movement_for_different_date` | Mesmo setor, `data_movimentacao` diferente. Dois movimentos. |
| `test_recalculates_sequence_after_upsert` | Cria 3 movimentos em ordem não-cronológica. Após upsert, `sequence` fica 0, 1, 2. |
| `test_links_to_active_admission` | Cria `Admission` ativa para o paciente. Upsert vincula `PatientMovement.admission`. |
| `test_no_active_admission_leaves_null` | Paciente sem `Admission` ativa → `admission=None`. |
| `test_returns_correct_metrics` | Verifica `movements_created`, `movements_updated`, `patients_processed` no dict de retorno. |

### 2. GREEN — Implemente o mínimo

- Adicione `upsert_patient_movements()` e `_recalc_sequences()` em
  `apps/census/services.py`.
- Adicione a chamada no `process_census_snapshot.py`.
- Resista à tentação de adicionar logs extras, flags ou features não
  especificadas (YAGNI).

### 3. REFACTOR

- Extraia parsing de data em helper se achar necessário, mas **não duplique**
  `_parse_dt_int`.
- Verifique nomes de variáveis e docstrings.
- Certifique-se de que `_recalc_sequences` usa `update_fields` para evitar
  sobrescrever `last_seen_at` acidentalmente.

---

## Gates de validação

Execute **nesta ordem** e **todos devem passar sem erro**:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
```

---

## Relatório obrigatório

Gere `/tmp/sirhosp-slice-PMT-S2-report.md` com:

```markdown
# Relatório SLICE-PMT-S2

## 1. Resumo

## 2. Checklist de aceite
- [ ] Testes RED escritos e falharam
- [ ] upsert_patient_movements() implementado
- [ ] Hook adicionado em process_census_snapshot
- [ ] Todos os testes passam
- [ ] Lint sem erros
- [ ] Nenhum arquivo fora do escopo alterado

## 3. Arquivos alterados

## 4. Fragmentos antes/depois
(Para services.py e process_census_snapshot.py)

## 5. Comandos executados e resultados

## 6. Riscos e pendências
- O parsing de data depende do formato DD/MM ou DD/MM/AAAA
- A vinculação com Admission é best-effort

## 7. Próximo passo sugerido
SLICE-PMT-S3: trajetória nos detalhes da internação
```

---

## Stop Rule

- **Não** implemente views, templates, ou páginas de setor.
- **Não** altere arquivos fora da lista de escopo.
- Ao terminar, **pare** e aguarde revisão humana.
