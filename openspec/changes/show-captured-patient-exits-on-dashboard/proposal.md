## Why

O indicador gerencial de altas está subestimando saídas reais porque a série
principal depende da reconciliação longitudinal da internação, embora o campo
fonte `DischargeRecord.saida_em` tenha sido capturado com cobertura histórica.
Isso transforma pendências de qualidade/reconciliação em um falso vale de fluxo
hospitalar, especialmente em abril e agosto de 2026.

## What Changes

- Fazer do `DischargeRecord.saida_em`, agrupado por data local
  `America/Bahia`, a fonte da contagem gerencial de saídas no dashboard e no
  gráfico principal de altas.
- Exibir no gráfico principal somente saídas efetivas capturadas; remover dele a
  série de sumários por `alta_em` e qualquer dependência da procedência
  reconciliada.
- Calcular médias móveis, médias por dia da semana e distribuição horária por
  especialidade a partir de `saida_em`, mantendo hoje fora da série histórica
  diária.
- Construir o eixo diário pelo intervalo calendário solicitado, incluindo zero
  para dias sem saída, em vez de depender da existência de linhas no agregado
  canônico.
- Preservar a reconciliação longitudinal para reinternações, identidade de
  episódios e auditoria, sem torná-la pré-condição para a métrica gerencial.
- Levar a comparação entre saídas capturadas, saídas reconciliadas e sumários
  médicos para uma superfície secundária de qualidade da reconciliação,
  protegida pela permissão de revisão já existente.
- Corrigir a listagem de altas acessada pelo gráfico para consultar registros por
  `saida_em`, pois o vínculo legado com `DailyDischargeCount` foi
  intencionalmente removido.
- Atualizar a ADR-0009 para distinguir indicador gerencial baseado em evidência
  fonte do agregado canônico usado pelo domínio de reconciliação.

Fora de escopo:

- alterar as regras que fecham ou mesclam `Admission`;
- usar `alta_em` como data de saída;
- executar ou redesenhar o backfill de produção neste change;
- criar migrations, novos modelos ou nova infraestrutura de filas.

## Capabilities

### New Capabilities

Nenhuma.

### Modified Capabilities

- `daily-discharge-tracking`: muda a fonte e a apresentação do indicador
  gerencial para `DischargeRecord.saida_em`, separando-o do agregado canônico e
  movendo comparações de qualidade para uma superfície secundária.

## Impact

- Portal: `apps/services_portal/views.py`, dashboard, gráfico/listagem de altas e
  superfície protegida de reconciliação.
- Testes: contratos unitários e de integração dos indicadores de alta e da
  revisão protegida.
- Especificação: `daily-discharge-tracking` e decisão registrada na ADR-0009.
- Sem mudança de schema ou dependências.
- Risco principal: contar evidência duplicada ou agrupar no dia incorreto; será
  mitigado pela unicidade existente do `DischargeRecord`, testes de reextração
  idempotente, eixo calendário completo e limites explícitos de
  `America/Bahia`.
