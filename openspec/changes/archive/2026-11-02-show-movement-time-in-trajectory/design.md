# Design

## Context

A rc.44 persistiu a hora real de movimentação em
`CensusSnapshot.source_movement_at` (aware, `America/Bahia`), disponível a
partir do run 2944950 (2026-11-01). A Trajetória lê `PatientMovement`,
que é date-only e não recebe essa projeção. Este change leva a hora até a
UI quando existe, sem alterar nenhuma semântica clínica aceita.

## Goals / Non-Goals

### Goals

- Exibir a hora real de movimentação na Trajetória quando a fonte a
  forneceu;
- Degradação graciosa: entradas antigas seguem apenas com data na mesma
  linha do tempo;
- Preservar integralmente identidade, deduplicação, ordenação e cálculo de
  durações por data.

### Non-Goals

- Hora de internação na Trajetória (o cabeçalho da admissão já exibe
  `d/m/Y H:i` quando `Admission.admission_date` a possui);
- Backfill de movimentos históricos;
- Mudança de durações para base horária; mudanças em extração, snapshot ou
  consumidores existentes.

## Decisions

### D1 — Hora opcional propagada no upsert, não na leitura

`PatientMovement.source_movement_at` (DateTimeField anulável, aware) é
preenchido por `upsert_patient_movements` a partir do snapshot processado.
Alternativa considerada: join em tempo de render (view consultando
snapshots por paciente/data/setor). Rejeitada porque o upsert é o ponto
canônico onde snapshot ↔ movimento se correspondem (mesma data, mesmo
setor), o join por render seria ambíguo com múltiplos snapshots do mesmo
dia e adicionaria queries por requisição.

### D2 — Política: último snapshot com hora vence; null nunca apaga hora

No update do movimento existente: `source_movement_at` do snapshot
sobrescreve quando não-null; snapshot sem hora mantém o valor existente.
Justificativa: snapshots repetidos do mesmo evento de movimentação trazem a
mesma hora da fonte; o valor mais recente é o mais confiável (corrige
leituras anteriores), e uma captura sem tooltip não deve apagar conhecimento
já obtido. Movimento criado sem hora fica NULL até um snapshot posterior da
mesma data de movimentação trazer a hora (P2 do cenário "ganha hora
depois").

### D3 — Sem backfill

Migração aditiva apenas cria a coluna. Movimentos anteriores à rc.44
permanecem NULL: a hora não existia na fonte coletada e inventá-la
violaria a decisão ECD-S1. Movimentos antigos podem ganhar hora apenas se
um novo censo reobservar a mesma data de movimentação (paciente ainda no
mesmo estado — raro, mas correto).

### D4 — Exibição condicional com fuso do projeto

A view inclui `source_movement_at` em cada entrada do contexto de
trajetória; o template renderiza `d/m/Y H:i` quando presente e `d/m/Y`
quando ausente, na timezone configurada (`settings.TIME_ZONE` /
`America/Bahia`), consistente com o cabeçalho de admissão. Nenhum
placeholder de hora.

### D5 — Durações e identidade permanecem date-based

`days` continua `(próxima.movement_date - atual.movement_date).days`;
constraints, `sequence` e query de ordenação inalterados. A hora é anotação
de exibição, não dimensão de cálculo — mudar isso seria decisão clínica
nova, fora deste change.

### D6 — Privacidade/auditoria inalteradas

A hora exibida vem exclusivamente do tooltip da fonte persistido no
snapshot (trilha ECD-S1/S3). Nenhuma nova fonte de dados, log ou artefato.

## Risks / Trade-offs

- **Leitura mista na mesma trajetória** (datas antigas, data+hora
  recentes): aceito explicitamente — é o comportamento solicitado; o UI
  deixa claro por si (presença/ausência da hora).
- **Hora "ganha depois"** pode fazer uma entrada antiga passar a exibir
  hora dias após a criação do movimento: consistente com D2 (a fonte
  reobservou o evento); trilha `first_seen_at`/`last_seen_at` preservada.
- Custo: uma coluna e um campo no contexto — desprezível.

## Migration Plan

1. Migração aditiva `PatientMovement.source_movement_at` (null=True), sem
   backfill, sem índice (consulta é por paciente/admissão existente).
2. Deploy conjunto (upsert + view + template na mesma imagem) — não há
   contrato entre serviços; versão antiga de UI lendo movimento novo apenas
   ignora o campo.
3. Rollback por imagem sem reverter migração (coluna opcional fica sem
   consumidor no código antigo), idêntico ao padrão rc.43/rc.44.

## Open Questions

Nenhuma — a expectativa de granularidade mista foi confirmada pelo
operador como o comportamento desejado.
