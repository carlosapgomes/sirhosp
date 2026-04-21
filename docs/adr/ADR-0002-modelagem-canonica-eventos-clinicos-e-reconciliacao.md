# ADR-0002 — Modelagem canônica de eventos clínicos com reconciliação por chave externa

## Status

Accepted

## Contexto

O SIRHOSP precisa espelhar dados clínicos do sistema fonte hospitalar em um banco paralelo read-only para busca textual, consulta e resumos institucionais. O primeiro fluxo de alto valor é a ingestão de evoluções clínicas (daily notes), com vínculo consistente a pacientes e internações.

Os principais desafios identificados foram:

- o sistema fonte não expõe uma chave técnica estável de paciente para o scraping
- ingestões sob demanda podem repetir janelas de tempo, exigindo idempotência
- o mesmo evento clínico pode ser revisado no sistema fonte, exigindo detecção de mudança de conteúdo
- timestamps do sistema fonte não possuem offset de timezone
- o volume inicial justifica um modelo canônico único com extensão posterior por tipo documental

## Decisão

Adotar a seguinte arquitetura de dados para a fundação clínica do SIRHOSP:

### 1. Modelo canônico centrado em `ClinicalEvent`

Uma tabela única de eventos com colunas fortes para dados comuns (`happened_at`, `signed_at`, `author_name`, `profession_type`, `content_text`, `signature_line`) e `raw_payload_json` para preservação do bruto de auditoria. Tabelas filhas especializadas (ex: `DailyNote`) serão criadas somente quando houver campos/regras exclusivos relevantes.

### 2. Chave externa de internação baseada em `admissionKey`

Tratar `source_admission_key` como identificador externo principal da internação, com unicidade `(source_system, source_admission_key)`. A escolha é baseada em testes práticos que mostraram estabilidade dessa chave entre sessões de scraping.

### 3. Identidade de paciente por camadas

Adotar `patient_source_key` textual como chave principal inicial (registro atual no sistema fonte), com estratégia de reconciliação futura por prioridade:

1. CNS quando disponível e confiável.
2. CPF quando disponível e confiável.
3. Combinação de atributos demográficos (`nome`, `gênero`, `data_nascimento`, `nome_mae`) para reconciliação assistida.

O MVP utiliza `patient_source_key` + `source_system` com unicidade garantida por constraint.

### 4. Idempotência por `event_identity_key` + `content_hash`

Deduplicação por identidade lógica do evento (SHA-256 de `source_system|admission_key|happened_at|author_name`) e hash de conteúdo (SHA-256 de `content_text`) para detectar revisões. Ingestões repetidas com mesma identidade e mesmo hash são ignoradas; com hash diferente, uma nova versão é registrada.

### 5. Registro operacional por `IngestionRun`

Cada execução registra parâmetros, status, métricas e erros, com referência nos eventos ingeridos para observabilidade e auditoria.

### 6. Full Text Search em coluna canônica

FTS implementada diretamente em `content_text` com índice GIN (PostgreSQL) e fallback `icontains` (SQLite/desenvolvimento). Filtros compostos por paciente, internação, período e tipo profissional.

### 7. Histórico de identificadores (`PatientIdentifierHistory`)

Registro de mudanças em chaves e atributos do paciente desde o slice 1, para rastreabilidade longitudinal em uso jurídico e administrativo.

### 8. Normalização de timezone

Timestamps sem offset do sistema fonte são normalizados para timezone institucional (`America/Sao_Paulo`) e persistidos como timezone-aware.

### 9. Normalização de nome do paciente

Como o sistema fonte já entrega nome em caixa alta e sem diacríticos, o MVP aplica apenas higiene mínima (`trim` e colapso de espaços), preservando valor bruto para auditoria.

## Alternativas Consideradas

### Alternativa A — Tabela filha `DailyNote` dedicada desde o início

**Vantagens:** estrutura especializada imediata.
**Desvantagens:** custo de evolução precoce sem necessidade; payload atual de evolução é predominantemente textual sem estrutura clínica especializada.
**Motivo para não escolher:** não justificado pelo perfil dos dados atuais.

### Alternativa B — Modelo JSONB puro sem colunas canônicas

**Vantagens:** flexibilidade máxima.
**Desvantagens:** pior ergonomia para busca, FTS, consultas e governança.
**Motivo para não escolher:** compromete funcionalidade central do sistema (busca textual operacional).

### Alternativa C — Relacionar paciente por nome/período

**Vantagens:** não depende de chaves externas.
**Desvantagens:** alto risco de colisão entre homônimos e erros clínicos.
**Motivo para não escolher:** risco inaceitável para uso institucional.

### Alternativa D — Deduplicar por timestamp apenas

**Vantagens:** simplicidade.
**Desvantagens:** insuficiente diante de assinaturas e textos semelhantes no mesmo horário.
**Motivo para não escolher:** não garante idempotência adequada.

### Alternativa E — FTS direto em JSONB (`payload->>'content'`)

**Vantagens:** não requer coluna separada.
**Desvantagens:** mais frágil para evolução e tuning; dificulta queries operacionais.
**Motivo para não escolher:** coluna canônica simplifica queries e manutenção.

## Consequências

### Positivas

- idempotência garantida para ingestões repetidas
- rastreabilidade completa da origem (payload bruto + run de ingestão)
- detecção automática de revisões de conteúdo
- busca textual operacional com filtros compostos
- base sólida para expansão futura (prescrições, ficha operatória)
- simplicidade operacional compatível com fase 1 (sem Celery/Redis)

### Negativas / Trade-offs

- modelo canônico único pode exigir refatoração quando tipos documentais especializados surgirem (mitigado por `raw_payload_json` e critério de "promoção para tabela especializada")
- dependência de estabilidade de `source_admission_key` do sistema fonte (mitigado por campos de reconciliação)
- timestamps sem offset exigem configuração correta do timezone institucional

## Artefatos decorrentes

- modelos Django: `Patient`, `Admission`, `PatientIdentifierHistory`, `ClinicalEvent`, `IngestionRun`
- serviço de ingestão em memória com upsert e dedup
- serviço de busca FTS com filtros operacionais
- views de navegação (lista de internações, timeline com filtros)
- management command `ingest_evolutions`
- constraints de unicidade: `uq_patient_src`, `uq_adm_src`, `uq_evt_identity`
- índice FTS GIN em `content_text`

## Referências

- `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/design.md`
- `openspec/changes/fundacao-modelo-eventos-e-ingestao-evolucoes/specs/`
