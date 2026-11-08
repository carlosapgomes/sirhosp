# Proposal: remove-pending-type-search

## Why

O formulário de pendência oferece hoje um campo "Buscar tipo" que filtra
client-side as opções do select "Tipo". O efeito é invisível até o usuário
abrir o dropdown, não existe lista de resultados própria e o padrão (campo de
texto separado filtrando um select nativo) não é reconhecível para o usuário
final. Feedback de uso real: o campo parece não fazer nada.

O dropdown progressivo já entrega a experiência necessária: Categoria → tipos
daquela categoria (1 a ~8 opções por categoria), com cada opção exibindo
`Categoria > Tipo` — o que já distingue os tipos homônimos RNM. Manter um
widget auxiliar que não comunica seu efeito é custo sem benefício.

Decisão do mantenedor: remover o campo em vez de construir um combobox
pesquisável (custo de widget novo com acessibilidade por teclado para resolver
um problema que o filtro por categoria já resolve).

## What Changes

- Remover o campo "Buscar tipo" (`input type_search`) e o hint
  `pending-type-hint` do formulário compartilhado de cadastro/edição de
  pendências (afeta cadastro contextual, edição contextual e edição rápida,
  que compartilham a mesma renderização).
- O select "Tipo" permanece: filtrado pela categoria selecionada; com rótulos
  `Categoria > Tipo`; e a seleção de um tipo continua definindo a categoria
  correspondente automaticamente.
- Remover a referência `aria-describedby="pending-type-hint"` do select
  "Tipo" em `forms.py` (o id deixa de existir).
- PP-10: remover a cláusula "ou buscar tipo com categoria visível" e
  reescrever o cenário "Buscar RNM com contexto" para a distinção de
  homônimos pelo rótulo `Categoria > Tipo` do dropdown (o openspec 1.14
  não suporta remoção de cenário em bloco MODIFIED; o nome é mantido e o
  conteúdo passa a descrever o dropdown).
- Testes HTTP e browser atualizados: assert de ausência do campo e jornada
  RNM por seleção direta com rótulo.

## Capabilities

### Modified capabilities

- `pending-items-portal`: PP-10 passa a ter a seleção categoria → tipo como
  único caminho de classificação; o rótulo `Categoria > Tipo` do dropdown
  assume a desambiguação de homônimos.

## Impact

- UX: um campo a menos no formulário; nenhuma mudança de dado clínico, migração,
  endpoint ou contrato de dados.
- Leitores posicionais/exportadores não são afetados (o campo nunca foi
  enviado ao servidor de forma significativa; o POST simplesmente deixa de
  incluir a chave `type_search`).
