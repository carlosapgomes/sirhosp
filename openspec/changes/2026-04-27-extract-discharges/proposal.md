# Change Proposal: extract-discharges

## Why

O dashboard do SIRHOSP já exibe o card "Altas (24h)" com query real contra
`Admission.discharge_date`, mas o campo `discharge_date` nunca é populado de
forma sistemática. Ele só é capturado como subproduto passivo do scraping de
admissions (`admissions_only`), e apenas se o paciente for re-sincronizado
**após** a alta. O resultado é que o card de altas mostra zero.

O sistema fonte hospitalar oferece uma página específica **"Altas do Dia"**
que lista todos os pacientes que receberam alta na data atual. Já existe um
script funcional (`pontelo/busca-altas-hoje.py`) que faz scraping dessa página,
baixa o PDF gerado e extrai a tabela de pacientes com PyMuPDF.

**Sem um mecanismo dedicado de captura de altas**, o indicador de altas no
dashboard permanece inútil e a diretoria não tem visibilidade de quantos
pacientes saíram do hospital nas últimas 24 horas.

## What Changes

### 1. Script de extração integrado

- Adaptar `pontelo/busca-altas-hoje.py` para `automation/source_system/discharges/extract_discharges.py`
- Usar o bridge module `automation/source_system/source_system.py` (mesmo padrão do `extract_census.py`)
- Seletor do ícone migrado de `id` instável para classe CSS estável: `.silk-new-internacao-altas-do-dia`
- Output: JSON padronizado com timestamp em `downloads/`

### 2. App `discharges` com serviço de processamento

- App Django `apps/discharges/` (sem modelos próprios nesta fase)
- Serviço `process_discharges()` que:
  - Lê a lista de pacientes do JSON
  - Para cada paciente: localiza `Patient` por `patient_source_key` (prontuário)
  - Se paciente não encontrado → **skip** (não cria paciente novo)
  - Localiza `Admission` com match por `data_internacao` (do PDF)
  - Fallback: se match exato falhar, pega a admission mais recente sem `discharge_date`
  - Seta `discharge_date = timezone.now()` (a data da alta é "hoje")
  - Se já tinha `discharge_date` → conta como `already_discharged` e pula

### 3. Management command `extract_discharges`

- Executa o script Playwright via subprocess
- Registra `IngestionRun` com `intent="discharge_extraction"`
- Métricas de estágio (`IngestionRunStageMetric`)
- Reporta resultado: quantos pacientes processados, quantas altas setadas, quantos skips

### 4. Agendamento systemd

- Timer disparando 3x/dia: **11:00**, **19:00**, **23:55**
- Script `deploy/discharges-scheduler.sh` (mesmo padrão do `census-scheduler.sh`)
- Units `sirhosp-discharges.service` e `sirhosp-discharges.timer`

### 5. Atualização do `deploy/README.md`

- Documentar instalação das units de discharges
- Atualizar tabela de troubleshooting

## Non-Goals

- Não criar modelo novo no banco (usa `Patient` e `Admission` existentes)
- Não alterar a query `altas_24h` do dashboard (já existe e funciona)
- Não implementar diff de censos consecutivos como fallback
- Não criar pacientes novos quando não encontrados (segurança)
- Não alterar o fluxo de `admissions_only` existente
- Não introduzir Celery/Redis

## Capabilities

### Added Capabilities

- `discharge-extraction`: extração diária da lista de altas do sistema fonte,
  atualização de `discharge_date` nas admissões correspondentes, e visibilidade
  do indicador de altas no dashboard

### Modified Capabilities

- Nenhuma — este change adiciona funcionalidade nova sem modificar specs existentes

## Impact

- **Dashboard**: card "Altas (24h)" passa a exibir dados reais em vez de zero
- **Operacional**: visibilidade diária de quantos pacientes saíram do hospital
- **Automação**: 3 execuções diárias sem intervenção manual
- **Carga no sistema fonte**: 3 acessos rápidos por dia (login + clique + download PDF)
