# Proposal: improve-beds-v5-page-ux — `/beds` v5 com leitura rápida

## Why

O `occupancy-v5` está vigente em produção desde 2026-08-26 (medição 607/666 =
91,14% no primeiro censo) e a auditoria do CIPOO-S6 confirmou que a semântica
da página está correta. A experiência de uso, porém, ficou insatisfatória para
a leitura rápida da situação do hospital:

1. a seção `Como os pacientes foram contados` ocupa muito espaço vertical
   entre o resumo oficial e a lista de setores;
2. os cabeçalhos dos cards collapsibles mostram apenas a contagem de
   pacientes; capacidade, taxa, saldo e excedente ficam escondidos no corpo;
3. não existe mais um resumo da situação real que inclua todos os pacientes
   identificados, dentro e fora da taxa oficial (o antigo resumo físico foi
   removido corretamente na v5, mas nada o substituiu em nível agregado);
4. o badge `N códigos de origem` no cabeçalho não ajuda o usuário típico;
5. cada paciente carrega um badge `contado na taxa oficial` ou
   `fora da taxa oficial` redundante com o próprio setor;
6. a renderização autenticada executa ~140 queries para 42 unidades (N+1 no
   caminho catálogo→grupos→memberships), dívida registrada no relatório S6.

## What Changes

- **IBPU-S1**: nova seção `Situação real do hospital` logo após o resumo
  oficial, com total de pacientes identificados (na taxa + fora da taxa) e
  contagens dos estados operacionais (vagos, reservados, manutenção,
  isolamento), derivadas exclusivamente de `physical_reconciliation_json`
  persistido; a ponte `Como os pacientes foram contados` muda para o fim da
  página, dentro de collapsible recolhido por padrão.
- **IBPU-S2**: cabeçalhos dos cards v5 expõem as métricas oficiais persistidas
  por grupo (`[N pacientes] [Cap. X] [Y%] [Saldo Z]`, `Acima da capacidade ·
  excedente W` textual, `fora da taxa oficial` para unrated, `0 pacientes`
  explícito, 3A com uma linha por partição sem total combinado); remoção do
  badge de contagem de códigos do cabeçalho e dos badges por paciente de
  política de contagem, preservando exceções factuais.
- **IBPU-S3**: fim do N+1 com prefetch no caminho exact-run da página e teste
  de orçamento de queries que prova que o custo não cresce com o número de
  grupos do catálogo.
- **IBPU-S4**: release imutável `v0.1.0-rc.12` (somente UI: sem migration, sem
  catálogo novo, sem comando de ativação) e deploy em produção com runbook,
  backup, verificação e rollback trivial.

## Impact

- **Especs**: delta somente em `bed-status-capacity-view` — requisitos
  ADDED (resumo da situação real; métricas nos cabeçalhos; orçamento de
  queries) e MODIFIED (ponte recolhida ao fim; política de contagem
  comunicada no nível da unidade; aviso de acima da capacidade visível no
  cabeçalho).
- **Código**: apresentação v5 em `apps/census/occupancy.py`, branch v5 de
  `apps/census/templates/census/bed_status.html` e testes em
  `tests/unit/test_bed_status_view.py`; runbook/índice/teste de release no
  S4.
- **Produção**: RC11 permanece imutável; a melhoria entra por RC12 após
  gates; rollback volta à RC11 sem risco de schema.
- **Inalterado**: modelos, migrations, catálogos, medições, resumos diários,
  cálculo persistido, branches históricos v1–v4 da página, autenticação
  (anônimo 302) e privacidade exact-run.

## Out of scope

- Redesenho visual geral, CSS/JS novos ou mudanças nas versões v1–v4 da
  página.
- Qualquer alteração em `occupancy-v5` de cálculo, catálogo ou persistência.
- Novos campos persistidos ou backfill; qualquer dado nominal em agregados.
- Otimizações além do orçamento de queries da página `/beds`.

## Success Criteria (binários)

- [ ] v5 renderiza `Situação real do hospital` entre o resumo oficial e a
  lista de setores, somente com agregados persistidos, fechando a soma
  `na taxa + fora da taxa = total`.
- [ ] v5 renderiza a ponte após a lista de setores, recolhida por padrão
  (`collapse` sem `show`, gatilho com `aria-expanded="false"`), com o mesmo
  conteúdo agregado.
- [ ] Cabeçalhos v5 mostram pacientes/capacidade/taxa/saldo ou excedente por
  grupo, `0 pacientes` explícito, 3A por partição sem total 48, unrated sem
  taxa, e sem badge de contagem de códigos.
- [ ] Nenhum badge por paciente de `contado na taxa oficial` ou
  `fora da taxa oficial`; exceções factuais permanecem.
- [ ] Teste de orçamento prova que dobrar/triplicar grupos do catálogo não
  aumenta o número de queries além de folga fixa.
- [ ] Regressão v1–v4 intocada; anônimo 302; zero PHI em relatórios/tests.
- [ ] `v0.1.0-rc.12` publicada pelo workflow oficial e implantada em
  produção saudável com dez workers e `/beds` validado por agregados.
