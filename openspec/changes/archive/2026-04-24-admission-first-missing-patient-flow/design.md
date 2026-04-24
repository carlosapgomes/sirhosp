<!-- markdownlint-disable MD013 -->

# Design: admission-first-missing-patient-flow

## Context

O SIRHOSP já possui:

- hub autenticado de pacientes (`/patients/`),
- extração sob demanda por registro+período (`/ingestao/criar/`),
- pipeline de worker com captura de snapshot de internações e associação determinística de eventos.

Após as últimas changes, a entrada principal para o caso "paciente não encontrado no espelho local" ficou incompleta no portal: o usuário vê apenas estado vazio, sem ação primária para sincronizar internações. Isso contraria a estratégia clínica do produto (tudo vinculado a internação) e aumenta fricção operacional.

Restrições e invariantes relevantes:

- fase 1 permanece monólito Django + PostgreSQL, sem Celery/Redis;
- execução assíncrona segue `IngestionRun` + `process_ingestion_runs`;
- evoluções do sistema fonte dependem de internação;
- não deve haver extração de evoluções sem internação conhecida;
- conector legado já fragmenta períodos longos em chunks de 15 dias.

## Goals / Non-Goals

**Goals:**

- Restaurar o fluxo admission-first para busca sem resultado em `/patients/`.
- Tornar "Sincronizar internações" a ação primária para paciente ausente localmente.
- Permitir seleção explícita de internação antes da sincronização de evoluções.
- Manter extração por período como ação secundária contextual.
- Preservar pipeline atual (snapshot + extração + associação determinística).
- Formalizar e validar a política de chunking operacional (15 dias por chunk).

**Non-Goals:**

- Não introduzir nova arquitetura assíncrona (Celery/Redis/filas externas).
- Não alterar o modelo clínico canônico de `ClinicalEvent`.
- Não reescrever integralmente o conector Playwright (`path2.py`).
- Não permitir fallback "extração por período" quando não há internações na fonte.

## Decisions

### 1) Estado de "não encontrado" em `/patients/` vira ponto de entrada operacional

**Decisão:** quando a busca não retornar pacientes e houver termo de busca válido, o portal exibirá:

- CTA primária: **Buscar/sincronizar internações** para o registro buscado;
- CTA secundária: **Ajustar período de extração** (somente após internações conhecidas).

**Racional:** reduz perda de fluxo e mantém consistência com o domínio (internação primeiro).

**Alternativas consideradas:**

- manter estado vazio com texto apenas → rejeitada por regressão de usabilidade;
- enviar direto para `/ingestao/criar/` como primário → rejeitada por priorizar período antes de internação.

### 2) Sincronização de internações como tipo explícito de run

**Decisão:** introduzir modo de execução para sincronização de catálogo de internações (admissions-only) em `IngestionRun`, sem extração de evoluções.

**Racional:** separa claramente descoberta operacional de internações do passo de sincronização de eventos; reaproveita worker atual sem nova infraestrutura.

**Alternativas consideradas:**

- sincronização síncrona na request HTTP → rejeitada (timeout/instabilidade do sistema fonte);
- criar tabela/worker separado → rejeitada por complexidade desnecessária na fase 1.

### 3) Seleção de internação antes da sincronização de evoluções

**Decisão:** após sincronização de internações bem-sucedida, o usuário é direcionado para lista de internações do paciente e escolhe uma internação para:

- ação principal: sincronizar internação completa (`admission_date` até `discharge_date` ou hoje);
- ação secundária: abrir `/ingestao/criar/` em modo contextual para recorte de período.

**Racional:** alinha operação humana ao modelo clínico e evita extrações desconectadas da internação.

**Alternativas consideradas:**

- autoescolher internação mais recente sem confirmação humana → rejeitada por risco clínico/operacional.

### 4) `/ingestao/criar/` torna-se rota secundária contextual

**Decisão:** manter `/ingestao/criar/` como tela de ajuste fino, pré-preenchida a partir de paciente/internação selecionados. Acesso sem contexto válido deve redirecionar para `/patients/` com mensagem orientativa.

**Racional:** preserva utilidade da tela sem competir com o fluxo principal admission-first.

### 5) Regra de bloqueio: sem internações, sem extração

**Decisão:** se a sincronização de internações retornar catálogo vazio, o sistema encerra o fluxo com status/mensagem clara e não oferece fallback para extração de evoluções.

**Racional:** reflete a regra de negócio confirmada: no sistema fonte, evoluções estão vinculadas a internações.

### 6) Política de chunking vira contrato explícito de operação

**Decisão:** formalizar em spec/testes que janelas longas são fragmentadas em chunks de no máximo 15 dias (com sobreposição definida), preservando tolerância ao limite operacional do sistema fonte.

**Racional:** evitar regressão silenciosa do comportamento já implementado em `path2.py`.

## Risks / Trade-offs

- **[Risco] aumento de estados de run (descoberta vs extração) pode confundir operação** → **Mitigação:** labels explícitos no status e mensagens de próximo passo.
- **[Risco] usuário tentar usar `/ingestao/criar/` sem contexto** → **Mitigação:** redirecionamento guiado para `/patients/`.
- **[Risco] sincronização de internações demorar no sistema fonte** → **Mitigação:** manter processamento assíncrono com observabilidade de status/erro.
- **[Trade-off] mais passos na UI (buscar → sincronizar → escolher internação)** → ganho de precisão clínica e redução de extração equivocada.

## Migration Plan

1. Implementar contrato/specs admission-first e cobertura de testes RED para estado "não encontrado".
2. Adicionar fluxo de sincronização de internações (run admissions-only) com status dedicado.
3. Integrar redirecionamento pós-sincronização para seleção de internação.
4. Adaptar `/ingestao/criar/` para modo secundário contextual e bloquear acesso solto.
5. Incluir testes de regressão de chunking (intervalos > 29 dias) para garantir fragmentação em chunks <= 15 dias.
6. Atualizar docs de operação e prompts de slice.

Rollback: como não há mudança arquitetural de infra, rollback segue reversão de commits e restauração do fluxo anterior de navegação.

## Open Questions

- O status page deve exibir um "próximo passo" clicável por tipo de run (ex.: após admissions-only, botão "Selecionar internação")?
- Manter a opção de período customizado visível na lista de internações ou apenas dentro de `/ingestao/criar/` contextual?
