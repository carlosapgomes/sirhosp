# Architecture Decision Records

Registros de decisoes arquiteturais importantes do projeto.

## ADRs Ativas

| Numero                                                                                            | Titulo                                                                    | Status   | Data       |
| ------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------- | -------- | ---------- |
| [ADR-0001](ADR-0001-monolito-django-postgresql-e-jobs-agendados.md)                               | ADR-0001-monolito-django-postgresql-e-jobs-agendados                      | Accepted | 2026-05-24 |
| [ADR-0002](ADR-0002-modelagem-canonica-eventos-clinicos-e-reconciliacao.md)                       | ADR-0002-modelagem-canonica-eventos-clinicos-e-reconciliacao              | Accepted | 2026-05-24 |
| [ADR-0003](ADR-0003-catalogo-temporal-capacidade-materializacao-imutavel.md)                      | ADR-0003-catalogo-temporal-capacidade-materializacao-imutavel             | Accepted | 2026-08-17 |
| [ADR-0004](ADR-0004-correcao-co-e-particionamento-etario-3a.md)                                   | ADR-0004-correcao-co-e-particionamento-etario-3a                          | Accepted | 2026-08-20 |
| [ADR-0005](ADR-0005-duas-realidades-capacidade-oficial-e-posicoes-legado.md)                      | ADR-0005-duas-realidades-capacidade-oficial-e-posicoes-legado             | Accepted | 2026-08-21 |
| [ADR-0006](ADR-0006-ocupacao-v4-acionavel-conflitos-tipados-e-lista-unica.md)                     | ADR-0006-ocupacao-v4-acionavel-conflitos-tipados-e-lista-unica            | Accepted | 2026-09-01 |
| [ADR-0007](ADR-0007-ocupacao-v5-pacientes-identificados.md)                                       | ADR-0007-ocupacao-v5-pacientes-identificados                              | Accepted | 2026-08-25 |
| [ADR-0008](ADR-0008-fullsync-failure-characterization-decision.md)                                | ADR-0008-fullsync-failure-characterization-decision                       | Accepted | 2026-09-01 |
| [ADR-0009](ADR-0009-reconciliacao-canonica-de-saidas-e-identidade-longitudinal-de-internacoes.md) | Reconciliação canônica de saídas e identidade longitudinal de internações | Proposed | 2026-09-03 |

## ADRs Deprecated/Superseded

| Numero | Titulo | Status | Data |
| ------ | ------ | ------ | ---- |
| -      | -      | -      | -    |

## Como criar uma nova ADR

1. Execute `python3 adr_generator.py --title "Sua decisao"`
2. Revise contexto, decisao, alternativas e consequencias
3. Commit da ADR junto do change relacionado
