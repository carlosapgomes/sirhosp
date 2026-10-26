# Design: reconcile-date-only-deaths

Referências canônicas: `proposal.md`; spec atual
`openspec/specs/admission-exit-reconciliation/spec.md` (requisito
"Date-only death evidence does not synthesize time"); ADR-0009
(reconciliação canônica, fail-closed); ADR-0013 (ruído abril/agosto —
fora daqui).

## D1: Matching por data local, unicidade obrigatória

Óbito date-only casa quando existe **exatamente uma** internação canônica
cujo período conhecido contém a data local do óbito em `America/Bahia`:
`admission_date` (data local) ≤ D **e** (`discharge_date` nulo **ou**
data local de `discharge_date` ≥ D). Zero ou mais de uma → fail-closed:
pendente + reason de revisão manual (`ambiguous` /
`patient_not_found` / `admission_not_found` conforme o caso),
idêntico ao comportamento do caminho com datetime. Nenhuma heurística de
desempate.

## D2: Representação — data local a 00:00 como portadora + marcador explícito

`Admission.discharge_date` e `ReconciliationEvent.new_discharge_date` são
`DateTimeField` não-anuláveis neste fluxo; mudar o schema para precisão
dupla teria blast radius desproporcional (invariantes de fechamento,
rollback, comparações).

Decisão: o fechamento date-only usa **D 00:00 `America/Bahia`** como
**portadora da data** (não como hora de óbito), acompanhado de marcador
explícito no `details_json` do evento (ex.: `death_exit.precision =
"date"`, `local_date: "YYYY-MM-DD"`). Invariantes que tornam isso seguro:

- **nenhuma superfície pode exibir ou usar a hora** de um fechamento
  date-only — o marcador é a fonte da verdade da precisão; contagens por
  dia usam data local (00:00 local pertence a D por construção);
- óbitos já são excluídos dos indicadores de altas (S8), então a hora
  nunca alimenta série clínica;
- rollback compara `discharge_date` com `new_discharge_date` (a portadora
  restaura exatamente como foi gravada).

Alternativas rejeitadas: sintetizar fim de dia (a mesma síntese com viés);
`discharge_date` anulável para date-only (quebra invariantes amplas);
campo novo de precisão no schema (migração sem consumidor além do
marcador — YAGNI).

Aceitação do operador (2026-10-25): aprovada exatamente como proposta —
D 00:00 `America/Bahia` como portadora + marcador `precision="date"` +
invariante de exibição.

## D3: Coorte `deaths` e reasons de revisão

- `_death_candidates` passa a produzir items para date-only único (D1);
- o reason `deaths:date_only` **deixa de existir** como revisão (torna-se
  eligível); ambiguidades e não-resoluções continuam com os reasons
  existentes;
- a linha `cohort=deaths` do dry-run passa a refletir a nova elegibilidade;
  `deaths:ambiguous` pode crescer (óbitos date-only ambíguos) — é o
  fail-closed trabalhando.

## D4: Apply/rollback reutilizam o fluxo delimitado existente

Item de óbito date-only aplica pelo mesmo caminho online de hoje
(transação única, evento append-only, linkage de batch,
`--apply --limit --label --backup-ref`, cap 50/100); o apply apenas
escreve o marcador D2 no evento criado. Rollback por batch e por operação
valida pós-estado e restaura — sem código novo além do marcador.

## D5: Ativação dos 777 históricos é operação separada

Após implementação e release: dry-run → backup → canário 50 → lotes ≤100
até drenar → conferência (episódios fechados por morte, marcador presente,
indicadores de altas inalterados). Sem automação nova; o gotejamento mensal
futuro usa o mesmo comando ad hoc até haver decisão de integrar ao runtime
(fora de escopo).

## D6: Testes (behavior, not implementation)

- matcher date-only: única casa; múltipla → ambiguous; sem paciente →
  patient_not_found; paciente sem internação compatível →
  admission_not_found; borda de data local (admissão e óbito no mesmo D);
- datetime completo: comportamento inalterado (regressão);
- apply: fecha em D 00:00 local com marcador; evento `exit_type=death`;
  idempotência; rollback restaura estado anterior;
- invariantes de exibição: contagens/agregações por data local não mudam
  com a hora portadora; indicadores de altas seguem sem óbitos.
