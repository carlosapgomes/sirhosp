# Change: Tornar qualidade de ocupação acionável

## Why

A ativação de `occupancy-v3` confirmou que o censo pode estar completo para
extração e, ainda assim, conter conflitos ou linhas ocupadas sem identidade de
posição. Em 23/08/2026, cinco medições aceitas pelo gate de cobertura foram
materializadas corretamente, mas todas ficaram fora das estatísticas diárias
porque a política v3 torna qualquer conflito físico bloqueante.

Essa tolerância zero é inadequada para o objetivo operacional: o sistema de
origem sempre terá algum ruído, e a página deve tornar os problemas visíveis
para orientar melhoria progressiva, não eliminar dias inteiros de estatística.
Além disso, `/beds` usa nomes limpos na realidade oficial e nomes técnicos com
prefixos físicos na fotografia de origem, emprega a expressão pouco familiar
“sistema legado” e obriga o usuário a localizar o mesmo setor em duas listas
longas.

O change introduz `occupancy-v4` futuro e imutável. Censos já aceitos pelo gate
primário de pelo menos 40 setores passam a contribuir às estatísticas diárias
com ressalvas de qualidade. Conflitos são classificados pelo impacto real sobre
a ocupação, a reconciliação explica se cada evidência foi consolidada,
computada, não computada ou mantida fora do escopo da taxa, e todos os usuários
autenticados podem inspecionar os casos no contexto do setor.

## What Changes

- Introduzir `occupancy-v4`, selecionado somente por catálogo integral futuro,
  sem alterar ou recalcular v1, v2 ou v3.
- Manter como gate primário o critério existente de no mínimo 40 setores
  distintos antes da persistência do censo; este change não reduz nem duplica
  essa proteção.
- Tornar toda medição v4 materializada de um censo aceito elegível para resumo
  diário, preservando uma classificação separada de `com ressalvas`.
- Classificar conflitos de posição por impacto:
  - divergência apenas de ocupante com status ocupado e faixa compatível conta
    uma posição ocupada, sem escolher paciente autoritativo;
  - divergência de status não entra no numerador;
  - divergência etária em setor particionado não é atribuída arbitrariamente;
  - divergências entre estados não ocupados não afetam o numerador.
- Preservar deduplicação exata: linhas extras são consolidadas, enquanto a
  posição correspondente é contada uma vez.
- Manter linhas ocupadas sem leito fora do numerador, mas disponíveis como caso
  autenticado para correção.
- Separar posições ocupadas intencionalmente `unrated` de posições `unmapped`
  ou `linked_slots_pending`, evitando chamar todas de simples exclusão.
- Persistir reconciliação v4 schema 2 somente com agregados allowlisted e uma
  indicação explícita de qualidade, sem PHI no histórico.
- Adicionar contador diário de medições com ressalvas, sem reutilizar o contador
  histórico de medições v3 excluídas.
- Adicionar alias limpo e versionado por código-fonte no catálogo, mantendo o
  nome bruto do sistema de origem para auditoria.
- Substituir “sistema legado” por “sistema de origem” na interface.
- Manter dois resumos agregados separados e substituir as duas listas longas
  por uma única listagem expansível `Setores e posições`.
- Organizar a listagem única por unidades de apresentação derivadas do grafo
  entre grupos oficiais e códigos-fonte, cobrindo sem duplicação os casos 1:1,
  vários códigos em um grupo, 3A particionada e CO com vários códigos.
- Permitir que todo usuário autenticado veja os detalhes das alternativas em
  conflito e das linhas sem posição, claramente não autoritativos; a página
  continua protegida por `login_required`.
- Criar ADR substituindo somente as decisões de tratamento de conflito,
  elegibilidade v4, nomenclatura e composição visual da ADR-0005.

## Capabilities

### New Capabilities

Nenhuma. O change evolui catálogo, materialização, resumo e apresentação já
existentes.

### Modified Capabilities

- `occupancy-measurement-history`: adiciona algoritmo v4, tipagem de conflitos,
  reconciliação schema 2 e qualidade com ressalvas.
- `daily-occupancy-summary`: medições v4 aceitas entram nas estatísticas e são
  auditadas por contador de ressalvas, sem reinterpretar v3.
- `versioned-sector-capacity-catalog`: adiciona aliases limpos por código-fonte
  e catálogo integral v4 futuro.
- `bed-status-capacity-view`: usa “sistema de origem”, esclarece tratamentos e
  apresenta uma única listagem expansível com detalhes autenticados.

### Unchanged Capabilities

- `census-extraction-completeness`: continua rejeitando antes da persistência
  extrações com menos de 40 setores distintos e mantém defesa em profundidade.
- `census-snapshot-processing`: continua processando snapshots brutos e não é
  alterado pela classificação de qualidade de ocupação.

## Impact

- **Código:** `apps/census/models.py`, `apps/census/occupancy.py`,
  `apps/census/capacity_catalog.py`, `apps/census/views.py`, template de
  `/beds`, migrations aditivas, catálogo v4 e testes focados.
- **Banco:** campos aditivos para qualidade diária/medição e alias de origem;
  reconciliação continua em JSON agregado versionado; sem backfill.
- **UI:** dois resumos agregados e uma lista única; detalhes nominais continuam
  somente na página autenticada e nunca são copiados ao histórico agregado.
- **Operação:** release e deploy não ativam v4; publicação explícita para data
  futura local após dry-run, backup e deploy imutável.
- **Arquitetura:** monólito Django/PostgreSQL, sem Celery, Redis, microserviço,
  scheduler ou dependência nova.
- **Risco:** crítico, pois altera semântica de indicador oficial futuro e exibe
  detalhes de qualidade com PHI já autorizado; exige TDD, auditoria, release
  imutável e validação do primeiro censo v4 apenas por agregados seguros.

## Non-goals

- Alterar o limiar 40 ou tornar o gate configurável.
- Corrigir, apagar ou editar snapshots do sistema de origem.
- Fazer backfill de medições ou resumos v1, v2 ou v3.
- Tornar uma linha conflitante autoritativa ou escolher um paciente vencedor.
- Deduplicar prontuários entre posições diferentes ou inferir mãe-criança.
- Alterar capacidades 666/666, CO `unrated` ou partição etária 32/16 da 3A.
- Expor PHI em JSON histórico, logs, alertas agregados, relatórios ou consultas
  operacionais.
- Criar cadastro nominal de leitos oficiais.
- Alterar autenticação ou adicionar perfil de permissão neste change.

## Success Criteria

- Um censo com menos de 40 setores continua rejeitado antes de gerar medição.
- Uma medição v4 aceita com conflitos entra no resumo diário com ressalva.
- V3 continua excluindo parcialidade física exatamente como foi persistido.
- Conflito apenas de ocupante conta uma posição ocupada sem paciente vencedor.
- Conflito de status ou classificação etária não é resolvido arbitrariamente.
- A reconciliação fecha e explica consolidação, não cômputo e fora de escopo.
- Nomes limpos são versionados por código-fonte; nomes brutos permanecem apenas
  como proveniência secundária.
- `/beds` usa “sistema de origem”, mantém os dois resumos e mostra uma única
  lista de setores/posições sem duplicar posição física.
- Todos os autenticados podem expandir conflitos e linhas sem posição.
- V1–v3, histórico, exact-run, privacidade e fluxo clínico permanecem intactos.

## Dependency and sequencing

Este change depende da implementação concluída de
`separate-official-and-physical-bed-realities`. Antes da release v4, o change
anterior deve estar sincronizado nas specs canônicas e arquivado. A criação
destes artefatos não arquiva, modifica ou reabre o change anterior.
