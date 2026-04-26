# Design: admission-period-canonical-reconciliation

## Context

Atualmente, `Admission` possui unicidade por `(source_system, source_admission_key)`. Esse contrato presume estabilidade do identificador externo de internação.

No conector fonte (`path2.py`), o `admissionKey` observado pode variar entre execuções para a mesma internação (mesmo período), o que quebra a hipótese de estabilidade e induz duplicatas no espelho local.

## Design Goals

1. Garantir unicidade funcional por paciente+período.
2. Manter o mínimo de alterações (fase 1, monólito modular).
3. Preservar visibilidade de internações sem eventos.
4. Resolver duplicatas no fluxo normal de reconciliação (sem operação manual obrigatória).
5. Cobrir com testes unitários e integração de ciclo de worker.

## Business Rules (confirmed)

- Internação é única por `(patient, admission_start, admission_end)`.
- Dois episódios distintos com período idêntico para o mesmo paciente não existem.
- Internações sem eventos podem ser exibidas.
- Reruns devem convergir para a mesma internação (não duplicar).

## Decisions

### 1) Identidade canônica operacional por paciente+período

No `upsert_admission_snapshot`, a reconciliação deve seguir esta ordem:

1. match por `source_admission_key` (quando existir e for consistente);
2. fallback por `(patient, admission_date, discharge_date)`;
3. criação apenas quando não houver match por nenhuma das duas estratégias.

### 2) Consolidação oportunística de duplicatas do mesmo período

Se já existirem múltiplas admissões para o mesmo paciente/período:

- escolher uma admissão canônica de forma determinística:
  - maior `event_count`;
  - empate por menor `id`.
- reapontar `ClinicalEvent.admission` das duplicadas para a canônica;
- remover admissões duplicadas órfãs após merge.

### 3) `source_admission_key` passa a ser metadado

`source_admission_key` permanece armazenado e útil para rastreabilidade, mas não é mais tratado como única âncora confiável para reconciliação funcional.

### 4) Sem migração retroativa dedicada

Não será criado job/migração específica de saneamento em lote. A consolidação ocorrerá no próprio fluxo de snapshot (admissions capture/upsert), atendendo o cenário de desenvolvimento atual.

## Risks and Mitigations

### Risco: merge indevido de admissões

Mitigação: regra explícita de negócio validada (período idêntico nunca representa admissões distintas para o mesmo paciente) + testes de regressão.

### Risco: perda de vínculo de eventos

Mitigação: teste cobrindo reapontamento de eventos para admissão canônica antes da remoção de duplicadas.

### Risco: alteração de contadores `created/updated`

Mitigação: manter contrato de retorno explícito em testes unitários de `upsert_admission_snapshot`.

## Validation Strategy

- Unit tests (serviço de ingestão):
  - não criar duplicata quando chave externa muda mas período é igual;
  - consolidar duplicadas existentes preservando eventos.
- Integration tests (worker lifecycle):
  - reruns com snapshot de mesma internação e chaves instáveis não aumentam cardinalidade de `Admission`.
- Gates oficiais em container conforme `AGENTS.md`.

## Slice Strategy (overview)

- **S1**: Reconciliação canônica por período (prevenção de novas duplicatas).
- **S2**: Consolidação de duplicadas existentes + preservação de eventos.
- **S3**: Regressão de worker/rerun e hardening do contrato observável.
