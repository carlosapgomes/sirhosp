# Proposal

## Why

Na página `/beds/`, as listas dentro do collapsible de cada setor não
seguiam a ordem do identificador do leito: a ordenação anterior era
lexicográfica (`10` antes de `2`) e, no caminho occupancy-v5, os
pacientes eram ordenados pelo prontuário. Para a gestão de leitos, isso
dificulta localizar um leito e conferir a ocupação do setor.

## What Changes

- As listas de leitos dentro de cada setor em `/beds/` passam a seguir a
  ordem natural do identificador (`2` antes de `10`, `UTI02` antes de
  `UTI10`), em todos os caminhos de apresentação (v5, v4 e legado).
- Em v5, o paciente é posicionado pela sua primeira leito na ordem
  natural; pacientes sem leito informado ficam por último.
- A regra de ordenação natural, que já existia apenas no relatório de
  estatísticas diárias, passa a ter um lar único compartilhado pelas
  duas superfícies.

Não-objetivos: não altera contagens, medições ou qualquer valor oficial;
não altera a página de detalhe de estados operacionais (que lista
apenas agregados por setor e casos de exceção); sem mudança de modelo
de dados ou migração.

## Capabilities

### New Capabilities

Nenhuma.

### Modified Capabilities

- `bed-status-capacity-view`: as listas de leitos de cada setor em
  `/beds/` passam a ter requisito explícito de ordenação natural pelo
  identificador do leito.

## Impact

- Código: `apps/census/occupancy.py` (apresentação de `/beds/`),
  novo `apps/census/bed_ordering.py` (chave compartilhada) e
  `apps/statistics_reports/events.py` (passa a reexportar a chave).
- Risco principal: divergência de ordem entre `/beds/` e o relatório de
  estatísticas — mitigado pela chave única compartilhada e por testes
  de ordenação nas duas superfícies.
- Sem impacto em domínio clínico, scraping, banco ou operação agendada;
  preserva a simplicidade da fase 1 (sem dependência nova).
