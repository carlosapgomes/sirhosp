# Tasks: extract-discharges

## 1. Slice S1 — Script de extração adaptado + app `discharges`

**Arquivos (7)**: `automation/source_system/discharges/__init__.py`, `automation/source_system/discharges/extract_discharges.py`, `apps/discharges/__init__.py`, `apps/discharges/apps.py`, `apps/discharges/services.py`, `apps/discharges/management/commands/__init__.py`, `apps/discharges/management/commands/extract_discharges.py`

**Arquivo modificado**: `config/settings.py` (adicionar `apps.discharges.DischargesConfig` ao `INSTALLED_APPS`)

TDD: RED → testa `process_discharges()` com fixtures; GREEN → implementa serviço + comando.

- [ ] 1.1 Criar `automation/source_system/discharges/__init__.py` (vazio)
- [ ] 1.2 Criar `automation/source_system/discharges/extract_discharges.py` — adaptar de `pontelo/busca-altas-hoje.py`:
  - Importar helpers do bridge module (`automation/source_system/source_system.py`)
  - Trocar seletor de `#_icon_img_20352` para `.silk-new-internacao-altas-do-dia`
  - CLI: `--headless`, `--output-dir`, `--source-url`, `--username`, `--password`
  - Output JSON com timestamp
- [ ] 1.3 Criar `apps/discharges/__init__.py` e `apps/discharges/apps.py`
- [ ] 1.4 Criar `apps/discharges/services.py` com `process_discharges(patients)`:
  - Match por `patient_source_key` → skip se não encontrado
  - Match de admission: `data_internacao` exato → fallback mais recente sem `discharge_date`
  - Idempotente: pula admissions já com `discharge_date`
  - Retorna dict com métricas: `total_pdf`, `patient_not_found`, `admission_not_found`, `already_discharged`, `discharge_set`
- [ ] 1.5 Criar `apps/discharges/management/commands/extract_discharges.py`:
  - Mesmo padrão do `extract_census`: subprocess + `IngestionRun` + `IngestionRunStageMetric`
  - `intent="discharge_extraction"`
  - Timeout de 10 minutos
- [ ] 1.6 Adicionar `"apps.discharges.DischargesConfig"` ao `INSTALLED_APPS` em `config/settings.py`
- [ ] 1.7 Criar `tests/unit/test_discharge_service.py` com testes para `process_discharges()`
- [ ] 1.8 Rodar `./scripts/test-in-container.sh check`, `unit`, `lint` — confirmar verde

## 2. Slice S2 — Agendamento systemd + deploy

**Arquivos (3)**: `deploy/discharges-scheduler.sh`, `deploy/systemd/sirhosp-discharges.service`, `deploy/systemd/sirhosp-discharges.timer`

**Arquivo modificado**: `deploy/README.md` (documentar instalação)

- [ ] 2.1 Criar `deploy/discharges-scheduler.sh` — script bash que executa o management command no container
- [ ] 2.2 Criar `deploy/systemd/sirhosp-discharges.service` — unit oneshot
- [ ] 2.3 Criar `deploy/systemd/sirhosp-discharges.timer` — OnCalendar 11:00, 19:00, 23:55
- [ ] 2.4 Atualizar `deploy/README.md` com instruções de instalação das units e entrada no troubleshooting
- [ ] 2.5 Rodar `markdownlint-cli2` no `deploy/README.md`

## 3. Validação final

- [ ] 3.1 Rodar `./scripts/test-in-container.sh quality-gate` e garantir tudo verde
- [ ] 3.2 Rodar `./scripts/markdown-lint.sh` nos arquivos .md alterados/criados
- [ ] 3.3 Verificar visualmente que o dashboard mostra altas > 0 após primeira execução real
