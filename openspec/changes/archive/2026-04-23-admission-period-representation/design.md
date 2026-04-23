<!-- markdownlint-disable MD013 -->
# Design: admission-period-representation

## Contexto

O conector Playwright já abre a listagem de internações para escolher as admissões que intersectam a janela solicitada. Porém, hoje o pipeline persiste principalmente evoluções e não trata explicitamente o catálogo completo de internações como artefato independente da janela.

## Objetivos

1. Separar semanticamente:
   - **catálogo de internações conhecidas**;
   - **cobertura de evoluções extraídas por janela**.
2. Garantir associação determinística de evento -> internação.
3. Expor no portal a diferença entre internação conhecida e internação com eventos.
4. Preservar implementação incremental com slices pequenos e testáveis.

## Decisões técnicas

### 1) Captura de internações como etapa explícita

Adicionar no conector fluxo para exportar snapshot de internações conhecidas do paciente (lista completa encontrada na tabela de internações), com campos mínimos:

- `admission_key` (obrigatório)
- `admission_start`
- `admission_end`
- `ward` (quando disponível; passado pode ficar vazio)
- `bed` (quando disponível; passado pode ficar vazio)

### 2) Semântica de falha da execução

- Se a etapa de captura de internações falhar: `run.status = failed`.
- Se internações foram capturadas/persistidas, mas evoluções falharem: manter internações persistidas e `run.status = failed`.
- Se internações foram capturadas e não houver evoluções na janela: `run.status = succeeded` com `events_processed=0`.

### 3) Upsert de Admission com política de atualização segura

- `ward`/`bed` só atualizam quando o valor novo é não vazio.
- Internações antigas sem `ward`/`bed` permanecem com campos vazios sem sobrescrever valores válidos existentes.

### 4) Associação determinística evento -> internação

Ordem de resolução:

1. `admission_key` válido (hit direto);
2. fallback por período (`admission_date <= happened_at <= discharge_date` ou `discharge_date is null`);
3. múltiplos matches: escolher maior `admission_date` (mais recente);
4. nenhum match: escolher internação com `admission_date` mais próxima anterior; se não houver, mais próxima posterior;
5. desempate final estável por `source_admission_key` ascendente.

### 5) Observabilidade de IngestionRun

Adicionar métricas operacionais para internações:

- `admissions_seen`
- `admissions_created`
- `admissions_updated`

Exibir no status da execução para auditoria operacional.

### 6) Representação no portal

- `/patients/`: mostrar resumo por paciente:
  - internações conhecidas;
  - internações com eventos;
  - sem eventos.
- `/patients/<id>/admissions/`:
  - continuar mostrando todas as admissões;
  - quando `event_count == 0`, mostrar badge **"Sem eventos extraídos"**.

## Estratégia de implementação por fases

### Fase 1 — Núcleo de ingestão e associação

- S1: contrato de captura de internações no conector/extractor.
- S2: persistência de internações + fallback determinístico de associação.
- S3: orquestração do worker com semântica de falha e métricas no run.

### Fase 2 — Representação no portal

- S4: lista de admissões + lista de pacientes com cobertura explícita.

### Fase 3 — Hardening e validação final

- S5: testes de regressão finais, checagens completas e artefatos.

## Riscos e mitigação

1. **Mudança de contrato do extractor quebrar testes existentes**
   - Mitigação: manter API existente para evoluções e adicionar novo caminho explícito para snapshot.

2. **Vinculação incorreta por fallback**
   - Mitigação: regras determinísticas codificadas + testes de caracterização de cenários ambíguos.

3. **Sobrescrita indevida de ward/bed**
   - Mitigação: atualizar somente com valores não vazios.

4. **Escopo inflar para redesign da automação**
   - Mitigação: limitar mudanças à captura de snapshot e integração no pipeline atual.
