# SLICE-S1: TIME_ZONE + Modelo DailyDischargeCount

## Handoff / Contexto de Entrada

**Change**: `discharge-daily-tracking` — rastreamento diário de altas
hospitalares.

**O que já existe**:

- App `apps/discharges/` com `services.py` (`process_discharges`),
  `apps.py`, `management/commands/extract_discharges.py`
- App **não tem `models.py` ainda** (o design original não previa modelos)
- `Admission.discharge_date` (DateTimeField) já é populado pelo
  `extract_discharges` via `timezone.now()`
- `config/settings.py` com `TIME_ZONE = "America/Sao_Paulo"`

**O que você vai construir neste slice**:

1. Alterar `TIME_ZONE` para `"America/Bahia"` (1 linha)
2. Criar modelo `DailyDischargeCount` no app `discharges`
3. Gerar migration

**Próximo slice (S2)**: Criará o management command que popula essa tabela.

## Arquivos que você vai tocar (limite: 3)

| Arquivo | Ação |
| --- | --- |
| `config/settings.py` | Alterar 1 linha: `TIME_ZONE` |
| `apps/discharges/models.py` | **Criar** — modelo `DailyDischargeCount` |
| Migration (auto) | Gerada por `makemigrations` |

**NÃO toque** em: `services.py`, `extract_discharges.py`, views, templates,
urls, tests de outros apps.

## TDD Workflow (RED → GREEN → REFACTOR)

### RED: Escreva o teste primeiro

Crie `tests/unit/test_daily_discharge_model.py`:

```python
import pytest
from apps.discharges.models import DailyDischargeCount
from datetime import date


@pytest.mark.django_db
class TestDailyDischargeCountModel:
    def test_create_daily_count(self):
        entry = DailyDischargeCount.objects.create(
            date=date(2026, 4, 28),
            count=5,
        )
        assert entry.date == date(2026, 4, 28)
        assert entry.count == 5
        assert entry.created_at is not None
        assert entry.updated_at is not None

    def test_date_is_unique(self):
        DailyDischargeCount.objects.create(date=date(2026, 4, 28), count=5)
        with pytest.raises(Exception):
            DailyDischargeCount.objects.create(date=date(2026, 4, 28), count=10)

    def test_default_count_is_zero(self):
        entry = DailyDischargeCount.objects.create(date=date(2026, 4, 28))
        assert entry.count == 0
```

Rode e confirme que **falha** (modelo não existe):

```bash
uv run pytest tests/unit/test_daily_discharge_model.py -q
```

### GREEN: Implementação mínima

1. Altere `TIME_ZONE` em `config/settings.py`:

   ```python
   TIME_ZONE = "America/Bahia"
   ```

2. Crie `apps/discharges/models.py`:

   ```python
   from django.db import models


   class DailyDischargeCount(models.Model):
       date = models.DateField(unique=True)
       count = models.IntegerField(default=0)
       created_at = models.DateTimeField(auto_now_add=True)
       updated_at = models.DateTimeField(auto_now=True)

       class Meta:
           ordering = ["-date"]

       def __str__(self) -> str:
           return f"{self.date}: {self.count} altas"
   ```

3. Gere a migration:

   ```bash
   uv run python manage.py makemigrations discharges
   ```

4. Rode os testes e confirme **verde**:

   ```bash
   uv run pytest tests/unit/test_daily_discharge_model.py -q
   ```

### REFACTOR

- Verifique se o modelo segue o padrão dos modelos existentes (`Patient`,
  `Admission`): `__str__`, `Meta.ordering`, docstring
- Confirme que a migration está nomeada de forma clara

## Critérios de Sucesso (Auto-Avaliação Obrigatória)

- [ ] `TIME_ZONE = "America/Bahia"` em `config/settings.py`
- [ ] `DailyDischargeCount` criado com campos: `date` (unique), `count`
  (default 0), `created_at`, `updated_at`
- [ ] Migration gerada e aplicável (`makemigrations` sem erro)
- [ ] Testes passam: criação, unicidade, default count
- [ ] `./scripts/test-in-container.sh check` sem erro
- [ ] `./scripts/test-in-container.sh unit` testes do slice passando
- [ ] Modelo registrado/visível no Django admin (opcional, só se fizer sentido)

## Anti-Alucinação / Stop Rules

1. **Se não entender** algum termo ou contexto → **PARE** e documente a dúvida
   no relatório. Não invente.
2. **Limite de arquivos**: máximo **3 arquivos** alterados/criados neste slice.
   Se parecer que precisa de mais → PARE e reporte.
3. **Não modifique** `services.py`, `extract_discharges.py`, views, templates,
   ou urls.
4. **Não adicione** campos extras ao modelo além dos especificados.
5. **Não introduza** imports que não sejam estritamente necessários.
6. Se um teste falhar por motivo que você não consegue resolver em 15 minutos →
   **PARE**, documente o bloqueio, e entregue o relatório.

## Relatório Obrigatório

Ao final, gere `/tmp/sirhosp-slice-S1-report.md` contendo:

```markdown
# Slice S1 Report: TIME_ZONE + DailyDischargeCount

## Resumo
(Uma frase sobre o que foi feito)

## Checklist de Aceite
- [ ] TIME_ZONE alterado
- [ ] Modelo criado
- [ ] Migration gerada
- [ ] Testes passando
- [ ] check e unit verdes

## Arquivos Alterados
(Lista com paths)

## Fragmentos Antes/Depois

### config/settings.py
**Antes:**
`TIME_ZONE = "America/Sao_Paulo"`
**Depois:**
`TIME_ZONE = "America/Bahia"`

### apps/discharges/models.py (NOVO)
(Colar o arquivo completo)

## Comandos Executados e Resultados
(Colar comandos e output resumido)

## Riscos e Pendências
- Nenhum / (listar se houver)

## Próximo Slice
S2: Criar management command refresh_daily_discharge_counts
```

**Após gerar o relatório, PARE. Não inicie o próximo slice.**
