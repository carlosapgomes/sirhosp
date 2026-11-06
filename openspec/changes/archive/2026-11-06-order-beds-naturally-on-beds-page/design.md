# Design

## Context

A view de `/beds/` já pedia `snapshots.order_by("leito")`, mas essa
ordenação é lexicográfica no banco e se perde na remontagem da
apresentação em `apps/census/occupancy.py`: o caminho v5 reordenava
pacientes por prontuário, o v4 ordenava lexicograficamente e o legado
seguia a ordem de inserção do agrupamento. Uma chave de ordenação
natural já existia em `apps/statistics_reports/events.py`, usada só
pelo relatório de estatísticas diárias. Ver `proposal.md` para a
motivação.

## Goals / Non-Goals

**Goals:**

- Ordenar naturalmente por identificador todas as listas de leitos dos
  collapsibles de `/beds/` (v5, v4 e legado).
- Uma única definição da regra, compartilhada com o relatório de
  estatísticas.

**Non-Goals:**

- Alterar contagens, medições, valores oficiais ou persistência.
- Reordenar a página de detalhe de estados operacionais (agregados por
  setor; identificadores só aparecem em casos de exceção).

## Decisions

- Extrair a chave para `apps/census/bed_ordering.py`:
  `statistics_reports.events` já importa `census.occupancy`, então a
  apresentação de `/beds/` não pode importar a chave de lá sem ciclo.
  O módulo novo é o lar único; `events` reexporta o nome público para
  não quebrar consumidores existentes. Alternativa descartada:
  duplicar a função em `occupancy.py` — criaria duas definições da
  mesma regra sujeitas a divergência.
- Ordenar na camada de apresentação, não na query: a ordem precisa
  sobreviver ao reagrupamento por setor/unidade, que só existe nessa
  camada. A query da view permanece como está.
- Paciente v5 com vários leitos é posicionado pelo primeiro leito na
  ordem natural; sem leito, por último — mesmo contrato do relatório
  de estatísticas (nome e prontuário desempatam).

## Risks / Trade-offs

- [Risco] Superfícies divergirem no futuro → mitigado pela chave única
  e por testes de ordenação nas duas superfícies.
- [Trade-off] Mover a chave muda o módulo dono de uma função pública;
  mitigado pela reexportação em `events` e pela suíte de integração do
  relatório de estatísticas.
