# Design: remove-pending-type-search

## Contexto

O campo "Buscar tipo" (`type_search`) foi introduzido pelo change
`structure-inpatient-pending-items` (slice S2, decisão D5) como busca
complementar do PP-10. A implementação filtra client-side as `<option>` do
select "Tipo" por substring sem acento, combinada com a categoria
selecionada. O efeito, porém, é invisível até o dropdown ser aberto, e o
padrão não é reconhecível. Decisão do mantenedor (reversão de UX):
remover o campo.

## Decisões

### D1 — Remover em vez de construir combobox

Um combobox pesquisável real (input + listbox dinâmica, ARIA, teclado) é um
widget novo com custo de implementação, acessibilidade e manutenção para
resolver um problema que o fluxo Categoria → Tipo já resolve (1 a ~8 tipos
por categoria; homônimos distinguidos pelo rótulo `Categoria > Tipo`).
Menor mudança correta: remoção. Sem biblioteca externa, sem novo widget.

### D2 — Preservar o filtro por categoria do select "Tipo"

A função JS `syncTypeFilter` atual filtra por **dois** critérios: categoria
selecionada **e** termo buscado. Apenas o critério "termo" é removido. O
comportamento "selecionar categoria reduz a lista de tipos" permanece
exatamente como hoje (hint da categoria e cenário PP-10 "Selecionar
categoria e descobrir campos" intactos), bem como o listener que define a
categoria quando um tipo é escolhido.

### D3 — Corrigir referência de acessibilidade pendurada

O hint `pending-type-hint` pertence ao bloco removido. O widget do select
"Tipo" em `forms.py` referencia esse id via `aria-describedby`; a referência
é removida junto (referência a id inexistente é defeito de acessibilidade).

## Riscos e mitigações

- Remover a função inteira em vez de só o critério de busca perderia o
  filtro por categoria: coberto por teste browser existente
  (`_option_hidden_flags` com categoria selecionada) que permanece.
- Migração/regressão de dados: nenhuma — mudança é template/JS/testes/spec.

## Estratégia de teste

RED-before: (a) teste HTTP passa a afirmar **ausência** de `type_search`
(falha antes da remoção); (b) teste browser passa a afirmar `count == 0`
para `#id_type_search` (falha antes). GREEN-after: jornada RNM
reescrita para seleção direta por rótulo `CHD ... > RNM` mantendo a
cobertura de desambiguação de homônimos e categoria automática. Gates
oficiais completos no container.
