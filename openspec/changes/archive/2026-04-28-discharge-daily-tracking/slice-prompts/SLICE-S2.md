# SLICE-S2: Management command `refresh_daily_discharge_counts`

## Handoff / Contexto de Entrada

**Change**: `discharge-daily-tracking` — rastreamento diário de altas.

**Slice S1 concluído**:

- `TIME_ZONE = "America/Bahia"` em `config/settings.py`
- Modelo `DailyDischargeCount(date, count, created_at, updated_at)` em
  `apps/discharges/models.py`
- Migration `discharges/0001_initial.py` aplicada
- Testes do modelo passando

**O que você vai construir neste slice**:
Management command `refresh_daily_discharge_counts` que consulta
`Admission.discharge_date`, agrupa por dia (timezone America/Bahia),
e faz upsert em `DailyDischargeCount`.

**Próximo slice (S3)**: Hook que chama este comando ao final de
`extract_discharges`.

## Arquivos que você vai tocar (limite: 2)

| Arquivo | Ação |
| --- | --- |
| `tests/unit/test_daily_discharge_count.py` | **Criar** — testes do comando |
| `apps/discharges/management/commands/refresh_daily_discharge_counts.py` | **Criar** |

**NÃO toque** em: models.py, settings.py, services.py, extract_discharges.py,
views, templates, urls.

## TDD Workflow (RED → GREEN → REFACTOR)

### RED: Escreva os testes primeiro

Crie `tests/unit/test_daily_discharge_count.py`:

```python
from datetime import date, datetime, timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.discharges.models import DailyDischargeCount
from apps.patients.models import Admission, Patient


@pytest.mark.django_db
class TestRefreshDailyDischargeCounts:
    """Tests for refresh_daily_discharge_counts management command."""

    def test_command_populates_counts_from_admissions(self):
        """Command groups discharge_date by day and upserts counts."""
        patient = Patient.objects.create(
            patient_source_key="P1", source_system="tasy", name="A")

        today = timezone.localdate()
        yesterday = today - timedelta(days=1)

        # 3 discharges today, 2 yesterday
        for i in range(3):
            Admission.objects.create(
                patient=patient,
                source_admission_key=f"ADM-T{i}",
                source_system="tasy",
                discharge_date=timezone.make_aware(
                    datetime(today.year, today.month, today.day, 10 + i, 0, 0)),
            )
        for i in range(2):
            Admission.objects.create(
                patient=patient,
                source_admission_key=f"ADM-Y{i}",
                source_system="tasy",
                discharge_date=timezone.make_aware(
                    datetime(yesterday.year, yesterday.month, yesterday.day, 14 + i, 0, 0)),
            )

        call_command("refresh_daily_discharge_counts")

        assert DailyDischargeCount.objects.get(date=today).count == 3
        assert DailyDischargeCount.objects.get(date=yesterday).count == 2

    def test_command_upserts_existing_counts(self):
        """Re-running updates existing counts instead of duplicating."""
        patient = Patient.objects.create(
            patient_source_key="P1", source_system="tasy", name="A")
        today = timezone.localdate()

        # First run: 2 discharges
        for i in range(2):
            Admission.objects.create(
                patient=patient,
                source_admission_key=f"ADM-A{i}",
                source_system="tasy",
                discharge_date=timezone.make_aware(
                    datetime(today.year, today.month, today.day, 10 + i, 0, 0)),
            )
        call_command("refresh_daily_discharge_counts")
        assert DailyDischargeCount.objects.get(date=today).count == 2

        # Second run: 1 more discharge → should update to 3
        Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-A3",
            source_system="tasy",
            discharge_date=timezone.make_aware(
                datetime(today.year, today.month, today.day, 15, 0, 0)),
        )
        call_command("refresh_daily_discharge_counts")
        assert DailyDischargeCount.objects.get(date=today).count == 3
        assert DailyDischargeCount.objects.count() == 1  # no duplicates

    def test_command_handles_empty_admissions(self):
        """Command completes without error when no discharge_dates exist."""
        call_command("refresh_daily_discharge_counts")
        assert DailyDischargeCount.objects.count() == 0

    def test_command_ignores_null_discharge_dates(self):
        """Admissions without discharge_date are not counted."""
        patient = Patient.objects.create(
            patient_source_key="P1", source_system="tasy", name="A")
        today = timezone.localdate()

        # One with discharge_date, one without
        Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-D",
            source_system="tasy",
            discharge_date=timezone.make_aware(
                datetime(today.year, today.month, today.day, 10, 0, 0)),
        )
        Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-N",
            source_system="tasy",
            discharge_date=None,
        )

        call_command("refresh_daily_discharge_counts")
        assert DailyDischargeCount.objects.get(date=today).count == 1
```

Rode e confirme que **falham** (comando não existe):

```bash
uv run pytest tests/unit/test_daily_discharge_count.py -q
```

### GREEN: Implementação

Crie `apps/discharges/management/commands/refresh_daily_discharge_counts.py`:

```python
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Count
from django.db.models.functions import TruncDate

from apps.discharges.models import DailyDischargeCount
from apps.patients.models import Admission


class Command(BaseCommand):
    help = (
        "Aggregate Admission.discharge_date by day and upsert "
        "into DailyDischargeCount."
    )

    def handle(self, *args, **options):
        counts = (
            Admission.objects
            .filter(discharge_date__isnull=False)
            .annotate(day=TruncDate("discharge_date"))
            .values("day")
            .annotate(count=Count("id"))
            .order_by("day")
        )

        updated = 0
        for entry in counts:
            _, created = DailyDischargeCount.objects.update_or_create(
                date=entry["day"],
                defaults={"count": entry["count"]},
            )
            updated += 1

        if updated == 0:
            self.stdout.write("No discharge data found.")
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Updated {updated} daily discharge count(s)."
                )
            )
```

Confirme **verde**:

```bash
uv run pytest tests/unit/test_daily_discharge_count.py -q
```

### REFACTOR

- Verifique imports: apenas o necessário
- Confirme que `update_or_create` é a estratégia correta (não `get_or_create`
  com save posterior, que exigiria duas queries)
- O comando segue o padrão dos outros management commands do projeto?

## Critérios de Sucesso (Auto-Avaliação Obrigatória)

- [ ] Comando `refresh_daily_discharge_counts` executável via
  `uv run python manage.py refresh_daily_discharge_counts`
- [ ] Agrupamento por dia usa `TruncDate` no timezone `America/Bahia`
- [ ] Upsert via `update_or_create` (não duplica registros)
- [ ] Comando lida com zero admissions sem erro
- [ ] Admissions sem `discharge_date` são ignoradas
- [ ] Output informativo no stdout
- [ ] 4 testes passando (popula, upsert, vazio, ignora null)
- [ ] `./scripts/test-in-container.sh check` sem erro
- [ ] `./scripts/test-in-container.sh unit` passando

## Anti-Alucinação / Stop Rules

1. **NÃO modifique** `DailyDischargeCount` — o modelo já existe do S1.
2. **NÃO modifique** `process_discharges()` ou `extract_discharges`.
3. **NÃO adicione** lógica de agendamento (systemd timer) — isso já existe.
4. **NÃO use** `bulk_create` em vez de `update_or_create` — perderia o upsert.
5. **Limite**: máximo 2 arquivos. Se precisar de mais → PARE.
6. Se `TruncDate` não funcionar como esperado com timezone → documente no
   relatório, **NÃO** implemente workaround complexo.
7. Se não souber resolver em 20 minutos → PARE, documente, entregue relatório.

## Relatório Obrigatório

Gere `/tmp/sirhosp-slice-S2-report.md` com:

```markdown
# Slice S2 Report: refresh_daily_discharge_counts

## Resumo
...

## Checklist de Aceite
- [ ] Comando executável
- [ ] Agrupamento por dia correto
- [ ] Upsert funciona
- [ ] Zero admissions ok
- [ ] Null discharge_date ignorado
- [ ] 4/4 testes passando
- [ ] check + unit verdes

## Arquivos Alterados
- tests/unit/test_daily_discharge_count.py (NOVO)
- apps/discharges/management/commands/refresh_daily_discharge_counts.py (NOVO)

## Fragmentos Antes/Depois
(Colar snippets relevantes — neste caso só "Depois" pois são arquivos novos)

## Comandos Executados
- uv run pytest tests/unit/test_daily_discharge_count.py -q
- ./scripts/test-in-container.sh check
- ./scripts/test-in-container.sh unit
(Colar outputs)

## Riscos e Pendências
...

## Próximo Slice
S3: Hook do comando no extract_discharges
```

**Após gerar o relatório, PARE.**
