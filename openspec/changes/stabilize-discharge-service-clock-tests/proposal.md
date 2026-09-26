## Why

Dois testes unitários de `process_discharges` dependem do relógio de parede e
falham diariamente entre 00:00 e 03:00 em `America/Bahia`, bloqueando o quality
gate apesar de o código de produção não ter regredido. A correção é necessária
para recuperar um gate determinístico e permitir evidência operacional
confiável em qualquer horário.

## What Changes

- Tornar determinísticas as datas sintéticas dos dois cenários afetados sem
  alterar a regra de negócio de altas.
- Preservar a cobertura de admissões já encerradas no mesmo dia operacional.
- Registrar RED com a reprodução já coletada na janela crítica e GREEN com os
  testes focados e o quality gate oficial fora de qualquer dependência do
  horário corrente.
- Restringir o slice aos testes; não alterar código de produção, banco,
  persistência clínica ou runtime operacional.

Não objetivos: mudar a definição de dia operacional, flexibilizar a seleção de
admissões, alterar dados persistidos ou encobrir falhas reais do serviço.

## Capabilities

### New Capabilities

Nenhuma.

### Modified Capabilities

Nenhuma. Este change corrige apenas a determinismo da suíte de testes e usa
`skip_specs: true`; não modifica comportamento observável do sistema.

## Impact

- Arquivo esperado: `tests/unit/test_discharge_service.py`.
- Sem alteração de API, modelo, migration, dependência ou código de produção.
- Risco principal: enfraquecer acidentalmente as asserções; mitigado pela
  preservação das contagens esperadas e por revisão independente.
- Risco classificado como **ESSENCIAL**: manutenção local de testes, sem impacto
  funcional, regulatório ou em dados.
