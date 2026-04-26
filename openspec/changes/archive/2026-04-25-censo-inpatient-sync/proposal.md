# Change Proposal: censo-inpatient-sync

## Why

O SIRHOSP já extrai e persiste dados clínicos por paciente (evoluções, prescrições, demografia), mas **não tem mecanismo para descobrir QUAIS pacientes existem no hospital**. Hoje, toda ingestão depende de um operador humano informar manualmente um prontuário.

O sistema fonte (AGHU/TASY) oferece a tela de **Censo Diário de Pacientes**, que lista todos os pacientes internados no momento, por setor e leito, com prontuário, nome e especialidade. Há um MVP funcional (`busca_todos_pacientes_slim.py` no projeto `pontelo/`) que faz scraping dessa tela completa, incluindo paginação por setor.

**Sem essa descoberta automatizada de pacientes**, o SIRHOSP permanece reativo, dependente de entrada manual.

Além disso, não há visibilidade de ocupação de leitos (vagos, reservados, em manutenção), informação valiosa para o dashboard operacional da diretoria.

## What Changes

### 1. Conector de censo integrado

- Copiar/adaptar `busca_todos_pacientes_slim.py` para `automation/source_system/current_inpatients/`
- Integrar ao padrão de subprocess do projeto (igual `path2.py`)
- Geração de CSV + JSON padronizados no diretório `downloads/`

### 2. App `census` com tabela de snapshot

- Modelo `CensusSnapshot` armazenando cada linha do censo (setor, leito, prontuário, nome, especialidade, status do leito)
- Classificação automática de status: `occupied`, `empty`, `maintenance`, `reserved`, `isolation`
- Histórico preservado (uma linha por execução)

### 3. Management command `extract_census`

- Executa o script Playwright, faz parse do CSV gerado, classifica leitos, popula `CensusSnapshot`
- Pode ser chamado via `systemd timer` ou manualmente

### 4. Processador de censo: descoberta de novos pacientes

- Serviço que lê o snapshot mais recente
- Para cada prontuário ocupado: cria `Patient` se não existir + enfileira `IngestionRun` com `intent="admissions_only"`
- Para pacientes já existentes: atualiza `name` se mudou + enfileira `admissions_only`
- Ignora leitos não-ocupados (sem prontuário)

### 5. Worker: auto-full_sync da admissão mais recente

- Após processar `admissions_only`, o worker detecta a admissão com `admission_date` mais recente
- Enfileira automaticamente um `IngestionRun` com `intent="full_sync"` para extrair evoluções daquela admissão
- **Padronização**: para todo paciente novo, o sistema captura TODAS as admissões, mas só extrai evoluções da internação atual

### 6. Página de visualização de leitos

- Nova página `/beds/` autenticada: tabela agrupada por setor, com contagem de leitos ocupados/vagos/reservados/manutenção
- Card no dashboard futuro apontando para essa página

### 7. Merge de pacientes (ferramenta administrativa)

- Função `merge_patients(keep, merge)` para consolidar pacientes duplicados (ex.: paciente com registro antigo e novo)
- Ação no Django Admin para operador executar merge manual
- **Sem detecção automática** neste change (adiado para quando houver demografia completa)

## Non-Goals

- Não introduzir detecção automática de duplicatas (adiado para change futuro com dados demográficos)
- Não criar dashboard analítico completo (apenas a página de leitos + placeholder de card)
- Não alterar fluxo de extração de evoluções por paciente
- Não criar UI de busca nova
- Não introduzir Celery/Redis

## Capabilities

### Added Capabilities

- `census-snapshot-mirror`: extração, armazenamento e processamento do censo diário de pacientes internados
- `bed-status-view`: visualização de ocupação de leitos por setor e status

### Modified Capabilities

- `patient-admission-mirror`: worker agora auto-enfileira full_sync da admissão mais recente após admissions_only
- `evolution-ingestion-on-demand`: suporta enfileiramento automático pós-censo

## Impact

- **Operacional**: elimina necessidade de entrada manual de prontuários; sistema descobre pacientes automaticamente
- **Cobertura**: garante que todos os internados sejam espelhados, não só os consultados manualmente
- **Dashboard**: fornece dados de ocupação de leitos para diretoria/qualidade
- **Manutenção**: ferramenta de merge manual resolve duplicatas inevitáveis de troca de registro
