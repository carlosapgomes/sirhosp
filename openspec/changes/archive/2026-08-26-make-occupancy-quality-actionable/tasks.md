## 1. MOQA-S1 — Conflitos tipados e elegibilidade occupancy-v4

- [x] 1.1 Ler `slice-prompts/SLICE-MOQA-S1.md`, registrar `BASE_REF`, árvore
      limpa e baseline unitário oficial em container antes de editar.
- [x] 1.2 Criar primeiro testes RED sintéticos para conflito apenas de ocupante,
      conflito de status, conflito etário particionado, duplicata, linha sem leito,
      reconciliação schema 2, privacidade, elegibilidade v4 e história v3.
- [x] 1.3 Adicionar campos e migration aditiva para qualidade v4 e contador
      diário de ressalvas, sem backfill nem edição de migrations existentes.
- [x] 1.4 Implementar `occupancy-v4` com tipagem conservadora por impacto,
      reconciliação fechada e resumo diário elegível com ressalvas.
- [x] 1.5 Provar que v1/v2/v3, disponibilidade, imutabilidade, exact-run e fluxo
      clínico mantêm a semântica anterior.
- [x] 1.6 Executar gates oficiais, integração e inspeções; gerar
      `/tmp/sirhosp-slice-MOQA-S1-report.md`, marcar este bloco, commit/push e parar.

## 2. MOQA-S2 — Catálogo v4 com aliases limpos por código-fonte

- [x] 2.1 Confirmar S1 completo, ler `slice-prompts/SLICE-MOQA-S2.md`, registrar
      novo baseline limpo e criar testes RED de alias obrigatório e algoritmo v4.
- [x] 2.2 Evoluir modelo, schema, parsing, validação, persistência e dry-run para
      alias limpo e versionado, preservando fallback somente para catálogos antigos.
- [x] 2.3 Adicionar JSON integral v4 sem editar catálogos anteriores, mantendo
      43/48/47, quatro `unrated`, capacidades 666/666, CO e 3A.
- [x] 2.4 Provar aliases determinísticos para relações 1:1, Cardio, 3A, CO e
      rejeição de alias vazio/divergente para o mesmo código.
- [x] 2.5 Executar gates oficiais, integração e inspeções; gerar
      `/tmp/sirhosp-slice-MOQA-S2-report.md`, marcar este bloco, commit/push e parar.

## 3. MOQA-S3 — Resumos separados e listagem única acionável em `/beds`

- [x] 3.1 Confirmar S2 completo, ler `slice-prompts/SLICE-MOQA-S3.md`, registrar
      baseline limpo e criar testes RED de terminologia, nomes, unidades, detalhes,
      privacidade, exact-run, histórico e autenticação.
- [x] 3.2 Construir unidades de apresentação do grafo grupo↔código, sem
      hardcode de 3A/CO/Cardio e sem duplicar posições físicas.
- [x] 3.3 Manter os dois resumos agregados e substituir as duas listas atuais
      por uma única lista detalhada `Setores e posições`, usando nomes limpos e
      “sistema de origem”.
- [x] 3.4 Exibir tratamento explícito das categorias e detalhes não autoritativos
      de conflitos/linhas sem posição para todos os usuários autenticados.
- [x] 3.5 Criar ADR-0006 e atualizar o índice, substituindo somente decisões de
      conflito, elegibilidade v4, nomes e composição visual da ADR-0005.
- [x] 3.6 Executar gates oficiais, integração, Markdown lint e inspeções; gerar
      `/tmp/sirhosp-slice-MOQA-S3-report.md`, marcar este bloco, commit/push e parar.

## 4. Encerramento, release e ativação operacional separada

- [x] 4.1 Auditar proposal, design, quatro delta specs, ADR, migrations, código,
      JSON v4 e relatórios dos três slices; corrigir divergências antes da release.
- [x] 4.2 Executar `openspec validate make-occupancy-quality-actionable --strict`,
      `./scripts/test-in-container.sh quality-gate`, integração e Markdown lint.
- [x] 4.3 Sincronizar e arquivar primeiro o change concluído
      `separate-official-and-physical-bed-realities`, se ainda estiver ativo.
- [x] 4.4 Publicar release/imagem imutáveis, criar backup protegido e fazer
      deploy sem ativar catálogo v4 durante build, migration ou subida.
- [x] 4.5 Confirmar v3 vigente antes da data aprovada, executar dry-run futuro v4
      com algoritmo, aliases e totais 43/48/47/666/666, provando ausência de escrita.
- [x] 4.6 Ativar explicitamente catálogo v4 para primeira data futura local
      aprovada, sem editar versões anteriores e sem backfill.
- [x] 4.7 No primeiro censo completo v4, validar somente agregados seguros:
      reconciliação, tipos de conflito, elegibilidade com ressalvas, resumo diário,
      aliases, lista única, detalhes autenticados e fluxo clínico.
- [x] 4.8 Sincronizar as quatro delta specs canônicas, validar e arquivar
      `make-occupancy-quality-actionable`; commit/push e parar.
