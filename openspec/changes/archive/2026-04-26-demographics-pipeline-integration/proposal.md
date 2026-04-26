# Change Proposal: demographics-pipeline-integration

## Why

O projeto já possui três ativos prontos e testados para extração de dados
demográficos detalhados dos pacientes:

1. **Script Playwright** `automation/source_system/patient_demographics/extract_patient_demographics.py`
   — faz scraping de 35+ campos da ficha cadastral do paciente (nome da mãe,
   data de nascimento, CNS, CPF, endereço, telefones, etc.)

2. **Função de upsert** `upsert_patient_demographics()` em
   `apps/ingestion/services.py` — recebe o dict de demográficos, mapeia para
   campos do modelo `Patient` e persiste com política de overwrite seguro.

3. **Modelo `Patient`** completo em `apps/patients/models.py` — 30+ campos
   demográficos (`mother_name`, `date_of_birth`, `cns`, `cpf`, `gender`,
   `street`, `city`, etc.)

Porém esses ativos **não estão conectados ao pipeline**. Hoje:

- O `process_census_snapshot` cria pacientes **apenas com `name`** (dado que
  a tela de censo só expõe setor, leito, prontuário, nome e especialidade).
- O worker `process_ingestion_runs` nunca chama `upsert_patient_demographics()`.
- Nenhum `IngestionRun` com intent de demografia é enfileirado.

**Consequência**: todo paciente no banco tem `mother_name=""`, `date_of_birth=NULL`,
`cns=""`, etc. A reconciliação automática de duplicatas (planejada desde a ADR-0002)
permanece bloqueada.

## What Changes

### 1. Intent `demographics_only` no worker

- Nova função `queue_demographics_only_run()` em `apps/ingestion/services.py`
- Novo método `_process_demographics_only()` no worker `process_ingestion_runs.py`
  que executa `extract_patient_demographics.py` como subprocess e chama
  `upsert_patient_demographics()` com o JSON resultante
- Segue o mesmo padrão de subprocess + leitura de JSON do `extract_census`

### 2. Enfileiramento automático a partir do censo

- `process_census_snapshot()` passa a enfileirar **duas** runs para cada
  paciente processado: `admissions_only` (já existente) + `demographics_only`
  (novo)
- Métricas expandidas para reportar `demographics_runs_enqueued`

### 3. Testes

- Testes unitários para `queue_demographics_only_run()`
- Testes unitários para `_process_demographics_only()` com mock de subprocess
- Testes de integração: `process_census_snapshot()` enfileira ambos os intents
- Atualização dos testes existentes de `process_census_snapshot` para
  verificar o novo comportamento

## Non-Goals

- Não criar management command de backfill para pacientes existentes (isso
  será um change separado ou slice opcional)
- Não extrair demográficos durante `admissions_only` ou `full_sync`
  (mantém intents independentes)
- Não introduzir detecção automática de duplicatas (continua adiado para
  change futuro com dados demográficos completos)
- Não alterar o script Playwright de extração (já funciona)
- Não alterar `upsert_patient_demographics()` (já implementada e testada)

## Capabilities

### Added Capabilities

- `patient-demographics-ingestion`: extração e persistência dos dados
  demográficos completos de paciente, disparada automaticamente pelo censo

### Modified Capabilities

- `census-snapshot-mirror`: `process_census_snapshot()` agora também
  enfileira runs `demographics_only`

## Impact

- **Operacional**: pacientes descobertos pelo censo passam a ter dados
  demográficos completos automaticamente, sem ação manual
- **Cobertura**: todos os campos do modelo `Patient` passam a ser preenchidos
- **Reconciliação futura**: dados como `mother_name`, `date_of_birth`, `cns`,
  `cpf` ficam disponíveis para detecção automática de duplicatas (change
  futuro)
- **Custo**: +1 sessão Playwright (~30s) por paciente a cada execução do
  censo. Com ~170 pacientes/dia, o worker processa sequencialmente sem
  sobrecarga significativa
