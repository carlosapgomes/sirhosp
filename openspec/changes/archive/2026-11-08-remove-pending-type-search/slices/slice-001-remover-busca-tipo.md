# Slice 001 — Remover busca de tipo do formulário de pendências

Change: `remove-pending-type-search`. Políticas globais: ver `AGENTS.md`
(Engineering Policies aplicam sem repetição).

## Objetivo

Remover o campo "Buscar tipo" (`input type_search` + hint
`pending-type-hint`) do formulário compartilhado de pendências, mantendo
intacto o fluxo progressivo Categoria → Tipo (filtro do select pela
categoria, rótulos `Categoria > Tipo`, categoria definida automaticamente
pela escolha do tipo).

## Requisitos cobertos

- PP-10 (MODIFIED) — ver `specs/pending-items-portal/spec.md` desta change.
- Sem impacto em outros requisitos: PI-01/02/05/06/09/10/11 e PP-01..09
  inalterados.

## Referências necessárias

- Delta: `openspec/changes/remove-pending-type-search/specs/pending-items-portal/spec.md`
- Design: `openspec/changes/remove-pending-type-search/design.md` (D1–D3)
- Spec vigente: `openspec/specs/pending-items-portal/spec.md` (PP-10)
- Origem do campo: `openspec/changes/archive/2026-11-07-structure-inpatient-pending-items/`
  (design D5, slice S2)

## Código-alvo (expected blast radius)

1. `apps/pending_items/templates/pending_items/_pending_form_fields.html`
   — remover bloco do campo de busca (label + input + hint); coluna da
   categoria passa a `col-12`.
2. `apps/pending_items/templates/pending_items/_pending_form_script.html`
   — remover `searchInput`, o critério de termo da filtragem e o listener
   `input`; **preservar** o filtro por categoria e o listener que define a
   categoria ao escolher tipo.
3. `apps/pending_items/forms.py` — remover
   `"aria-describedby": "pending-type-hint"` do widget de `item_type`.
4. `tests/integration/test_pending_items_details_http.py` — trocar o assert
   de presença por assert de ausência (`type_search` não renderizado).
5. `tests/integration/test_pending_items_browser.py` — remover interação
   com `#id_type_search`; adicionar assert `count == 0`; jornada RNM por
   seleção direta por rótulo (ex.: `CHD (Centro de Hemorragia Digestiva) >
RNM`), mantendo asserções de categoria automática e grupo RNM visível;
   renomear o teste (retirar "search") e atualizar docstring da classe;
   manter `_option_hidden_flags` (cobertura do filtro por categoria).

Nenhum outro arquivo deve ser tocado. Tocar algo além: justificar no
relatório.

## Acceptance criteria

- AC1: GET do formulário (cadastro, edição contextual e modal) não contém
  `type_search` nem `id_type_search` (evidência: teste HTTP).
- AC2: No browser, `#id_type_search` não existe (`count == 0`).
- AC3: Selecionar categoria continua restringindo as opções de tipo
  (asserções `_option_hidden_flags` existentes permanecem e passam).
- AC4: Selecionar um tipo continua definindo a categoria automaticamente e
  revelando o grupo do perfil correto (jornada RNM por rótulo).
- AC5: Sem referência a `pending-type-hint` no DOM renderizado nem em
  `forms.py`.
- AC6: `./scripts/test-in-container.sh quality-gate` e
  `./scripts/test-in-container.sh integration` verdes no estado final.
- AC7: Sem novas migrações (`makemigrations --check` limpo dentro do gate).

## Estratégia de teste/verification

- RED-before: AC1/AC2 como asserts de ausência falham antes da remoção
  (registrar saída); GREEN-after com a implementação.
- Browser focado do teste reescrito antes dos gates completos.
- Gates oficiais completos no container (`SIRHOSP_TEST_PROJECT` conforme
  ambiente corrente; ver seção Comandos).

## Comandos obrigatórios

```bash
SIRHOSP_TEST_PROJECT=sirhosp-structpend-s1 ./scripts/test-in-container.sh quality-gate
SIRHOSP_TEST_PROJECT=sirhosp-structpend-s1 ./scripts/test-in-container.sh integration
./scripts/markdown-lint.sh
git diff --check && git diff HEAD --check
```

## Condições de bloqueio

- Filtro por categoria do select "Tipo" quebrado pela remoção do termo de
  busca (D2) — não prosseguir com a função inteira removida.
- Qualquer dependência adicional de template/JS inesperada.
- Gates vermelhos sem causa clara e proporcional.
