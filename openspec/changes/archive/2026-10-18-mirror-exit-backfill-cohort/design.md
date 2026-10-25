# Design: mirror-exit-backfill-cohort

## Contexto

Diagnóstico de produção 2026-09-07 (evidence pack de ativação): altas
`pending` com internação-âncora **fechada por espelho** — re-extrações de
admissões por intervalo (`recover_historical_data --extractor
admissions`) criam `Admission` já com `discharge_date` do fonte. A saída
existe no domínio, mas a série canônica (S8) exige evento reconciled, e o
planner atual só eligibilita internações **abertas** (replay da saída).

## Decisões

### D1. Coorte nova, sem mutação clínica

`mirror_exits`: para cada `DischargeRecord` `pending` (com `alta_em`
válida) **que não seja elegível para a coorte exact** (ver D4), resolver
o paciente por prontuário único; elegível quando **exatamente uma**
`Admission` do paciente (canônica, não mesclada) satisfaz
`admission_date <= alta_em <= discharge_date` com `discharge_date`
non-nulo. A aplicação **não toca na `Admission`**: apenas emite o evento
de procedência e fecha a evidência.

Exclusões explícitas (revisão manual, nunca elegíveis):

- `alta_em` nula → reason existente `discharges:missing_saida_em`;
- paciente irresolvível → `discharges:mirror_patient_not_found`;
- mais de uma candidata fechada → `discharges:mirror_ambiguous`;
- elegível para a coorte exact (anchor aberta ou reivindicada por
  `decide_discharge_match`) → permanece na coorte exact, nunca mirror
  (evita dupla reivindicação no mesmo plano, que bloquearia rollback do
  batch para sempre).

### D2. Proveniência explícita no evento

`ReconciliationEvent` com `status=reconciled`,
`exit_type=hospital_discharge`, `reason_code="mirror_exit"`,
`new_discharge_date` = `discharge_date` espelhado (igual ao prévio —
registro de procedência, não de mudança), `source_kind/source_id`
apontando a evidência, e `details_json["backfill"]` com o batch UUID
(mesmo linkage S9 das demais coortes). A leitura canônica S8
(último evento reconciled por internação) passa a contar a saída
automaticamente — sem mudança no agregado.

### D3. Ambiguidade vai para revisão manual

Mais de uma candidata fechada, paciente irresolvível ou janela
incompatível → `manual_review` com reason
`discharges:mirror_ambiguous` / `discharges:mirror_patient_not_found`
(contagens agregadas no plano). Nunca elegível por fallback.

### D4. Ordem no plano

`duplicates → discharges (exact) → mirror_exits → deaths`, revisão
manual por último. Mirror depois de exact: altas com internação aberta
continuam preferindo o replay completo (muta a internação e produz
procedência de extração); mirror cobre só o que ficou.

### D5. Reversibilidade estendida (mecanismo e assimetria documentada)

`rollback_admission_reconciliation --batch`: para itens mirror, o caminho
é explícito — em `apps/patients/backfill.py`, no rollback por batch (e no
de operação única), **após** `reverse_reconciliation` emitir o evento
inverso, restaurar a `DischargeRecord` vinculada (resolvida por
`event.source_kind`/`event.source_id`) para o status prévio registrado no
payload (`pending`, `reconciled_at` limpo), **na mesma transação**. A
`Admission` nada sofre (nada a reverter).

**Assimetria aceita e documentada**: o evento inverso copia o `exit_type`
do original (`reconciled`/`hospital_discharge`), portanto a internação
**permanece contada** na série canônica após o rollback do mirror. O
rollback mirror desfaz o registro de proveniência da evidência, não o
espelho; excluir a saída da série exigiria reverter o próprio espelho —
fora de escopo. O cenário da spec declara essa assimetria.

## Riscos e alternativas

- **Espelho mentir?** O `discharge_date` espelhado vem do próprio fonte
  de admissões; a coorte exige ainda a alta correspondente dentro da
  janela — dupla corroboração (espelho + relatório de altas). Sem as
  duas → revisão manual.
- **Série inflada?** O evento tem `reason_code` próprio; se algum dia a
  operação quiser série "só extração-do-dia", o discriminador existe.
- **Contar espelho no card do dia?** Sim por construção (evento
  reconciled) — correto: é uma saída real com procedência.

## Plano de teste

Unitário (`tests/unit/test_backfill_mirror_exit.py`), fixtures
sintéticas:

S1 (planner): pending + única fechada na janela → item mirror; duas
candidatas → manual `mirror_ambiguous`; paciente ausente → manual
`mirror_patient_not_found`; internação aberta não vira mirror (fica para
exact); ordem duplicates→discharges→mirror→deaths; dry-run do comando
imprime `cohort=mirror_exits`; contagem `truncated` correta com `--limit`.

S2 (apply/rollback): apply cria evento com `reason_code=mirror_exit` +
batch em `details_json`, `DischargeRecord` reconciled, `Admission`
intacta (assert de não-mutação); idempotência (segundo apply do mesmo
item não duplica); rollback do batch restaura pending; rollback parcial
de item único funciona; saída agregada sem identidade.
