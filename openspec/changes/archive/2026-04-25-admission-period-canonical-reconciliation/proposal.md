# Change Proposal: admission-period-canonical-reconciliation

## Why

No estado atual, a lista de internações pode exibir duplicatas do mesmo período para o mesmo paciente quando o conector retorna `admissionKey` volátil (ex.: `InternacaoVO@<hash-diferente-por-run>`).

Impacto observado:

- múltiplas linhas para a mesma internação (mesmo período) no portal;
- runs falhos com 0 eventos permanecem como entradas separadas;
- novo run bem-sucedido pode criar mais uma entrada, em vez de convergir para a internação já existente.

Decisões de negócio confirmadas:

1. para o mesmo paciente, a internação é única por período (entrada/alta);
2. não existe caso válido de duas internações diferentes com período idêntico para o mesmo paciente;
3. internações sem eventos podem continuar visíveis;
4. reruns para o mesmo período devem convergir para uma única internação canônica;
5. sem necessidade de compatibilidade retroativa de produção (projeto ainda sem implantação).

## What Changes

- Definir reconciliação canônica de internação por paciente + período (`admission_start`, `admission_end`).
- Tratar `source_admission_key` como metadado de origem (não como identidade principal confiável).
- Impedir criação de novas duplicatas em reruns com chave volátil.
- Consolidar duplicatas já existentes do mesmo paciente/período durante o upsert de snapshot (reapontando eventos para a canônica).
- Formalizar o contrato em OpenSpec para evitar regressões futuras.

## Non-Goals

- Não introduzir nova arquitetura (Celery/Redis/microserviços).
- Não alterar UX para ocultar internações sem eventos.
- Não criar migração de dados massiva offline dedicada (consolidação ocorre no fluxo de reconciliação do snapshot).
- Não alterar pipeline clínico além da reconciliação de internações.

## Capabilities

### Modified Capabilities

- `patient-admission-mirror`
- `evolution-ingestion-on-demand`

## Impact

- Elimina duplicidade de internações na navegação do paciente para casos de chave externa instável.
- Mantém histórico operacional de runs, sem poluir o catálogo clínico de admissões.
- Aumenta previsibilidade da associação admissão/evento e reduz ruído operacional.
