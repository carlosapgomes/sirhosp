# Change Proposal: fundacao-modelo-eventos-e-ingestao-evolucoes

## Why

A diretoria, qualidade, jurídico e gestão de prontuários precisam de acesso rápido a dados clínicos pesquisáveis e resumíveis, o que o prontuário fonte não oferece hoje. Este change cria a fundação do banco paralelo read-only para ingestão confiável de evoluções clínicas com vínculo robusto a paciente e internação.

## What Changes

- Definir modelo canônico inicial para espelhamento clínico com `Patient`, `Admission`, `ClinicalEvent` e `IngestionRun`.
- Implementar ingestão idempotente de evoluções clínicas (daily notes) sem dependência de arquivo-fonte, suportando execução em memória.
- Adotar chave externa de internação (`source_admission_key`, derivada de `admissionKey`) com estratégia defensiva de reconciliação.
- Implementar deduplicação por `event_identity_key` + `content_hash` para evitar duplicatas e permitir versionamento quando conteúdo mudar.
- Preservar payload bruto da extração para auditoria (`raw_payload_json`) e manter colunas canônicas para consulta/FTS.
- Habilitar Full Text Search em `content_text` com filtros por paciente, internação, período e tipo profissional.

Escopo desta fase:

- ingestão de evoluções clínicas e cadastro básico de pacientes/internações vinculadas.

Não-objetivos desta fase:

- ingestão de prescrições, ficha operatória e demais documentos;
- SSO/LDAP, desidentificação, exportação avançada;
- UI final completa para todos os setores.

Riscos principais:

- instabilidade futura de chaves externas do sistema fonte;
- mudanças de UI no scraping;
- ambiguidades de timezone em timestamps sem offset.

## Capabilities

### New Capabilities

- `patient-admission-mirror`: Espelhamento read-only de pacientes e internações com identificadores externos estáveis e reconciliação segura.
- `clinical-event-ledger`: Registro canônico de eventos clínicos com rastreabilidade de origem, idempotência e suporte a revisão de conteúdo.
- `evolution-ingestion-on-demand`: Ingestão sob demanda de evoluções por paciente e período, com execução em memória e vínculo automático a paciente/internação.
- `clinical-event-full-text-search`: Busca textual clínica com índice FTS e filtros operacionais para uso por gestão, qualidade e jurídico.

### Modified Capabilities

- *(nenhuma nesta mudança inicial)*

## Impact

- **Domínio/Dados**: novas entidades de núcleo clínico e constraints de deduplicação.
- **Ingestão**: novo pipeline de upsert para paciente/internação/evento via management commands.
- **Busca**: índices PostgreSQL para FTS e filtros combinados.
- **Operação**: execução manual e agendada com rastreamento por `IngestionRun`, mantendo simplicidade da fase 1 (sem Celery/Redis).
- **Governança**: base para futura expansão a prescrições, documentos operatórios e resumos por período com rastreabilidade.
