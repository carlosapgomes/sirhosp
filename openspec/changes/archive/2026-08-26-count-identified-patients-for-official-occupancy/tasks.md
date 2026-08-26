## 1. CIPOO-S1 — Medição v5 por paciente identificado

- [x] 1.1 Ler `slice-prompts/SLICE-CIPOO-S1.md`, registrar `BASE_REF`, árvore
  limpa e baseline oficial em container antes de editar.
- [x] 1.2 Criar testes RED sintéticos para identidade numérica/nome válido,
  paciente sem leito, dois pacientes no mesmo leito, deduplicação por grupo,
  múltiplos grupos, nomes variantes e identificação incompleta.
- [x] 1.3 Criar testes RED da 3A para faixa confiável, desconhecida,
  contraditória, prefixo literal `RN`, fallback adulto e deduplicação antes da
  partição.
- [x] 1.4 Implementar `occupancy-v5`, migration aditiva, reconciliação privada
  fechada, qualidade agregada e elegibilidade no resumo diário.
- [x] 1.5 Provar regressão v1–v4, aritmética setorial, CO/unrated, exact-run,
  privacidade, idempotência e continuidade do fluxo clínico.
- [x] 1.6 Executar gates oficiais, gerar
  `/tmp/sirhosp-slice-CIPOO-S1-report.md`, marcar somente S1, commit/push e parar.

## 2. CIPOO-S2 — Catálogo integral occupancy-v5

- [x] 2.1 Ler `slice-prompts/SLICE-CIPOO-S2.md`, confirmar S1 completo e
  registrar novo baseline limpo.
- [x] 2.2 Criar testes RED para algoritmo v5 permitido, documento integral,
  preservação byte a byte dos quatro catálogos anteriores e hash próprio.
- [x] 2.3 Adicionar catálogo v5 com 43/48/47, 39 standard, quatro unrated,
  666/666, aliases 48/48, CO e 3A 32/16 inalterados.
- [x] 2.4 Provar dry-run sem escrita, publicação futura atômica/idempotente e
  rejeição de algoritmo/data/hash inválidos.
- [x] 2.5 Executar gates oficiais, gerar
  `/tmp/sirhosp-slice-CIPOO-S2-report.md`, marcar somente S2, commit/push e parar.

## 3. CIPOO-S3 — `/beds` por pacientes e estados de leitos

- [x] 3.1 Ler `slice-prompts/SLICE-CIPOO-S3.md`, confirmar S2 completo e criar
  testes RED de cards, terminologia, pacientes deduplicados e estados
  operacionais.
- [x] 3.2 Construir apresentação v5 efêmera por grupo oficial: uma pessoa por
  prontuário, todos os nomes/leitos, repetição entre grupos e identificação
  incompleta, sem persistência adicional.
- [x] 3.3 Simplificar o resumo v5 e substituir conflitos físicos por mensagens
  factuais de leito/estado repetido; preservar UI histórica v1–v4.
- [x] 3.4 Provar exact-run, 302 anônimo, detalhes para autenticados, privacidade,
  Cardio, CO, 3A e setores sem capacidade.
- [x] 3.5 Criar ADR-0007 e atualizar índice, documentando a substituição somente
  para v5 das decisões de unidade de contagem das ADR-0005/0006.
- [x] 3.6 Executar gates oficiais e Markdown lint, gerar
  `/tmp/sirhosp-slice-CIPOO-S3-report.md`, marcar somente S3, commit/push e parar.

## 4. CIPOO-S4 — Auditoria, release e deploy sem ativação

- [x] 4.1 Ler `slice-prompts/SLICE-CIPOO-S4.md` e auditar proposal, design,
  quatro delta specs, ADR, migration, código, JSON e relatórios S1–S3.
- [x] 4.2 Executar check, unit, integration, lint, typecheck, quality-gate,
  OpenSpec strict e Markdown lint; qualquer falha bloqueia release.
- [x] 4.3 Criar runbook/index da próxima RC, incluindo hashes, backup, rollback
  forward-only e separação obrigatória entre deploy e catálogo.
- [x] 4.4 Publicar release/imagem imutáveis pelo workflow oficial; em produção,
  drenar, criar backup protegido e implantar sem dry-run/publicação v5.
- [x] 4.5 Confirmar RC nova saudável, migrations, dez workers, v4 vigente e zero
  catálogos/medições v5; gerar `/tmp/sirhosp-slice-CIPOO-S4-report.md`, marcar
  somente S4 e parar.

## 5. CIPOO-S5 — Dry-run e publicação futura v5

- [x] 5.1 Ler `slice-prompts/SLICE-CIPOO-S5.md`, obter autorização explícita da
  data futura e confirmar release nova, v4 vigente e backup válido.
- [x] 5.2 Executar dry-run v5 com algoritmo, hash, 43/48/47/39/4/666/666 e aliases
  48/48, provando snapshot agregado idêntico antes/depois.
- [x] 5.3 Publicar explicitamente o mesmo documento para a data aprovada e provar
  retry idempotente, versões anteriores intactas e zero medição/backfill v5.
- [x] 5.4 Confirmar seleção v4 no dia corrente e v5 na data futura; gerar
  `/tmp/sirhosp-slice-CIPOO-S5-report.md`, marcar somente S5 e parar.

## 6. CIPOO-S6 — Primeiro censo v5 e arquivamento

- [x] 6.1 Ler `slice-prompts/SLICE-CIPOO-S6.md` e aguardar o primeiro censo
  completo cujo local date usa o catálogo v5; não usar medição v4 como fallback.
- [x] 6.2 Validar somente agregados seguros: ponte de linhas/pacientes, políticas
  standard, unrated, pending e unmapped, duplicações, fallback RN, múltiplos
  grupos, saldo/excedente e elegibilidade diária.
- [x] 6.3 Validar `/beds` autenticado, 302 anônimo, cards sem redundância,
  pacientes/leitos/estados, setores sem capacidade e ausência da terminologia
  proibida v5, sem registrar PHI.
- [x] 6.4 Confirmar fluxo clínico, filas, dez workers, health e zero erro
  estrutural; nenhuma mutação manual de dados.
- [x] 6.5 Sincronizar as quatro delta specs canônicas, validar estritamente e
  arquivar primeiro `make-occupancy-quality-actionable` conforme seu estado e
  depois este change sem perder rastreabilidade histórica.
- [x] 6.6 Gerar `/tmp/sirhosp-slice-CIPOO-S6-report.md`, marcar S6, commit/push e
  parar.
