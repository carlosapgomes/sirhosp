## 1. SOPBR-S1 — Normalização física e materialização v3

- [x] 1.1 Ler `slice-prompts/SLICE-SOPBR-S1.md`, registrar `BASE_REF`, estado
  limpo e baseline oficial unitário em container antes de editar.
- [x] 1.2 Criar primeiro testes RED sintéticos para duplicata exata, prontuário
  igual em leitos distintos, conflito de ocupante/status, leito sem identidade,
  privacidade, disponibilidade setorial e história v1/v2.
- [x] 1.3 Adicionar campos e migration aditiva para algoritmo do catálogo,
  disponibilidade, reconciliação física, parcialidade e exclusão diária, sem
  backfill ou edição de migrations existentes.
- [x] 1.4 Implementar `occupancy-v3` com normalização conservadora transversal,
  reconciliação agregada, disponibilidade/excedente por setor e elegibilidade
  diária, preservando despacho e valores v1/v2.
- [x] 1.5 Provar que duplicatas/conflitos afetam somente ocupação e não bloqueiam
  o fluxo clínico aceito.
- [x] 1.6 Executar gates oficiais em container, integração, inspeções e comparação
  de baseline; gerar `/tmp/sirhosp-slice-SOPBR-S1-report.md`, marcar este bloco,
  commit/push e parar somente com evidência completa.

## 2. SOPBR-S2 — Catálogo integral futuro e ativação explícita v3

- [x] 2.1 Confirmar S1 completo, ler `slice-prompts/SLICE-SOPBR-S2.md`, registrar
  novo baseline limpo e criar testes RED para algoritmo obrigatório, versão
  inválida, persistência e dry-run v3.
- [x] 2.2 Evoluir parsing, validação, resultado e persistência do catálogo para
  versão explícita de algoritmo em novas publicações, mantendo fallback
  estrutural somente para catálogos históricos.
- [x] 2.3 Adicionar novo JSON integral v3 sem editar os artefatos inicial ou
  corrigido, preservando 43 grupos, 48 associações, 47 códigos, quatro unrated e
  capacidades 666/666.
- [x] 2.4 Fazer dry-run reportar `occupancy-v3` e os totais aprovados sem escrita;
  manter publicação estritamente futura, atômica, idempotente e separada do
  deploy.
- [x] 2.5 Executar gates oficiais em container, integração, inspeções e comparação
  de baseline; gerar `/tmp/sirhosp-slice-SOPBR-S2-report.md`, marcar este bloco,
  commit/push e parar somente com evidência completa.

## 3. SOPBR-S3 — Duas realidades visuais em `/beds` e ADR

- [x] 3.1 Confirmar S2 completo, ler `slice-prompts/SLICE-SOPBR-S3.md`, registrar
  novo baseline limpo e criar testes RED da separação visual, reconciliação,
  posição única, conflito, fallback v1/v2 e autenticação.
- [x] 3.2 Construir a apresentação física exact-run com a mesma normalização v3,
  exibindo cada posição inequívoca uma vez e diagnósticos agregados seguros.
- [x] 3.3 Separar `/beds` em `Capacidade oficial e ocupação` e `Posições
  registradas no sistema legado`, com cards e tabelas próprios, disponibilidade
  oficial setorial e rótulos semânticos não intercambiáveis.
- [x] 3.4 Exibir ponte agregada v3, alertas de parcialidade e compatibilidade
  histórica v1/v2, preservando fallback pendente, detalhe nominal autorizado e
  `login_required`.
- [x] 3.5 Criar ADR-0005 e atualizar o índice, substituindo somente decisões de
  identidade física, deduplicação, conflito, disponibilidade e apresentação.
- [x] 3.6 Executar gates oficiais em container, Markdown lint, inspeções e
  comparação de baseline; gerar `/tmp/sirhosp-slice-SOPBR-S3-report.md`, marcar
  este bloco, commit/push e parar somente com evidência completa.

## 4. Encerramento e ativação operacional separada

- [x] 4.1 Auditar proposal, design, cinco delta specs, ADR, migration, código,
  JSON v3 e relatórios dos três slices; corrigir divergências antes da release.
- [x] 4.2 Executar `openspec validate separate-official-and-physical-bed-realities
  --strict`, `./scripts/test-in-container.sh quality-gate`,
  `./scripts/test-in-container.sh integration` e `./scripts/markdown-lint.sh`.
- [x] 4.3 Publicar release/imagem imutáveis e fazer backup/deploy sem ativar
  catálogo v3 durante build, migration ou subida dos containers.
- [x] 4.4 Antes da ativação, confirmar v2 vigente, zero medições v3 e dry-run
  futuro com algoritmo v3 e totais 43/48/47/666/666.
- [x] 4.5 Ativar explicitamente o catálogo v3 para a primeira data futura local
  aprovada, sem editar versões anteriores e sem backfill.
- [x] 4.6 No primeiro censo completo v3, validar somente com agregados seguros:
  reconciliação fechada, disponibilidade/excedente setoriais, duplicatas,
  conflitos, elegibilidade diária, duas seções em `/beds` e fluxo clínico.
