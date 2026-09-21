# Design — Filtro por "Suspeita de paciente residual" em `/censo/`

## Contexto

`/censo/` é renderizado por `_build_censo_context`
(`apps/services_portal/views.py:952`): último snapshot ocupado de
`CensusSnapshot` → filtros SQL (`q`, `unidade`, `especialidade`) → montagem
da lista `pacientes` → anexo de `p["finding"]` via
`build_patient_flow_findings` (bulk, 5 queries fixas) → ordenação em Python
→ dropdowns. Os achados **não são persistidos** (contrato da spec
`patient-flow-findings`); são derivados por request. O export XLSX reusa o
mesmo builder com `include_findings=False` (sem coluna de achado na
planilha).

## Decisões

### D1 — Query param `finding=residual`, filtro por código exato

Novo param GET `finding`; único valor reconhecido: `residual`. O filtro
seleciona `p["finding"] is not None and p["finding"].code ==
CODE_SUSPECTED_LEGACY_RESIDUAL` — código exato, **não**
`requires_manual_review` (que também cobre `mirror_stale_admission`).
Valores vazios/desconhecidos não filtram (fail-open, consistente com
`ordenar`, que ignora valores desconhecidos). Aplicação em Python, entre o
anexo de achados e a ordenação, para que a ordenação atue sobre o subconjunto
filtrado.

### D2 — Pós-classificador em Python, sem persistência e sem query nova

Não existe coluna de banco para o achado; criá-la violaria a spec
(`nothing is persisted or migrated`) e adicionaria migration/backfill. O
classificador já roda em todo request HTML da página com orçamento fixo
(5 queries bulk, independente do tamanho da coorte), portanto o filtro em
Python sobre a lista pronta tem custo zero adicional de queries e preserva
os testes de orçamento existentes.

### D3 — Export WYSIWYG (opção a do operador)

`censo_export_xlsx` mantém `include_findings=False` por padrão (sem custo de
classificador), porém `_build_censo_context` passa a computar achados quando
o filtro `finding=residual` está presente, aplicando o mesmo recorte. Assim a
planilha contém exatamente as linhas da página filtrada — coerente com o
requisito existente "Export respects current filters". A planilha **não**
ganha coluna/label de achado (contrato de colunas preservado). Custo do
export com filtro: +5 queries fixas.

### D4 — Contrato de contexto e template

O dict retornado por `_build_censo_context` passa a incluir `finding_filter`
(string; vazio quando ausente) em ambos os retornos (early-return de
snapshot vazio incluído). O template adiciona um `select` "Situação"
(`id`/`name` `finding`) com duas opções — "Todos os pacientes" e "Suspeita de
paciente residual" — preservando `selected` a partir de `finding_filter`.
Segue o padrão do `select` `#ordenar` (`form-select` puro); TomSelect
permanece restrito a `#unidade`/`#especialidade` (listas longas). O grid do
form ajusta as classes de coluna para continuar responsivo em 12 colunas no
desktop.

### D5 — Variante "qualquer badge de revisão manual" excluída

`requires_manual_review=True` também vale para `mirror_stale_admission`
("Suspeita de internação antiga em aberto ou alta não detectada" — paciente
provavelmente ainda presente, com movimentação recente de leito). Um segundo
valor no select filtrando por essa flag sairia quase de graça, mas o operador
escopou este change apenas no filtro específico solicitado; a variante fica
registrada como follow-up trivial (mudança de predicado + 1 opção + testes).

### D6 — Alternativas rejeitadas

- **Persistir achados para filtrar em SQL**: quebra o contrato de
  "achados correntes e auto-resolventes", exige migration + job de
  sincronização e introduz estado mutável duplicado (a spec veda).
- **Filtro client-side (JS)**: esconderia linhas já entregues ao navegador,
  quebraria o export WYSIWYG e a acessibilidade.
- **Página dedicada** ("fila de revisão manual"): duplicaria filtros/ordenação
  e navigation; o requisito é um recorte da mesma lista.

## Impacto

- **Domínio clínico**: nenhum — classificador intocado; nenhuma regra nova.
- **Banco**: nenhum schema/migration; leituras idênticas às atuais (+5
  queries fixas apenas no export com filtro ativo).
- **Operação (fase 1)**: monólito preservado; sem workers, sem Celery/Redis,
  sem dependência nova; systemd/timers intocados.
- **UI**: um novo controle no form existente de `/censo/`; mobile incluído
  (mesma lista renderizada em cards).
