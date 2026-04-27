# SLICE-S1: Script de extração + app `discharges` + serviço + comando

> **Handoff para executor com ZERO contexto adicional.**
> Este documento é autocontido — não requer leitura de outros arquivos do projeto.
> Leia até o fim antes de começar.

---

## 1. Contexto do Projeto

**SIRHOSP** — Sistema Interno de Relatórios Hospitalares.
Extrai dados clínicos do sistema fonte hospitalar via web scraping (Playwright),
persiste em banco PostgreSQL paralelo, e oferece portal web Django para consulta rápida
por diretoria, qualidade e jurídico.

**Stack**:

- Python 3.12
- Django 5.x
- PostgreSQL
- `uv` para gerenciamento de dependências e execução de comandos Python
- Playwright (Chromium) para scraping
- PyMuPDF para extração de PDF
- pytest para testes
- Bootstrap 5 + HTMX no frontend

**Arquitetura**: monólito modular. Apps Django em `apps/`. Automações em `automation/`.

**Regras críticas**: sem Celery/Redis na fase 1, sem dados reais no código, TDD obrigatório.

---

## 2. O que este Slice faz

**Objetivo**: Criar a infraestrutura completa de extração e processamento de altas:

1. Script Playwright que acessa a página "Altas do Dia" do sistema fonte, baixa o PDF e extrai a lista de pacientes
2. App Django `discharges` com serviço de processamento que atualiza `discharge_date` nas `Admission`
3. Management command `extract_discharges` que orquestra tudo (subprocess + serviço)

Após este slice, o comando `uv run python manage.py extract_discharges` estará funcional e populando
o campo `Admission.discharge_date`. O card "Altas (24h)" do dashboard passará a mostrar dados reais.

---

## 3. Estrutura atual do projeto (relevante)

```text
sirhosp/
├── config/
│   └── settings.py              ← INSTALLED_APPS
├── apps/
│   ├── patients/
│   │   └── models.py            ← Patient, Admission (já existem)
│   ├── ingestion/
│   │   └── models.py            ← IngestionRun, IngestionRunStageMetric
│   ├── census/                  ← app de referência (padrão a seguir)
│   │   ├── apps.py
│   │   ├── models.py
│   │   ├── services.py
│   │   └── management/commands/
│   │       ├── extract_census.py
│   │       └── process_census_snapshot.py
│   └── ...
├── automation/
│   └── source_system/
│       ├── source_system.py     ← bridge module (aguardar_pagina_estavel, fechar_dialogos_iniciais)
│       ├── current_inpatients/
│       │   └── extract_census.py ← referência de script Playwright
│       └── medical_evolution/   ← (não relevante para este slice)
├── tests/
│   └── unit/
│       └── ...
└── manage.py
```

---

## 4. Modelos de referência (NÃO modificar)

### `Patient` (`apps/patients/models.py`)

```python
class Patient(models.Model):
    patient_source_key = models.CharField(max_length=255)  # prontuário (ex: "14160147")
    source_system = models.CharField(max_length=50, default="tasy")
    name = models.CharField(max_length=512)
    # ... outros campos
```

### `Admission` (`apps/patients/models.py`)

```python
class Admission(models.Model):
    patient = models.ForeignKey(Patient, on_delete=models.CASCADE, related_name="admissions")
    source_admission_key = models.CharField(max_length=255)
    source_system = models.CharField(max_length=100, default="tasy")
    admission_date = models.DateTimeField(null=True, blank=True)
    discharge_date = models.DateTimeField(null=True, blank=True)  # ← NOSSO ALVO
    # ... outros campos

    class Meta:
        constraints = [
            UniqueConstraint(fields=["source_system", "source_admission_key"], name="uq_adm_src"),
        ]
```

### `IngestionRun` (`apps/ingestion/models.py`)

```python
class IngestionRun(models.Model):
    STATUS_CHOICES = [
        ("queued", "Queued"),
        ("running", "Running"),
        ("succeeded", "Succeeded"),
        ("failed", "Failed"),
    ]
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="queued")
    intent = models.CharField(max_length=50, ...)       # usaremos "discharge_extraction"
    queued_at = models.DateTimeField(...)
    processing_started_at = models.DateTimeField(null=True, ...)
    finished_at = models.DateTimeField(null=True, ...)
    error_message = models.TextField(blank=True, default="")
    failure_reason = models.CharField(max_length=50, blank=True, default="")
    timed_out = models.BooleanField(default=False)
    parameters_json = models.JSONField(default=dict, blank=True)
```

### `IngestionRunStageMetric` (`apps/ingestion/models.py`)

```python
class IngestionRunStageMetric(models.Model):
    run = models.ForeignKey(IngestionRun, on_delete=models.CASCADE, related_name="stage_metrics")
    stage_name = models.CharField(max_length=100)
    started_at = models.DateTimeField()
    finished_at = models.DateTimeField()
    status = models.CharField(max_length=20)
    details_json = models.JSONField(default=dict, blank=True)
```

---

## 5. Convenções de código do projeto

- Todo `.py`: `from __future__ import annotations` no topo
- FK: usar string `"app_label.ModelName"` para evitar import circular
- Scripts Playwright: funções helper com type hints, constantes no topo, CLI via `argparse`
- Management commands: herdar de `BaseCommand`, `help` docstring, `add_arguments`, `handle`
- Testes: `@pytest.mark.django_db` na classe, nome `tests/unit/test_discharge_*.py`
- Testes: usar `reverse()` para URLs, `timezone.now()` para timestamps
- Templates: usar `{% url %}` para links (não relevante neste slice, mas é convenção)
- Quality gate: `./scripts/test-in-container.sh check|unit|lint`

---

## 6. O que EXATAMENTE criar

### 6.1 `automation/source_system/discharges/__init__.py`

Arquivo vazio.

### 6.2 `automation/source_system/discharges/extract_discharges.py`

**Script Playwright completo.** Adaptar a partir do código existente em
`/home/carlos/projects/pontelo/busca-altas-hoje.py` (leia o arquivo de origem para
copiar as funções de extração de PDF — elas são extensas e NÃO devem ser reescritas).

#### Estrutura do arquivo

```python
#!/usr/bin/env python3
"""..."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

import pymupdf
from playwright.sync_api import BrowserContext, FrameLocator, Page, sync_playwright

# ── Importa helpers do bridge module do SIRHOSP ──
# extract_discharges.py está em automation/source_system/discharges/
# bridge module está em automation/source_system/source_system.py (1 nível acima)
_CURRENT_DIR = Path(__file__).resolve().parent
_SOURCE_SYSTEM_DIR = _CURRENT_DIR.parent
sys.path.insert(0, str(_SOURCE_SYSTEM_DIR))

from source_system import aguardar_pagina_estavel, fechar_dialogos_iniciais  # noqa: E402

# ── Constantes ──
DEFAULT_TIMEOUT_MS = 180000
ALTAS_IFRAME_NAME = "i_frame_altas_do_dia"
ALTAS_ICON_SELECTOR = ".silk-new-internacao-altas-do-dia"  # classe CSS estável

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DOWNLOADS_DIR = _PROJECT_ROOT / "downloads"
DEBUG_DIR = _PROJECT_ROOT / "debug"
```

#### CLI

```python
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Extrai lista de pacientes com alta hoje do sistema fonte."
    )
    parser.add_argument("--headless", action="store_true", help="Executa sem interface gráfica")
    parser.add_argument("--output-dir", type=str, default=None,
                        help="Diretório de saída para o JSON")
    parser.add_argument("--source-url", type=str, required=True,
                        help="URL do sistema fonte")
    parser.add_argument("--username", type=str, required=True,
                        help="Nome de usuário do sistema fonte")
    parser.add_argument("--password", type=str, required=True,
                        help="Senha do sistema fonte")
    return parser.parse_args()
```

#### Funções a copiar do `pontelo/busca-altas-hoje.py` (MANTER IGUAIS)

Estas funções NÃO devem ser reescritas — copie-as integralmente do arquivo original:

- `wait_visible(locator, timeout)` — aguarda elemento visível
- `safe_click(locator, label, timeout)` — clique com fallback
- `get_altas_frame_locator(page)` — retorna `FrameLocator`
- `wait_altas_frame_ready(page, timeout_ms)` — aguarda iframe
- `click_altas_icon(page)` — **ATENÇÃO: alterar seletor** (ver abaixo)
- `click_visualizar_impressao(frame_locator)` — clica no botão
- `get_pdf_url_from_frame(frame_locator, page)` — extrai URL do `<object>`
- `download_pdf(context, pdf_url, output_path)` — download autenticado
- `extract_patients_from_pdf(pdf_path)` — parse com PyMuPDF
- `_extract_patients_by_x_bands(words)` — análise de bandas X
- `_group_by_x_band(pront_words, tolerance)` — agrupamento X
- `_parse_patient_band(main_words, secondary_words)` — parsing de campos
- `_clean_prontuario(raw)` — remove `/` do prontuário
- `_normalize_data(raw)` — normaliza DD/MM/YY → DD/MM/YYYY
- Todas as regex: `_RE_PRONTUARIO`, `_RE_DATA_CURTA`, `_RE_DATA_LONGA`, `_RE_CRM`, `_RE_CRM_PLACEHOLDER`, `_RE_SO_NUMEROS`, `_RE_PREFIXO`

#### Única alteração: `click_altas_icon`

**ORIGINAL** (do `pontelo/`):

```python
def click_altas_icon(page: Page) -> None:
    icon = page.locator(f'[id="{ALTAS_ICON_ID}"]')
    ...
```

**NOVO** (use classe CSS estável):

```python
def click_altas_icon(page: Page) -> None:
    """Clica no ícone de Altas do Dia usando classe CSS estável."""
    icon = page.locator(ALTAS_ICON_SELECTOR)
    if not safe_click(icon, "ícone Altas do Dia", timeout=20000):
        raise RuntimeError("Não foi possível clicar no ícone de Altas do Dia.")
    print("[i] Ícone Altas do Dia clicado.")
```

#### Login — usar helpers do bridge module

```python
# Login
page.goto(source_system_url)
page.get_by_role("textbox", name="Nome de usuário").fill(username)
page.get_by_role("textbox", name="Senha").fill(password)
page.get_by_role("button", name="Entrar").click()
aguardar_pagina_estavel(page)
fechar_dialogos_iniciais(page)
```

#### API pública (main entry point)

**ASSINATURA ALTERADA**: a função `capturar_altas_hoje` do script original recebia
`source_system_url`, `username`, `password` como parâmetros. No script adaptado,
esses valores vêm dos argumentos CLI, e a função principal é a `main()`:

```python
def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir) if args.output_dir else DOWNLOADS_DIR

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=args.headless,
            args=["--ignore-certificate-errors"],
        )
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT_MS)

        try:
            # Login (usando credenciais da CLI)
            page.goto(args.source_url)
            page.get_by_role("textbox", name="Nome de usuário").fill(args.username)
            page.get_by_role("textbox", name="Senha").fill(args.password)
            page.get_by_role("button", name="Entrar").click()
            aguardar_pagina_estavel(page)
            fechar_dialogos_iniciais(page)

            # Navegar para Altas do Dia
            click_altas_icon(page)
            frame_locator = wait_altas_frame_ready(page)
            page.wait_for_timeout(1500)

            # Visualizar Impressão
            click_visualizar_impressao(frame_locator)
            page.wait_for_timeout(3000)

            # Download PDF
            pdf_url = get_pdf_url_from_frame(frame_locator, page)
            pdf_path = output_dir / "altas-hoje.pdf"
            download_pdf(context, pdf_url, pdf_path)

            # Extrair pacientes
            patients = extract_patients_from_pdf(pdf_path)

            # Salvar JSON
            output_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d-%H%M%S")
            json_path = output_dir / f"discharges-{ts}.json"
            data = {
                "data": time.strftime("%Y-%m-%d"),
                "total": len(patients),
                "pacientes": patients,
            }
            json_path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            print(f"[i] JSON salvo em: {json_path}")

        except Exception as e:
            print(f"[ERRO] {e}", file=sys.stderr)
            # Salvar debug
            DEBUG_DIR.mkdir(exist_ok=True)
            ts = time.strftime("%Y%m%d-%H%M%S")
            try:
                page.screenshot(path=str(DEBUG_DIR / f"discharges-error-{ts}.png"))
                (DEBUG_DIR / f"discharges-error-{ts}.html").write_text(
                    page.content(), encoding="utf-8"
                )
            except Exception:
                pass
            sys.exit(1)
        finally:
            context.close()
            browser.close()

    # Se chegou aqui sem erro, sair com 0
    # (o JSON foi salvo; o management command vai lê-lo)
```

### 6.3 `apps/discharges/__init__.py`

Arquivo vazio.

### 6.4 `apps/discharges/apps.py`

```python
from __future__ import annotations

from django.apps import AppConfig


class DischargesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.discharges"
    verbose_name = "Discharges"
```

### 6.5 `apps/discharges/services.py`

Serviço puro (sem dependência de request/response). Função `process_discharges()`.

```python
from __future__ import annotations

from datetime import datetime
from typing import Any

from django.utils import timezone

from apps.patients.models import Admission, Patient


def process_discharges(patients: list[dict[str, str]]) -> dict[str, int]:
    """Process a list of discharged patients and update Admission.discharge_date.

    For each patient in the list:
      1. Look up Patient by patient_source_key (prontuario).
         If not found → skip (patient_not_found).
      2. Find the matching Admission:
         a) Exact match by data_internacao (admission_date date == data_internacao date)
            AND discharge_date IS NULL.
         b) Fallback: most recent admission with discharge_date IS NULL.
         If no match → skip (admission_not_found).
      3. If admission already has discharge_date → skip (already_discharged).
      4. Set discharge_date = timezone.now() → count as discharge_set.

    Args:
        patients: List of dicts with keys:
            prontuario, nome, leito, especialidade, data_internacao

    Returns:
        Dict with metrics:
            total_pdf: Total patients in the input list
            patient_not_found: Patients whose prontuario is not in the DB
            admission_not_found: Patients found but no matching admission
            already_discharged: Admissions that already had discharge_date set
            discharge_set: Admissions where discharge_date was successfully set
    """
    total_pdf = len(patients)
    patient_not_found = 0
    admission_not_found = 0
    already_discharged = 0
    discharge_set = 0

    for p in patients:
        prontuario = p.get("prontuario", "").strip()
        data_internacao_str = p.get("data_internacao", "").strip()

        if not prontuario:
            continue

        # 1. Find Patient by patient_source_key
        try:
            patient = Patient.objects.get(
                source_system="tasy",
                patient_source_key=prontuario,
            )
        except Patient.DoesNotExist:
            patient_not_found += 1
            continue

        # 2. Find matching Admission
        admission = None

        # 2a. Exact match by data_internacao
        if data_internacao_str:
            try:
                data_int = datetime.strptime(data_internacao_str, "%d/%m/%Y").date()
                admission = Admission.objects.filter(
                    patient=patient,
                    admission_date__date=data_int,
                    discharge_date__isnull=True,
                ).order_by("-admission_date").first()
            except (ValueError, OverflowError):
                pass  # invalid date format → skip to fallback

        # 2b. Fallback: most recent without discharge_date
        if admission is None:
            admission = Admission.objects.filter(
                patient=patient,
                discharge_date__isnull=True,
            ).order_by("-admission_date").first()

        if admission is None:
            admission_not_found += 1
            continue

        # 3. Already discharged?
        if admission.discharge_date is not None:
            already_discharged += 1
            continue

        # 4. Set discharge_date
        admission.discharge_date = timezone.now()
        admission.save(update_fields=["discharge_date", "updated_at"])
        discharge_set += 1

    return {
        "total_pdf": total_pdf,
        "patient_not_found": patient_not_found,
        "admission_not_found": admission_not_found,
        "already_discharged": already_discharged,
        "discharge_set": discharge_set,
    }
```

### 6.6 `apps/discharges/management/commands/__init__.py`

Arquivo vazio.

### 6.7 `apps/discharges/management/commands/extract_discharges.py`

**Management command que orquestra o ciclo completo.** Mesmo padrão do
`apps/census/management/commands/extract_census.py` (leia-o como referência).

```python
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.discharges.services import process_discharges
from apps.ingestion.models import IngestionRun, IngestionRunStageMetric

import json  # noqa: E402 (colocar no topo na versão final)


class Command(BaseCommand):
    help = "Extract today's discharges from source system and update Admission records."

    def add_arguments(self, parser):
        parser.add_argument(
            "--headless",
            action="store_true",
            default=True,
            help="Run Playwright in headless mode.",
        )
        parser.add_argument(
            "--no-headless",
            dest="headless",
            action="store_false",
            help="Run Playwright with visible browser.",
        )

    def handle(self, *args, **options):
        headless: bool = options["headless"]

        # Resolve credentials from settings/environment
        from django.conf import settings

        source_url = getattr(settings, "SOURCE_SYSTEM_URL", "")
        username = getattr(settings, "SOURCE_SYSTEM_USERNAME", "")
        password = getattr(settings, "SOURCE_SYSTEM_PASSWORD", "")

        if not all([source_url, username, password]):
            self.stderr.write("Missing source system credentials in settings.")
            sys.exit(1)

        # Path to the extract_discharges.py script
        script_path = (
            Path(__file__).resolve().parents[4]  # discharges/commands/extract_discharges.py → project root
            / "automation"
            / "source_system"
            / "discharges"
            / "extract_discharges.py"
        )

        if not script_path.exists():
            self.stderr.write(f"Script not found: {script_path}")
            sys.exit(1)

        # Create IngestionRun
        run = IngestionRun.objects.create(
            status="running",
            intent="discharge_extraction",
            queued_at=timezone.now(),
            processing_started_at=timezone.now(),
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            # ── Stage: discharge_extraction (subprocess) ──
            ext_stage_start = timezone.now()
            cmd = [
                sys.executable,
                str(script_path),
                "--output-dir", str(tmpdir_path),
                "--source-url", source_url,
                "--username", username,
                "--password", password,
            ]
            if headless:
                cmd.append("--headless")

            self.stdout.write("Running discharge extraction...")
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=600,  # 10 minutes max
                )
            except subprocess.TimeoutExpired as exc:
                self._record_stage(run, "discharge_extraction", "failed",
                                   ext_stage_start,
                                   details_json={"error": str(exc)})
                self._mark_run_failed(run, str(exc), failure_reason="timeout",
                                      timed_out=True)
                self.stderr.write(f"Discharge extraction timed out: {exc}")
                sys.exit(1)
            except Exception as exc:
                self._record_stage(run, "discharge_extraction", "failed",
                                   ext_stage_start,
                                   details_json={"error": str(exc)})
                self._mark_run_failed(run, str(exc),
                                      failure_reason="unexpected_exception")
                self.stderr.write(f"Discharge extraction failed: {exc}")
                sys.exit(1)

            if result.returncode != 0:
                err_msg = result.stderr[:500] if result.stderr else "Unknown error"
                self._record_stage(run, "discharge_extraction", "failed",
                                   ext_stage_start,
                                   details_json={"returncode": result.returncode})
                self._mark_run_failed(run, err_msg,
                                      failure_reason="source_unavailable")
                self.stderr.write(result.stderr)
                sys.exit(1)

            self._record_stage(run, "discharge_extraction", "succeeded",
                               ext_stage_start)

            # ── Stage: discharge_persistence (process JSON + set discharge_date) ──
            persist_stage_start = timezone.now()

            # Find JSON output
            json_files = sorted(
                tmpdir_path.glob("discharges-*.json"),
                key=lambda p: p.stat().st_mtime, reverse=True,
            )
            if not json_files:
                # Empty list — no discharges today (success, just nothing to do)
                self._record_stage(
                    run, "discharge_persistence", "succeeded",
                    persist_stage_start,
                    details_json={
                        "total_pdf": 0,
                        "discharge_set": 0,
                        "patient_not_found": 0,
                        "admission_not_found": 0,
                        "already_discharged": 0,
                    },
                )
                run.status = "succeeded"
                run.finished_at = timezone.now()
                run.save()
                self.stdout.write(
                    self.style.SUCCESS("No discharges found today.")
                )
                return

            json_path = json_files[0]
            self.stdout.write(f"  JSON output: {json_path}")

            try:
                data = json.loads(json_path.read_text(encoding="utf-8"))
                patients = data.get("pacientes", [])
                self.stdout.write(f"  Patients in PDF: {len(patients)}")

                metrics = process_discharges(patients)
                self.stdout.write(
                    f"  Discharge set: {metrics['discharge_set']} | "
                    f"Already discharged: {metrics['already_discharged']} | "
                    f"Patient not found: {metrics['patient_not_found']} | "
                    f"Admission not found: {metrics['admission_not_found']}"
                )
            except Exception as exc:
                self._record_stage(run, "discharge_persistence", "failed",
                                   persist_stage_start,
                                   details_json={"error": str(exc)})
                self._mark_run_failed(run, str(exc),
                                      failure_reason="unexpected_exception")
                self.stderr.write(f"Discharge processing failed: {exc}")
                sys.exit(1)

            self._record_stage(
                run, "discharge_persistence", "succeeded",
                persist_stage_start,
                details_json=metrics,
            )

            run.status = "succeeded"
            run.finished_at = timezone.now()
            run.save()

            self.stdout.write(
                self.style.SUCCESS(
                    f"Discharge extraction complete. "
                    f"{metrics['discharge_set']} discharges set."
                )
            )

    # ── Helpers (mesmo padrão do extract_census) ──

    @staticmethod
    def _record_stage(run, stage_name, status, started_at,
                      finished_at=None, details_json=None):
        IngestionRunStageMetric.objects.create(
            run=run,
            stage_name=stage_name,
            started_at=started_at,
            finished_at=finished_at or timezone.now(),
            status=status,
            details_json=details_json or {},
        )

    def _mark_run_failed(self, run, error_message, failure_reason="",
                         timed_out=False):
        run.status = "failed"
        run.error_message = error_message
        run.finished_at = timezone.now()
        run.failure_reason = failure_reason
        run.timed_out = timed_out
        run.save()
```

**IMPORTANTE**: Ajustar `parents[4]` no `script_path` se necessário.
O arquivo `extract_discharges.py` do management command está em:
`apps/discharges/management/commands/extract_discharges.py`
→ 4 níveis acima = raiz do projeto → depois `automation/source_system/discharges/extract_discharges.py`.
Confirme que `script_path` resolve corretamente.

### 6.8 `config/settings.py` — adicionar ao `INSTALLED_APPS`

Adicionar `"apps.discharges.DischargesConfig"` ao final da lista `INSTALLED_APPS`.

**IMPORTANTE**: usar o caminho completo com `.DischargesConfig`, igual aos outros apps.

Localize `INSTALLED_APPS` em `config/settings.py` e adicione a nova entrada.
Exemplo de como as últimas linhas devem ficar:

```python
    "apps.search",
    "apps.services_portal",
    "apps.census.CensusConfig",
    "apps.discharges.DischargesConfig",  # NOVO
]
```

**Verifique o fechamento correto do colchete** — pode ser que `apps.discharges`
seja o último elemento.

---

## 7. Testes: `tests/unit/test_discharge_service.py` (NOVO)

```python
from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from django.utils import timezone

from apps.discharges.services import process_discharges
from apps.patients.models import Admission, Patient


@pytest.mark.django_db
class TestProcessDischarges:
    """Tests for DischargeService.process_discharges()."""

    def test_empty_list_returns_zeros(self):
        """Empty input returns all zeros."""
        result = process_discharges([])
        assert result == {
            "total_pdf": 0,
            "patient_not_found": 0,
            "admission_not_found": 0,
            "already_discharged": 0,
            "discharge_set": 0,
        }

    def test_patient_not_found_is_skipped(self):
        """Patient not in DB is skipped, not created."""
        patients = [
            {
                "prontuario": "99999",
                "nome": "PACIENTE INEXISTENTE",
                "leito": "X01",
                "especialidade": "NEF",
                "data_internacao": "15/04/2026",
            }
        ]
        result = process_discharges(patients)
        assert result["total_pdf"] == 1
        assert result["patient_not_found"] == 1
        assert result["discharge_set"] == 0
        # Confirm patient was NOT created
        assert not Patient.objects.filter(patient_source_key="99999").exists()

    def test_discharge_set_with_data_internacao_match(self):
        """Matching by data_internacao sets discharge_date."""
        patient = Patient.objects.create(
            patient_source_key="12345",
            source_system="tasy",
            name="FULANO DE TAL",
        )
        data_int = date.today() - timedelta(days=10)
        admission = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-001",
            source_system="tasy",
            admission_date=datetime.combine(data_int, datetime.min.time()),
            discharge_date=None,
        )

        patients = [
            {
                "prontuario": "12345",
                "nome": "FULANO DE TAL",
                "leito": "UG01A",
                "especialidade": "NEF",
                "data_internacao": data_int.strftime("%d/%m/%Y"),
            }
        ]

        result = process_discharges(patients)
        assert result["discharge_set"] == 1
        assert result["patient_not_found"] == 0
        assert result["admission_not_found"] == 0

        admission.refresh_from_db()
        assert admission.discharge_date is not None
        # discharge_date should be approximately now
        assert (timezone.now() - admission.discharge_date).total_seconds() < 10

    def test_fallback_to_most_recent_admission(self):
        """When data_internacao doesn't match, use most recent without discharge."""
        patient = Patient.objects.create(
            patient_source_key="12345",
            source_system="tasy",
            name="FULANO",
        )
        now = timezone.now()
        # Older admission
        Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-OLD",
            source_system="tasy",
            admission_date=now - timedelta(days=30),
            discharge_date=None,
        )
        # Most recent admission
        recent = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-RECENT",
            source_system="tasy",
            admission_date=now - timedelta(days=5),
            discharge_date=None,
        )

        # data_internacao that doesn't match any admission
        patients = [
            {
                "prontuario": "12345",
                "nome": "FULANO",
                "leito": "UG01A",
                "especialidade": "NEF",
                "data_internacao": (date.today() - timedelta(days=3)).strftime("%d/%m/%Y"),
            }
        ]

        result = process_discharges(patients)
        assert result["discharge_set"] == 1

        recent.refresh_from_db()
        assert recent.discharge_date is not None

    def test_already_discharged_is_skipped(self):
        """Admission with discharge_date already set is skipped."""
        patient = Patient.objects.create(
            patient_source_key="12345",
            source_system="tasy",
            name="FULANO",
        )
        already_discharged_date = timezone.now() - timedelta(hours=2)
        Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-001",
            source_system="tasy",
            admission_date=timezone.now() - timedelta(days=10),
            discharge_date=already_discharged_date,
        )

        patients = [
            {
                "prontuario": "12345",
                "nome": "FULANO",
                "leito": "UG01A",
                "especialidade": "NEF",
                "data_internacao": (date.today() - timedelta(days=10)).strftime("%d/%m/%Y"),
            }
        ]

        result = process_discharges(patients)
        assert result["already_discharged"] == 1
        assert result["discharge_set"] == 0

    def test_admission_not_found_when_all_discharged(self):
        """When all admissions have discharge_date, count as not_found."""
        patient = Patient.objects.create(
            patient_source_key="12345",
            source_system="tasy",
            name="FULANO",
        )
        Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-001",
            source_system="tasy",
            admission_date=timezone.now() - timedelta(days=10),
            discharge_date=timezone.now() - timedelta(days=1),
        )

        patients = [
            {
                "prontuario": "12345",
                "nome": "FULANO",
                "leito": "UG01A",
                "especialidade": "NEF",
                "data_internacao": (date.today() - timedelta(days=10)).strftime("%d/%m/%Y"),
            }
        ]

        result = process_discharges(patients)
        assert result["admission_not_found"] == 1
        assert result["discharge_set"] == 0

    def test_invalid_date_format_falls_back(self):
        """Invalid data_internacao format should not crash, uses fallback."""
        patient = Patient.objects.create(
            patient_source_key="12345",
            source_system="tasy",
            name="FULANO",
        )
        admission = Admission.objects.create(
            patient=patient,
            source_admission_key="ADM-001",
            source_system="tasy",
            admission_date=timezone.now() - timedelta(days=5),
            discharge_date=None,
        )

        patients = [
            {
                "prontuario": "12345",
                "nome": "FULANO",
                "leito": "UG01A",
                "especialidade": "NEF",
                "data_internacao": "DATA-INVALIDA",
            }
        ]

        result = process_discharges(patients)
        assert result["discharge_set"] == 1  # fallback succeeded

        admission.refresh_from_db()
        assert admission.discharge_date is not None

    def test_multiple_patients_mixed_results(self):
        """Mixed results: some found, some not, some already discharged."""
        # Patient 1: normal discharge
        p1 = Patient.objects.create(
            patient_source_key="111", source_system="tasy", name="P1")
        Admission.objects.create(
            patient=p1, source_admission_key="A1", source_system="tasy",
            admission_date=timezone.now() - timedelta(days=5), discharge_date=None)

        # Patient 2: already discharged
        p2 = Patient.objects.create(
            patient_source_key="222", source_system="tasy", name="P2")
        Admission.objects.create(
            patient=p2, source_admission_key="A2", source_system="tasy",
            admission_date=timezone.now() - timedelta(days=5),
            discharge_date=timezone.now() - timedelta(hours=3))

        # Patient 3: not in DB (no Patient created)
        # Patient 4: no prontuario (empty)

        patients = [
            {"prontuario": "111", "nome": "P1", "leito": "B1",
             "especialidade": "NEF",
             "data_internacao": (date.today() - timedelta(days=5)).strftime("%d/%m/%Y")},
            {"prontuario": "222", "nome": "P2", "leito": "B2",
             "especialidade": "CIV",
             "data_internacao": (date.today() - timedelta(days=5)).strftime("%d/%m/%Y")},
            {"prontuario": "333", "nome": "P3", "leito": "B3",
             "especialidade": "PED",
             "data_internacao": "15/04/2026"},
            {"prontuario": "", "nome": "", "leito": "",
             "especialidade": "", "data_internacao": ""},
        ]

        result = process_discharges(patients)
        assert result["total_pdf"] == 4
        assert result["discharge_set"] == 1      # P1
        assert result["already_discharged"] == 1  # P2
        assert result["patient_not_found"] == 1   # P3
        # P4: prontuario vazio é ignorado, não conta como patient_not_found
```

---

## 8. Sequência de execução (TDD)

1. **RED**: Criar `tests/unit/test_discharge_service.py` com os testes acima.
   Rodar `uv run pytest tests/unit/test_discharge_service.py -v` e ver falhar (imports,
   arquivos ainda não existem).
2. **GREEN**: Criar `apps/discharges/__init__.py`, `apps/discharges/apps.py`,
   `apps/discharges/services.py` com `process_discharges()`.
3. **GREEN**: Rodar testes — devem passar (serviço puro, não depende de settings).
4. **GREEN**: Criar `automation/source_system/discharges/__init__.py` e
   `automation/source_system/discharges/extract_discharges.py`.
5. **GREEN**: Criar `apps/discharges/management/commands/__init__.py` e
   `apps/discharges/management/commands/extract_discharges.py`.
6. **GREEN**: Adicionar `"apps.discharges.DischargesConfig"` ao `INSTALLED_APPS`
   em `config/settings.py`.
7. **GREEN**: Rodar `uv run python manage.py check` — confirmar que o app é reconhecido.
8. **REFACTOR**: Revisar imports, verificar paths, limpar código.
9. Rodar quality gate completo.

---

## 9. Quality Gate (obrigatório)

Rodar no container:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh lint
```

Se Docker não disponível, fallback host-only (diagnóstico, não oficial):

```bash
uv run python manage.py check
uv run pytest tests/unit/test_discharge_service.py -v
uv run ruff check apps/discharges/ automation/source_system/discharges/ tests/unit/test_discharge_service.py config/settings.py
```

---

## 10. Relatório obrigatório

Gerar `/tmp/sirhosp-slice-DIS-S1-report.md` com:

```markdown
# Slice DIS-S1 Report

## Status
[PASS / FAIL]

## Arquivos criados
- automation/source_system/discharges/__init__.py
- automation/source_system/discharges/extract_discharges.py
- apps/discharges/__init__.py
- apps/discharges/apps.py
- apps/discharges/services.py
- apps/discharges/management/commands/__init__.py
- apps/discharges/management/commands/extract_discharges.py
- tests/unit/test_discharge_service.py

## Arquivos modificados
- config/settings.py (adicionado apps.discharges.DischargesConfig ao INSTALLED_APPS)

## Snippets before/after
### config/settings.py — INSTALLED_APPS
**Before:** (últimas 3 linhas)
**After:** (últimas 3 linhas + nova entrada)

### apps/discharges/services.py
(conteúdo completo criado — snippet dos métodos principais)

### apps/discharges/management/commands/extract_discharges.py
(conteúdo completo criado — snippet do handle())

## Comandos executados
- ./scripts/test-in-container.sh check: [output resumido]
- ./scripts/test-in-container.sh unit: [output resumido]
- ./scripts/test-in-container.sh lint: [output resumido]

## Resultados dos testes
- [X/Y] passed (test_discharge_service.py)

## Riscos / Pendências
- Script Playwright NÃO foi testado contra o sistema fonte real (sem credenciais).
  Teste funcional será feito após deploy com credenciais reais.
- O caminho `parents[4]` no script_path do management command deve ser validado
  em ambiente real.

## Próximo slice sugerido
S2 — Agendamento systemd + deploy (discharges-scheduler.sh, units, README)
```

---

## 11. Anti-padrões PROIBIDOS

- ❌ Importar `pontelo/` ou `from source_system import config` (use o bridge module do SIRHOSP)
- ❌ Usar o ID `_icon_img_20352` como seletor (use a classe CSS `.silk-new-internacao-altas-do-dia`)
- ❌ Criar `Patient` quando não encontrado no banco
- ❌ Sobrescrever `discharge_date` se já estiver preenchido
- ❌ Esquecer `from __future__ import annotations` em cada `.py`
- ❌ Hardcodar credenciais no script — sempre via CLI args
- ❌ Esquecer de adicionar o app ao `INSTALLED_APPS`
- ❌ Criar modelo `Discharge` ou migration (este slice NÃO tem modelo novo)
- ❌ Usar `subprocess.run` sem timeout
- ❌ Não rodar os gates de qualidade
- ❌ Modificar arquivos fora do escopo (ex.: mexer em `apps/census/`, `apps/patients/models.py`)
