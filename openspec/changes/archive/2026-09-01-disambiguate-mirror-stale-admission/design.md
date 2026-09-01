# Design — Disambiguate mirror-stale admissions from legacy residuals

## Contexto

O classificador `apps/ingestion/patient_flow_findings.py` (PFIF-S3, RC17)
deriva cinco achados correntes com prioridade D5 e orçamento de quatro
queries bulk. A regra 5 (`suspected_legacy_residual`) unia três condições
(admissão ativa ≥ 48 h; sem evento há 48 h; presença no censo) sob uma
hipótese única de linha órfã do legado. A produção mostrou que o mesmo padrão
observável cobre duas causas distintas, distinguíveis pela recência do
movimento do paciente (ledger `PatientMovement`, já alimentado pelo
processamento do censo).

## Decisões

### D1 — Novo achado fechado `mirror_stale_admission`

Código `mirror_stale_admission`; label constante "Suspeita de admissão órfã
no espelho"; severidade `warning`; `requires_manual_review=True`. Contrato
fechado idêntico aos demais (`code`/`label`/`severity`/
`requires_manual_review`), incluído em `ALL_FINDING_SPECS`/
`_FINDING_SPECS`. Semântica: o espelho interno mantém admissão ativa antiga
enquanto o paciente tem trânsito atual — a ação de revisão é fechar a
admissão órfã (ou espelhar a nova internação); o achado auto-resolve na
avaliação seguinte, sem persistência.

### D2 — Sinal de desambiguação: recência de movimento

`Max(PatientMovement.first_seen_at)` por paciente (entrada no setor mais
recente). Janela `_MOVEMENT_WINDOW = 48 h`, alinhada a `_EVENT_WINDOW`.
Regra 5 split determinístico:

- movimento em `[now − 48 h, now]` ⇒ `mirror_stale_admission`;
- sem movimento, ou movimento anterior a 48 h, ou timestamp futuro (dado
  inválido tratado como ausente, fail-closed) ⇒ `suspected_legacy_residual`
  (comportamento atual preservado).

Regras 1–4 e a prioridade D5 permanecem intocadas; o split só particiona a
condição final da regra 5.

### D3 — Orçamento de queries: 4 → 5 fixo

Uma quinta query bulk (`values("patient_id").annotate(Max("first_seen_at"))`
filtrada por `patient_id__in` da coorte) mantém o orçamento fixo e
independente do tamanho da coorte. Nenhuma query no loop de classificação;
superfícies continuam recebendo apenas o mapa pronto.

### D4 — Superfícies existentes sem mudança

`/censo`, `/beds` e a página de admissões renderizam
genericamente `finding.label`/`requires_manual_review`; o novo código flui
para elas sem alteração de view/template. A prova é por testes de
caracterização (o novo rótulo aparece sem tocar superfícies), não por
edição.

### D5 — Alternativas rejeitadas

- Lista fixa de setores de observação (`0 T …`): quebraria o princípio
  "um setor sozinho nunca classifica", exige manutenção por renomeação de
  setor e não cobre reentradas em enfermaria.
- `tempo_internacao=0`/`data_internacao` do snapshot legado: campo de
  exibição do legado, menos geral que o ledger de movimento e sujeito a
  formatação; o movimento cobre o mesmo sinal com semântica interna
  auditável.
- Fechamento automático de admissões órfãs: mutação de estado clínico fora
  de escopo; permanece revisão manual (o achado é o sinal, não o corretor).

### D6 — Aba patients do portal: coluna de situação corrente

`_get_latest_batch_failure_stats` (única fonte da tabela "Pacientes com
Falha Final") classifica em bulk os registros dos pacientes listados:
inputs construídos a partir da foto mais recente do censo (paciente fora do
censo atual ⇒ sem achado, o que é correto: a projeção é corrente). O
template ganha coluna "Situação" com o mesmo tratamento de badge acessível
das outras superfícies; sem achado ⇒ célula vazia, sem placeholder. Sem PHI
novo: a tabela já exibe `patient_record`; o rótulo é constante fechada.
Queries: 2 (foto + classifier's fixo de 5) por render, sem N+1 por linha.

### D7 — Não-acoplamento com eixos existentes

O health check, o contador `recognized_recent_encounter`, os labels
derivados de lote (`Concluído com achados`/`Falha parcial`) e o XLSX não
leem nem contam `mirror_stale_admission` (contam outcomes de stage, não
códigos do classificador). Nenhuma mudança necessária; testes de regressão
devem provar a não-interferência.

## Riscos e mitigações

- Movimento antigo reaberto por reprocesso histórico: janela de 48 h sobre
  `first_seen_at` reage apenas a entradas novas; reprocesso de snapshots
  antigos não cria `first_seen_at` novo.
- Falso negativo Face B sem setor novo (paciente reentra no MESMO setor):
  `first_seen_at` novo é criado por reentrada no setor (linha nova do
  ledger); se o legado reutilizar a linha antiga, o caso permanece na regra
  original — aceito (fail-closed) e observável pelo canário.
- Dimensionamento de revisão manual: dia-1 teve 26 sinalizações; o split
  reduz ruído sem remover a fila dos 21 casos originais.

## Slices

- **MSA-S1** — classificador: split da regra 5 + quinta query + testes
  (regra, superfícies por caracterização, orçamento).
- **MSA-S2** — portal: coluna de situação corrente na aba patients +
  testes (auth, sem placeholder, bounded queries, privacidade).

Implementação por DeepSeek4-Flash com contexto zero, um slice por vez,
relatório verificável por terceiro LLM em `/tmp/sirhosp-slice-MSA-S{n}-report.md`.
