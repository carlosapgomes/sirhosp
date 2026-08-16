# Design: guard-census-extraction-completeness

## Context

A investigação operacional mostrou que a extração `census_extraction` pode
terminar como sucesso mesmo quando o script Playwright coleta uma lista parcial
de setores. O caso observado capturou 25 setores e 372 linhas, enquanto os 34
batches recentes tinham média de 43,15 setores, mediana de 44 e apenas esse
batch abaixo de 40 setores.

Hoje o fluxo é:

```text
extract_census -> CensusSnapshot -> process_census_snapshot -> CensusExecutionBatch
```

O `run_adaptive_census_cycles` apenas orquestra os comandos existentes. Portanto
o ponto de proteção deve ficar na própria extração e, por defesa em
profundidade, no processamento por `run_id`.

## Goals / Non-Goals

**Goals:**

- Rejeitar extrações de censo com menos de 40 setores distintos.
- Evitar criação de `CensusExecutionBatch` a partir de snapshot incompleto.
- Persistir métricas agregadas suficientes para auditoria operacional.
- Melhorar a coleta da lista de setores no script Playwright.
- Manter slices verticais, enxutos e implementáveis por executor LLM com
  contexto zero.

**Non-Goals:**

- Não criar UI nova para configuração de limiar.
- Não criar catálogo administrativo de setores.
- Não introduzir Celery, Redis ou serviço externo.
- Não alterar lógica clínica de deduplicação, movimentação, admissão ou
  demografia.
- Não corrigir retroativamente batches históricos já criados.

## Decisions

### 1. Limiar fixo e centralizado em 40 setores

Usar 40 como mínimo de setores distintos para aceitar uma extração de censo.
Esse valor é conservador frente ao histórico recente: média 43,15, mediana
44, mínimo normal observado 42 e outlier problemático 25.

O valor deve ficar centralizado em código de domínio/serviço de censo. Não
espalhar números mágicos nem criar configuração dinâmica neste change.

Alternativa considerada: usar média móvel. Rejeitada por exigir estado
histórico e política de outliers; YAGNI para a primeira proteção.

### 2. Gate primário no `extract_census`

O management command `extract_census` deve validar a completude após parsear o
CSV e antes de persistir snapshots. Se `sector_count < 40`, ele deve:

- marcar o `IngestionRun` como `failed`;
- registrar `failure_reason` seguro, preferencialmente `invalid_payload`;
- gravar métricas agregadas em `IngestionRunStageMetric.details_json`;
- emitir mensagem operacional clara;
- sair com falha para que o orquestrador não processe snapshot.

Racional: o melhor momento para impedir dano é antes de persistir uma visão
parcial como snapshot canônico.

### 3. Defesa em profundidade no `process_census_snapshot`

Mesmo com gate na extração, `process_census_snapshot(run_id=...)` deve validar
que o conjunto de snapshots associado ao `run_id` tem pelo menos 40 setores
antes de criar `CensusExecutionBatch`.

Racional: protege execução manual, dados históricos parcialmente persistidos
ou qualquer caminho futuro que chame o processador diretamente.

Para manter compatibilidade, quando `run_id` for omitido, o processamento do
snapshot mais recente deve aplicar a mesma validação ao conjunto escolhido.

### 4. Métricas agregadas sem dados sensíveis

As métricas devem ser agregadas e seguras:

- `sector_count`;
- `row_count`;
- `occupied_count`, quando barato de calcular;
- `minimum_required_sectors`;
- `completeness_status` (`accepted` ou `rejected`);
- no script Playwright, contadores como `setores_found`, `setores_processed`,
  `setores_with_error` e `setores_empty`.

Não persistir nomes de pacientes, prontuários ou textos clínicos em logs de
falha, stage metrics ou relatórios.

### 5. Robustez da extração de setores no Playwright

O script deve tornar `extract_setores()` mais resistente a dropdown
parcialmente carregado, preferindo uma função pequena e testável para
normalizar setores e uma rotina Playwright que tente carregar todo o painel
antes de retornar a lista.

Racional: o gate de 40 evita dano, mas não resolve a causa provável. A
melhoria do scraping reduz a frequência de falhas sem mudar a arquitetura.

### 6. Dimensionamento dos slices

A mudança deve ter três slices verticais:

1. **GCEC-S1**: gate primário no `extract_census` com métricas agregadas.
2. **GCEC-S2**: defesa em profundidade no `process_census_snapshot` e
   integração com o orquestrador via falha segura.
3. **GCEC-S3**: robustez da coleta de setores no script Playwright e métricas
   de resumo do script.

Três slices é suficiente porque cada ajuste tem fronteira clara e testes
focados. Dividir mais aumentaria overhead; juntar tudo em um slice aumentaria
risco de drift.

## Risks / Trade-offs

- Limiar fixo pode bloquear cenário legítimo -> mitigação: valor centralizado
  e mensagem clara para ajuste futuro.
- Falhar antes de persistir snapshots reduz evidência forense no banco ->
  mitigação: persistir métricas agregadas no stage metric e manter
  stderr/stdout operacional seguro.
- Testes Playwright reais seriam frágeis -> mitigação: testar helpers puros e
  caminhos com fakes/mocks; não depender do sistema fonte nos testes.
- Defesa em dois pontos pode duplicar lógica -> mitigação: extrair helper de
  validação pequeno e reutilizável em `apps.census.services`.

## Migration Plan

1. Implementar GCEC-S1 e validar que extrações com menos de 40 setores falham
   antes de persistir `CensusSnapshot`.
2. Implementar GCEC-S2 e validar que processamentos diretos de snapshot
   incompleto não criam `CensusExecutionBatch`.
3. Implementar GCEC-S3 e validar que a coleta de setores é mais robusta sem
   introduzir dependências ou acoplamento adicional.
4. Rollback: reverter o change; não há migração obrigatória prevista.

## Open Questions

- O limiar de 40 deve se tornar variável de ambiente em change futuro?
- Convém adicionar alerta no portal para última extração rejeitada?
- Vale criar catálogo esperado de setores após acumular evidência suficiente?
