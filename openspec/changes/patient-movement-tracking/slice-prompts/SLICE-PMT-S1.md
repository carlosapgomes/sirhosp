# SLICE-PMT-S1: Modelo PatientMovement e migração

## Handoff para executor LLM (contexto zero)

Você está recebendo este arquivo como única fonte de instrução. Antes de
codificar, leia **obrigatoriamente** nesta ordem:

1. `/projects/dev/sirhosp/AGENTS.md` — stack, comandos, política de testes
2. `/projects/dev/sirhosp/PROJECT_CONTEXT.md` — visão geral do sistema
3. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/proposal.md`
4. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/design.md`
5. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/tasks.md`
6. `/projects/dev/sirhosp/openspec/changes/patient-movement-tracking/specs/patient-movement-model/spec.md`

**Implemente SOMENTE o Slice PMT-S1 e PARE.**

---

## Objetivo

Criar o modelo `PatientMovement` no app `census` com unique constraint, índices
e campo `sequence`, incluindo migração funcional.

Este slice é puramente de modelo — sem views, sem serviços, sem comandos.

---

## Escopo máximo de arquivos

Você pode alterar **no máximo 3 arquivos**:

| Arquivo | Ação |
| --- | --- |
| `apps/census/models.py` | Adicionar classe `PatientMovement` |
| `apps/census/migrations/0013_patientmovement.py` | Migration (gerada via `makemigrations`) |
| `tests/unit/test_patient_movement_model.py` | Testes do modelo |

Se precisar alterar qualquer outro arquivo, **pare e reporte bloqueio** no
relatório.

---

## Especificação do modelo

Copie o modelo exatamente como definido no `design.md` (seção "Modelo
PatientMovement"):

```python
class PatientMovement(models.Model):
    patient = models.ForeignKey(
        "patients.Patient", on_delete=models.CASCADE,
        related_name="movements",
    )
    admission = models.ForeignKey(
        "patients.Admission", on_delete=models.SET_NULL,
        null=True, blank=True, related_name="movements",
    )
    movement_date = models.DateField(
        help_text="Data da movimentação (do censo)",
    )
    sector = models.CharField(
        max_length=255, help_text="Setor atual",
    )
    bed = models.CharField(max_length=50, blank=True, default="")
    origin = models.CharField(
        max_length=100, blank=True, default="",
        help_text="Setor de origem (campo Origem do censo)",
    )
    discharge_type = models.CharField(
        max_length=50, blank=True, default="",
        help_text="Tipo de alta (vazio = ativo)",
    )
    sequence = models.IntegerField(
        default=0,
        help_text="Ordem cronológica dentro da admissão",
    )
    first_seen_at = models.DateTimeField(
        help_text="Primeiro snapshot que capturou este estado",
    )
    last_seen_at = models.DateTimeField(
        help_text="Último snapshot (atualizado a cada repetição)",
    )
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
        verbose_name = "Patient Movement"
        verbose_name_plural = "Patient Movements"

    def __str__(self) -> str:
        discharge = f" → {self.discharge_type}" if self.discharge_type else ""
        return (
            f"[{self.movement_date}] {self.patient} @ {self.sector}"
            f"{discharge}"
        )
```

---

## Metodologia TDD

### 1. RED — Escreva testes que falham

Crie `tests/unit/test_patient_movement_model.py` com os seguintes testes:

| Teste | O que verifica |
| --- | --- |
| `test_create_movement_minimal` | Cria `PatientMovement` com campos obrigatórios (`patient`, `movement_date`, `sector`). Verifica que `pk` não é None e `discharge_type` default é `""`. |
| `test_create_movement_all_fields` | Cria com todos os campos preenchidos e verifica persistência. |
| `test_unique_constraint` | Cria dois movimentos com mesmo `(patient, movement_date, sector)` → segundo deve levantar `IntegrityError`. Use `pytest.raises`. |
| `test_unique_allows_different_sector_same_day` | Mesmo paciente, mesma data, setores diferentes → ambos persistidos sem erro. |
| `test_unique_allows_different_date_same_sector` | Mesmo paciente, mesmo setor, datas diferentes → ambos persistidos sem erro. |
| `test_ordering_by_patient_and_sequence` | Cria 3 movimentos com sequences 2, 0, 1. `PatientMovement.objects.all()` deve retornar ordenado por patient ASC, sequence ASC. |
| `test_admission_nullable` | Cria movimento com `admission=None` → persiste sem erro. |
| `test_first_seen_at_and_last_seen_at` | Cria movimento → `first_seen_at` e `last_seen_at` são preenchidos automaticamente (via `auto_now_add` no `created_at`, mas como o design pede que sejam settados manualmente no serviço, use `timezone.now()` explícito no teste). |
| `test_str_representation` | `str(movement)` contém data, nome do paciente, setor. Quando `discharge_type` não vazio, aparece no `__str__`. |

Para criar fixtures de paciente, use:

```python
from apps.patients.models import Patient

patient = Patient.objects.create(
    source_system="tasy",
    patient_source_key="12345",
    name="TEST PATIENT",
)
```

### 2. GREEN — Implemente o mínimo

- Adicione a classe `PatientMovement` em `apps/census/models.py` conforme a
  especificação acima.
- Gere a migration: `uv run python manage.py makemigrations census --name patientmovement`
- Renomeie o arquivo gerado para `0013_patientmovement.py` se o número for
  diferente (verifique o último número em `apps/census/migrations/`).
- Adicione o import no `__init__.py` do app se necessário (Django geralmente
  não precisa, mas verifique).
- Rode `migrate` para aplicar.

**Atenção:** Se o número da migration não for 0013 porque há outras pendentes,
ajuste o nome do arquivo para o próximo número sequencial.

### 3. REFACTOR

- Verifique se nomes de campos e constraints batem com o design.
- Confirme que `ordering` e `indexes` estão corretos.
- Rode os testes novamente para garantir que ainda passam.

---

## Gates de validação

Execute **nesta ordem** e **todos devem passar sem erro**:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
```

Se houver erros de lint, corrija a causa raiz. **Não use `# noqa`** para
suprimir erros.

---

## Relatório obrigatório

Gere `/tmp/sirhosp-slice-PMT-S1-report.md` com **exatamente** estas seções:

```markdown
# Relatório SLICE-PMT-S1

## 1. Resumo
(2-3 frases sobre o que foi implementado)

## 2. Checklist de aceite
- [ ] Testes RED escritos e falharam antes da implementação
- [ ] Modelo PatientMovement adicionado em apps/census/models.py
- [ ] Migration gerada e aplicada
- [ ] Todos os testes passam (verde)
- [ ] Lint sem erros
- [ ] Nenhum arquivo fora do escopo foi alterado

## 3. Arquivos alterados
(Lista de paths exatos)

## 4. Fragmentos antes/depois
(Para models.py: cole o diff relevante — nova classe adicionada)

## 5. Comandos executados e resultados
(Cole a saída de cada comando de validação)

## 6. Riscos e pendências
- A migration depende do número sequencial correto
- Nenhum serviço ou view foi criado ainda (escopo dos próximos slices)

## 7. Próximo passo sugerido
SLICE-PMT-S2: serviço de upsert PatientMovement
```

---

## Stop Rule

- **Não** implemente serviços, views, comandos ou qualquer outra coisa.
- **Não** altere arquivos fora da lista de escopo.
- Ao terminar, **pare** e aguarde revisão humana.
