# Proposal — Disambiguate mirror-stale admissions from legacy residuals

## Problema

O achado `suspected_legacy_residual` ("Suspeita de paciente residual no
legado", PFIF-S3/RC17) sinaliza pacientes com admissão interna ativa há 48 h
ou mais, sem evolução há 48 h e ainda presentes no censo. A hipótese original
era unilateral: a linha do legado estaria órfã (paciente saiu e o legado não
baixou).

A observação do primeiro dia de produção da RC17 (canário §6.1.4) mostrou a
outra face da mesma ambiguidade — **Face B**: o paciente está genuinamente em
trânsito (entrada recente em novo setor) e o que está desatualizado é o
**espelho interno** (admissão antiga que nunca recebeu alta). No levantamento
de 2026-09-01: 26 pacientes rotulados, dos quais **5 com movimento de setor
novo em até 48 h** — todos em setores de observação do cluster `0 T`
(apenas cadeiras, incompatíveis com transferência de leito), todos com o
legado reportando entrada no próprio dia (`data_internacao` de hoje,
`tempo_internacao=0`) e todos com admissão interna órfã de junho/julho. Para
esses pacientes o rótulo atual é semanticamente equivocado: o resíduo está no
espelho, não no legado.

## Objetivo

1. Desambiguar a regra 5 do classificador com a recência de movimento do
   paciente (`PatientMovement`): admissão ativa antiga + sem evolução
   recente + **movimento de setor em até 48 h** ⇒ novo achado
   `mirror_stale_admission` ("Suspeita de admissão órfã no espelho",
   warning, revisão manual); sem movimento recente ⇒ comportamento atual
   (`suspected_legacy_residual`) preservado.
2. Exibir o rótulo do achado corrente (quando houver) na listagem
   "Pacientes com Falha Final" da aba patients de `/metrica-ingestao`,
   ajudando a interpretar a situação de cada falha/paciente.

## Escopo incluído

- `apps/ingestion/patient_flow_findings.py`: novo código fechado, janela de
  movimento, quinta query bulk (orçamento 4→5 fixo), split da regra 5.
- `apps/services_portal/views.py` +
  `apps/services_portal/templates/services_portal/ingestion_metrics.html`:
  coluna de situação corrente na tabela de pacientes com falha final.
- Deltas de spec: `patient-flow-findings` e `ingestion-run-metrics-portal`.
- Testes de regra, superfícies existentes (auto-aparição do novo rótulo) e
  portal.

## Escopo excluído

- Sem mudança nas regras 1–4, prioridade D5, health check, contadores,
  eixos técnicos, XLSX, stage outcomes, workers ou extração.
- Sem mutation de `Admission`/`PatientMovement` (o fechamento da admissão
  órfã permanece ação manual de revisão; o achado é projeção corrente e
  auto-resolvente).
- Sem novos sinais baseados em lista fixa de setores de observação ou em
  `tempo_internacao` do legado (ver design D5).

## Evidência (canário RC17, 2026-09-01)

- 26 sinalizações `suspected_legacy_residual` na foto de 677 pacientes;
- 5/5 pacientes Face B homogêneos: setor `0 T` (observação), entrada legado
  no dia, admissão interna órfã de 22/06 a 17/07, último evento 14/07–18/08;
- 21 pacientes sem movimento recente permanecem como fila de revisão
  legítima da regra original (mistura de resíduo real e longa permanência
  sem evolução extraída).

## Critérios de sucesso

- Paciente com admissão órfã + movimento ≤ 48 h recebe
  `mirror_stale_admission` em `/censo`, `/beds` e página de admissões, sem
  alteração nas três superfícies (renderização genérica do DTO fechado).
- Paciente sem movimento recente continua recebendo `suspected_legacy_residual`.
- A aba patients de `/metrica-ingestao` mostra o rótulo corrente de cada
  paciente com falha final, sem query por linha e sem dado sensível novo.
- Orçamento de queries do classificador permanece fixo (5 queries bulk),
  independente do tamanho da coorte.
- Gates oficiais verdes; specs e tasks atualizadas.
