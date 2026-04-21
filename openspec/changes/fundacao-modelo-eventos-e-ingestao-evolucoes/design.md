# Design: fundacao-modelo-eventos-e-ingestao-evolucoes

## Context

O SIRHOSP está em fase de fundação arquitetural para operar como banco paralelo institucional de consulta, pesquisa e resumo clínico. O primeiro fluxo de alto valor é a ingestão de evoluções clínicas por scraping, com vínculo consistente a pacientes e internações, sem alterar o sistema fonte.

Restrições e contexto operacional:

- monólito modular Django + PostgreSQL;
- jobs via management commands com systemd timers/cron;
- sem Celery/Redis na fase 1;
- ingestão pode ocorrer sob demanda e em memória (sem artefato JSON em disco);
- dados devem ser rastreáveis para uso assistencial-administrativo e jurídico.

Stakeholders primários:

- diretoria hospitalar;
- gestão de prontuários;
- qualidade/segurança do paciente;
- jurídico institucional.

## Goals / Non-Goals

**Goals:**

- Estabelecer modelo canônico de dados para paciente, internação e evento clínico.
- Garantir idempotência e deduplicação de eventos durante ingestões repetidas.
- Preservar rastreabilidade completa da origem (payload bruto + run de ingestão).
- Permitir busca textual de evoluções com desempenho operacional (FTS).
- Manter simplicidade operacional compatível com fase 1.

**Non-Goals:**

- Implementar todos os tipos documentais (prescrição, ficha operatória etc.) nesta mudança.
- Construir fluxos avançados de autorização setorial ou auditoria de acesso por paciente.
- Introduzir infraestrutura distribuída de filas/workers.
- Definir UI final completa para todos os casos de uso da diretoria.

## Decisions

### 1) Modelo canônico centrado em `ClinicalEvent` (sem tabela filha `DailyNote` inicialmente)

**Decisão:** usar uma tabela canônica de eventos com colunas fortes para dados comuns (`happened_at`, `signed_at`, `author_name`, `profession_type`, `content_text`, `signature_line`) e `raw_payload_json` para preservação do bruto.

**Racional:** o payload atual de evolução é predominantemente textual, sem estrutura clínica especializada que justifique tabela filha já na fase inicial.

**Alternativas consideradas:**

- Tabela `DailyNote` dedicada desde já: descartada por custo de evolução precoce.
- Modelo JSONB puro: descartado por pior ergonomia para busca/consulta e governança.

### 2) Chave externa de internação baseada em `admissionKey` com proteção de reconciliação

**Decisão:** tratar `source_admission_key` como identificador externo principal da internação, com unicidade `(source_system, source_admission_key)`.

**Racional:** testes práticos mostraram estabilidade entre sessões; reduz ambiguidade de vínculo.

**Alternativas consideradas:**

- Relacionar por nome/período: descartado por risco de colisão e erros clínicos.
- Gerar chave interna sem persistir chave externa: descartado por perda de rastreabilidade.

### 3) Idempotência por `event_identity_key` + `content_hash`

**Decisão:** deduplicar por identidade lógica do evento e usar hash de conteúdo para detectar revisões.

**Racional:** ingestões sob demanda podem repetir janelas; o sistema precisa ser reexecutável sem duplicação.

**Alternativas consideradas:**

- Deduplicar por arquivo de origem: não aplicável ao fluxo em memória.
- Deduplicar só por timestamp: insuficiente diante de assinaturas/textos semelhantes.

### 4) Full Text Search em coluna canônica (`content_text`), não só no JSON

**Decisão:** criar FTS no texto canônico com índices apropriados e filtros compostos.

**Racional:** simplifica queries operacionais, melhora performance e reduz complexidade de manutenção.

**Alternativas consideradas:**

- FTS direto em JSONB (`payload->>'content'`): possível, porém mais frágil para evolução e tuning.

### 5) Registro operacional por `IngestionRun`

**Decisão:** cada execução registra parâmetros, status, métricas e erros com referência nos eventos ingeridos.

**Racional:** facilita observabilidade, troubleshooting e auditoria de execução sem complexidade distribuída.

### 6) Estratégia de identidade de paciente e reconciliação

**Decisão:** adotar `patient_source_key` textual como chave principal inicial
(registro atual no sistema fonte), com fallback e reconciliação por prioridade,
coletando por scraping todos os identificadores disponíveis:

1. CNS quando disponível e confiável.
2. CPF (número fiscal) quando disponível e confiável.
3. Combinação de atributos demográficos para reconciliação assistida
   (`nome`, `gênero`, `data_nascimento`, `nome_mae`).

**Decisão complementar de normalização de nome:** como o sistema fonte já
entrega nome em caixa alta e sem diacríticos, o MVP não aplicará normalização
linguística adicional. Será aplicada apenas higiene mínima (`trim` e
colapso de espaços), preservando valor bruto para auditoria.

**Racional:** o sistema fonte não expõe, neste momento, uma key técnica estável
de paciente para o scraping; a estratégia por camadas reduz risco de colisão
sem bloquear o MVP.

**Alternativas consideradas:**

- Usar somente nome/data de nascimento: descartado por risco elevado de
  homônimos.
- Exigir key técnica do sistema fonte antes de iniciar: descartado por
  inviabilizar o início operacional.

### 7) Histórico de identificadores no slice 1

**Decisão:** incluir `PatientIdentifierHistory` já no slice 1.

**Racional:** há ocorrência real de atualização de número de registro de paciente; sem histórico, o vínculo longitudinal ficaria frágil e potencialmente incorreto para uso jurídico e administrativo.

**Alternativas consideradas:**

- Postergar para slice 2: descartado por risco de perda de rastreabilidade logo na fundação.

### 8) Escopo MVP de consultas inclui FTS avançada

**Decisão:** a busca global por FTS com filtros avançados entra no MVP, junto da navegação por timeline de paciente/internação.

**Racional:** a necessidade institucional central é recuperar rapidamente informação clínica por texto e contexto; adiar FTS avançada reduziria valor imediato para diretoria, jurídico e qualidade.

**Diretriz de UX inicial:**

- Primeiro nível: lista de internações do paciente.
- Segundo nível: timeline da internação selecionada com filtro por tipo profissional (médica, enfermagem, fisioterapia, etc.).
- Exibição preferencial em lista vertical de cards (mobile friendly).

## Risks / Trade-offs

- **[Estabilidade futura de `source_admission_key`]** → Mitigação: manter campos de apoio para reconciliação (`patient_source_key`, período de internação, assinatura) e rotina de correção controlada.
- **[Timestamps sem timezone explícito]** → Mitigação: normalizar ingestão para timezone institucional (`America/Sao_Paulo`) e persistir timezone-aware.
- **[Mudanças no HTML/seletores de scraping]** → Mitigação: separar conectores por domínio e manter modo laboratório desacoplado de produção.
- **[Crescimento do escopo documental]** → Mitigação: critério explícito de “promoção para tabela especializada” quando houver campos/regras exclusivos relevantes.
- **[Trade-off de modelo canônico único]** → Mitigação: manter `raw_payload_json` e planejar extensões 1:1 quando necessário.

## Migration Plan

1. Criar entidades e constraints iniciais (`Patient`, `Admission`, `ClinicalEvent`, `IngestionRun`) e índices de FTS.
2. Implementar pipeline de ingestão de evoluções com upsert de paciente/internação e dedupe de evento.
3. Expor busca textual inicial com filtros essenciais.
4. Validar qualidade com `uv run python manage.py check`, testes relevantes, lint e mypy.
5. Habilitar execução sob demanda e preparar agendamento posterior via comandos existentes.

Rollback (se necessário):

- desativar comando de ingestão;
- manter dados já ingeridos somente leitura;
- reverter migrações em janela controlada se a mudança ainda não estiver em produção institucional.

## Open Questions

- Qual será o fluxo operacional para casos minoritários em que não haja `CNS`,
  `CPF` e `nome_mae` disponíveis simultaneamente para reconciliação segura?

## Implementation Status (S1–S4)

As decisões de design acima foram implementadas integralmente nos slices S1–S4:

### Artefatos implementados

- **Modelos Django:** `Patient`, `Admission`, `PatientIdentifierHistory` (apps/patients); `ClinicalEvent` (apps/clinical_docs); `IngestionRun` (apps/ingestion).
- **Constraints de unicidade:** `uq_patient_src`, `uq_adm_src`, `uq_evt_identity`.
- **Serviço de ingestão:** `apps/ingestion/services.py` — ingestão em memória com upsert de paciente/internação, dedup por `event_identity_key` + `content_hash`, registro em `IngestionRun`.
- **Serviço de busca FTS:** `apps/search/services.py` — FTS PostgreSQL (SearchVector/SearchRank) com fallback `icontains`; filtros por paciente, internação, período e tipo profissional.
- **Views de navegação:** `apps/patients/views.py` — lista de internações por paciente (`/patients/<id>/admissions/`), timeline da internação com filtro por tipo profissional (`/admissions/<id>/timeline/`).
- **Templates:** Bootstrap 5 mobile-friendly com cards para lista de internações e timeline.
- **Management command:** `ingest_evolutions` para execução via CLI.
- **Índice FTS GIN:** migração `0002_clinicalevent_fts_gin_index.py`.

### Cobertura de testes

- 96 testes unitários e de integração passando.
- Cobertura inclui: modelos, constraints, dedup, timezone, upsert, IngestionRun, busca FTS com filtros, views de navegação, filtros de profissão e regressão de casos de borda.

### Riscos mitigados

- `source_admission_key`: adotada como chave externa principal com validação prática.
- Timestamps sem offset: normalização para `America/Sao_Paulo` implementada.
- Instabilidade de scraping: separação por domínio (connectors vs portal) preservada.
