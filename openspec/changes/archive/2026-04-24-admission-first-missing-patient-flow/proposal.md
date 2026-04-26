
# Change Proposal: admission-first-missing-patient-flow

## Why

O fluxo operacional planejado para o SIRHOSP é orientado por internações conhecidas no sistema fonte. Hoje, quando a busca em `/patients/` não encontra paciente no espelho local, o usuário perde o caminho principal de trabalho e não recebe a ação imediata de sincronizar internações, gerando regressão de produto e desalinhamento com o objetivo clínico-operacional.

## What Changes

- Restaurar e formalizar o fluxo **admission-first** para paciente ausente no banco local:
  - busca em `/patients/` sem resultado deve oferecer ação imediata para sincronizar internações do registro informado;
  - extração por período permanece disponível como ação secundária e contextual.
- Introduzir etapa explícita de descoberta/sincronização de internações antes da escolha de extração de evoluções.
- Adicionar tela de seleção de internação após sincronização, com ação principal para sincronizar a internação completa (admission_date até discharge_date ou hoje) e ação secundária para janela customizada.
- Proibir extração de evoluções quando não houver internações conhecidas para o registro informado (sem fallback por período nesse cenário).
- Preservar semântica atual do pipeline:
  - captura de snapshot de internações;
  - extração de evoluções por janela;
  - associação determinística evento → internação.
- Formalizar em especificação e testes a política de fragmentação de janelas longas em chunks operacionais (máximo de 15 dias por chunk), preservando compatibilidade com o limite do sistema fonte.

## Capabilities

### New Capabilities

- _(none)_

### Modified Capabilities

- `services-portal-navigation`: fluxo de recuperação quando paciente não é encontrado, com CTA primária de sincronização de internações e navegação para seleção de internação.
- `evolution-ingestion-on-demand`: regras de orquestração admission-first para paciente ausente localmente, seleção de internação e bloqueio de extração sem internação.
- `patient-admission-mirror`: sincronização explícita de catálogo de internações como operação principal do caso de uso de paciente ausente.
- `ingestion-run-observability`: visibilidade operacional para runs de sincronização de internações e runs de sincronização de internação completa/período contextual.

## Impact

- **Portal (Django templates/views)**: ajuste do estado "nenhum paciente encontrado" em `/patients/`, nova navegação para sincronização/seleção de internações e manutenção de `/ingestao/criar/` como fluxo secundário contextual.
- **Ingestion app**: ampliação de contratos de criação de run (tipo de run e contexto de internação), etapas de worker para admission-first e validações de pré-condição (não extrair sem internação).
- **Domínio de pacientes/internações**: reforço de uso do espelho de internações como fonte de decisão operacional para extração.
- **Automação Playwright (`path2.py`)**: manutenção da estratégia de chunking existente (15 dias) com cobertura de testes/regressão explícita.
- **Testes e artefatos OpenSpec**: novos testes unitários/integrados para jornada completa e atualização de docs/tasks/slice-prompts.
