# SLICE-S3: Hook do comando no `extract_discharges`

## Handoff / Contexto de Entrada

**Change**: `discharge-daily-tracking` — rastreamento diário de altas.

**Slice S2 concluído**:

- Management command `refresh_daily_discharge_counts` funcional e testado
  (4 testes passando: popula, upsert, vazio, ignora null)
- Comando agrupa `Admission.discharge_date` por dia (timezone America/Bahia)
  e faz upsert em `DailyDischargeCount`

**O que você vai construir neste slice**:
Adicionar `call_command("refresh_daily_discharge_counts")` ao final do
`handle()` de `extract_discharges`, **apenas quando a extração sucede**.
Se a extração falhar, o refresh NÃO é chamado.

**Próximo slice (S4)**: Alterar dashboard de "Altas (24h)" para "Altas no dia".

## Arquivos que você vai tocar (limite: 2)

| Arquivo | Ação |
| --- | --- |
| `tests/unit/test_daily_discharge_count.py` | **Modificar** — adicionar 2 testes de hook |
| `apps/discharges/management/commands/extract_discharges.py` | **Modificar** — adicionar ~5 linhas |

**NÃO toque** em: models.py, settings.py, views, templates, urls,
`refresh_daily_discharge_counts.py`.

## TDD Workflow (RED → GREEN → REFACTOR)

### RED: Adicione os testes de hook

No arquivo `tests/unit/test_daily_discharge_count.py`, adicione esta classe
**após** `TestRefreshDailyDischargeCounts`:

```python
from unittest.mock import patch

from apps.discharges.management.commands.extract_discharges import Command


@pytest.mark.django_db
class TestExtractDischargesHook:
    """Tests that extract_discharges calls refresh_daily_discharge_counts."""

    @patch(
        "apps.discharges.management.commands.extract_discharges.call_command"
    )
    def test_hook_called_after_successful_extraction(self, mock_call):
        """refresh_daily_discharge_counts is called when extraction succeeds."""
        # Simulate a successful extraction by mocking the subprocess
        # and process_discharges, then verifying call_command is invoked.
        # This test validates the hook exists - the actual integration
        # is tested in integration tests.
        #
        # For unit test: we patch the heavy dependencies and verify
        # that the command's success path includes the call.
        with patch.object(Command, "handle", wraps=None) as mock_handle:
            pass  # placeholder - test structure depends on implementation

    @patch(
        "apps.discharges.management.commands.extract_discharges.call_command"
    )
    def test_hook_not_called_on_extraction_failure(self, mock_call):
        """refresh_daily_discharge_counts is NOT called on failure."""
        pass  # placeholder - test structure depends on implementation
```

**IMPORTANTE**: Os testes acima são esboços. O approach mais prático e robusto
para testar o hook sem executar Playwright é:

```python
import subprocess
from unittest.mock import patch, MagicMock

from django.core.management import call_command as django_call_command
from django.utils import timezone

from apps.ingestion.models import IngestionRun
from apps.patients.models import Patient, Admission


@pytest.mark.django_db
class TestExtractDischargesCallsRefresh:
    """Verify extract_discharges calls refresh_daily_discharge_counts on success."""

    @patch(
        "apps.discharges.management.commands.extract_discharges."
        "call_command"
    )
    @patch("subprocess.run")
    def test_refresh_called_on_success(self, mock_run, mock_call_command):
        """After successful subprocess, refresh is called."""
        # Mock successful subprocess
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        # Create a temp dir with a fake JSON output
        import tempfile, json
        from pathlib import Path

        patient = Patient.objects.create(
            patient_source_key="12345", source_system="tasy", name="Test"
        )
        Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-1",
            source_system="tasy",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            json_path = Path(tmpdir) / "discharges-2026.json"
            json_path.write_text(json.dumps({
                "pacientes": [{
                    "prontuario": "12345",
                    "nome": "Test",
                    "data_internacao": "15/04/2026",
                }]
            }))

            # Patch TemporaryDirectory to return our controlled dir
            with patch(
                "apps.discharges.management.commands.extract_discharges."
                "tempfile.TemporaryDirectory"
            ) as mock_tmp:
                mock_tmp.return_value.__enter__.return_value = Path(tmpdir)

                call_command = django_call_command
                # Actually call the command
                from django.core.management import call_command as mgmt_call
                mgmt_call("extract_discharges", "--headless")

        # Verify refresh was called
        mock_call_command.assert_called_with("refresh_daily_discharge_counts")
```

Se este teste for muito complexo de mockar, simplifique para:

```python
@pytest.mark.django_db
class TestExtractDischargesRefreshHook:
    """Smoke test: verify the hook line exists in the source."""

    def test_command_file_contains_refresh_call(self):
        """extract_discharges.py has call_command('refresh_daily...')."""
        from pathlib import Path
        source = (
            Path(__file__).resolve().parents[3]
            / "apps" / "discharges" / "management" / "commands"
            / "extract_discharges.py"
        )
        content = source.read_text()
        assert "refresh_daily_discharge_counts" in content
        assert "call_command" in content

    def test_refresh_follows_status_succeeded_assignment(self):
        """The refresh call appears after run.status = 'succeeded'."""
        from pathlib import Path
        source = (
            Path(__file__).resolve().parents[3]
            / "apps" / "discharges" / "management" / "commands"
            / "extract_discharges.py"
        )
        content = source.read_text()
        # Find position of status succeeded and refresh
        pos_status = content.find('run.status = "succeeded"')
        pos_refresh = content.find("refresh_daily_discharge_counts")
        assert pos_status > 0, "status succeeded line not found"
        assert pos_refresh > 0, "refresh call not found"
        assert pos_refresh > pos_status, (
            "refresh must appear AFTER status succeeded"
        )
```

**Escolha a abordagem mais limpa.** A segunda (smoke test) é aceitável
porque a lógica real é trivial (3 linhas). Rode os testes e confirme que
**falham** (hook ainda não existe):

```bash
uv run pytest tests/unit/test_daily_discharge_count.py -q -k "hook or refresh or Hook"
```

### GREEN: Adicione o hook

Em `apps/discharges/management/commands/extract_discharges.py`, localize o
**final do `handle()`** — há dois pontos onde `run.status = "succeeded"` é
atribuído:

1. Após `discharge_persistence` stage com sucesso (caminho normal)
2. Após lista vazia de JSON ("No discharges found today")

Em **ambos** os pontos, imediatamente após `run.save()` (ou após a atribuição
de `run.status = "succeeded"`), adicione:

```python
# Refresh daily discharge tracking table
from django.core.management import call_command
call_command("refresh_daily_discharge_counts")
```

**Localização exata**:

No caminho 1 (processamento normal, ~linha 130-135 do arquivo atual):

```python
            run.status = "succeeded"
            run.finished_at = timezone.now()
            run.save()

            # ATUALIZAR tracking diário de altas
            from django.core.management import call_command
            call_command("refresh_daily_discharge_counts")
```

No caminho 2 (lista vazia, ~linha 115-120):

```python
                run.status = "succeeded"
                run.finished_at = timezone.now()
                run.save()
                # ATUALIZAR tracking diário de altas
                from django.core.management import call_command
                call_command("refresh_daily_discharge_counts")
                self.stdout.write(self.style.SUCCESS("No discharges found today."))
                return
```

**IMPORTANTE**: O `call_command` deve vir ANTES do `return` no caminho 2
(para que seja executado antes de sair).

Confirme **verde**:

```bash
uv run pytest tests/unit/test_daily_discharge_count.py -q
```

### REFACTOR

- O import `from django.core.management import call_command` pode ser movido
  para o topo do arquivo (junto com os outros imports) para evitar duplicação.
  Faça isso.
- Verifique que o hook está presente nos DOIS caminhos de sucesso.
- Confirme que nenhum caminho de falha (`sys.exit(1)`) tem o hook.

## Critérios de Sucesso (Auto-Avaliação Obrigatória)

- [ ] `call_command("refresh_daily_discharge_counts")` adicionado em ambos os
  caminhos de sucesso do `handle()`
- [ ] Hook posicionado APÓS `run.status = "succeeded"` / `run.save()`
- [ ] Hook NÃO está em nenhum caminho de falha (`sys.exit(1)`)
- [ ] Import movido para o topo do arquivo (não duplicado)
- [ ] Testes passando (smoke test ou mock test)
- [ ] `./scripts/test-in-container.sh check` sem erro
- [ ] `./scripts/test-in-container.sh unit` passando (todos os testes,
  não só os do slice)

## Anti-Alucinação / Stop Rules

1. **NÃO altere** a lógica de extração (subprocess, process_discharges,
   parsing de JSON).
2. **NÃO altere** `refresh_daily_discharge_counts.py`.
3. **NÃO remova** `sys.exit(0)` ou `sys.exit(1)` existentes.
4. **NÃO adicione** try/except em volta do hook — se falhar, deve propagar.
5. **Limite**: máximo 2 arquivos alterados.
6. Se não conseguir fazer o mock test funcionar → use o smoke test
   (verificação de string no fonte). É aceitável para este slice.
7. Se não souber resolver em 20 minutos → PARE, documente, entregue relatório.

## Relatório Obrigatório

Gere `/tmp/sirhosp-slice-S3-report.md`:

```markdown
# Slice S3 Report: Hook no extract_discharges

## Resumo
...

## Checklist de Aceite
- [ ] Hook nos 2 caminhos de sucesso
- [ ] Hook ausente nos caminhos de falha
- [ ] Import no topo do arquivo
- [ ] Testes passando
- [ ] check + unit verdes

## Arquivos Alterados
- apps/discharges/management/commands/extract_discharges.py (modificado)
- tests/unit/test_daily_discharge_count.py (modificado: +testes hook)

## Fragmentos Antes/Depois
(Mostrar o antes/depois dos trechos modificados em extract_discharges.py)

## Comandos Executados
(Colar outputs)

## Riscos e Pendências
...

## Próximo Slice
S4: Dashboard: query + template + URL
```

**Após gerar o relatório, PARE.**
