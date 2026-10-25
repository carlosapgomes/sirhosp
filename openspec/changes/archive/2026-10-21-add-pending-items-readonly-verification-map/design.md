# Design: add-pending-items-readonly-verification-map

Mudança somente documentação (`skip_specs: true`): registra as decisões que
guiaram o mapa de verificação read-only de pendências no skill
`verify-sirhosp`. Referências canônicas: `proposal.md`;
`.pi/skills/verify-sirhosp/features/pending-items.md`; revisão do estado
aplicado em `3e480b0`.

## Decision 1: contraste de escopo — docs-only, política intocada

Apenas 3 arquivos do skill mudam (`SKILL.md`, `features/README.md`,
`features/pending-items.md`). Sem código, migrations, dependências ou
alterações na suíte `dev-browser-verification` (especificação intocada,
motivo do `skip_specs`).

## Decision 2: estrutura do mapa segue o contrato existente

`pending-items.md` usa o mesmo contrato dos maps anteriores (ver
`features/census.md`): H1 + introdução + exatamente 4 seções H2
(`Sub-features`, `How to get to it (user POV)`,
`Driving it with Chrome DevTools MCP`, `Gotchas`), com vocabulário de status
honesto (`proven`/`demonstrated`/`future`) e o round MCP nascendo `future`
(exige janela dev autorizada, dataset fictício confirmado e workers parados).

## Decision 3: provas negativas por nome acessível, nunca por `data-testid`

Snapshots de acessibilidade expõem papéis e nomes, não testids — checagens de
ausência por `data-testid` passam de forma vazia. As provas negativas usam
nomes acessíveis reais (`Nova pendência`, `Cadastrar pendência`, `Editar`,
`Finalizar`) e o `Gotchas` registra a vacuidade como armadilha.

## Decision 4: contrato de desfecho vazio explícito

Superfícies sem dependência de item (painel, indicadores, histórico, filtros)
podem PASSAR legitimamente vazias. Jornadas dependentes de item
(`pend-history-fragment`, `pend-contextual-read`, `pend-contextual-history`)
ficam **BLOCKED** sem um item — nunca PASS, nunca fabricar dado, nunca ligar
workers para satisfazer verificação.

## Decision 5: leitor como perspectiva e proibições explícitas

A jornada assistida é da perspectiva de leitor (`verify_user` fora do grupo
`Desospitalização`). Escritas e `export.xlsx` permanecem proibidas mesmo como
GET; as listas de rotas no `SKILL.md` e no `features/README.md` separam
leituras permitidas, GET-proibido e POST-proibido.

## Decision 6: rótulos PT exatos em linha única

Rótulos literais dos cards permanecem em linha única (MD013 desativada no
projeto) para permitir a conferência mecânica de strings contra o código
(31/31 checks de rótulos/handles/rotas executados).

## Decision 7: prefixo de rota `/painel/` como pré-condição canônica

Pré-condição de todas as jornadas: login seguido de `/painel/` (estado
pós-login usado pelo contrato de navegação do skill).
