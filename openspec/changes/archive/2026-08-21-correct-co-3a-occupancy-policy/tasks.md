## 1. CCO3A-S1 — Faixa etária mínima no snapshot

- [x] 1.1 Ler o prompt autocontido
  `slice-prompts/SLICE-CCO3A-S1.md`, registrar baseline limpo e criar primeiro
  os testes RED da normalização `under_12`, `age_12_or_over`, `unknown` e
  `not_applicable`.
- [x] 1.2 Adicionar campo/choices e migration aditiva para a faixa etária do
  snapshot, sem backfill demográfico e sem alterar migrations existentes.
- [x] 1.3 Propagar a coluna `idade` já extraída pelo CSV até
  `CensusSnapshot`, persistindo somente a faixa normalizada e preservando setor,
  código e fluxo clínico.
- [x] 1.4 Cobrir formatos inteiro, `Nm`, `NmDd`, limite exato de 12, entradas
  inválidas, linhas não ocupadas e regressão do comando de extração.
- [x] 1.5 Executar os gates oficiais em container, inspeções e comparação de
  baseline; gerar `/tmp/sirhosp-slice-CCO3A-S1-report.md`, marcar este bloco
  somente com evidência completa, commit/push e parar.

## 2. CCO3A-S2 — Catálogo futuro particionado e dry-run corrigido

- [x] 2.1 Confirmar S1 completo, ler
  `slice-prompts/SLICE-CCO3A-S2.md`, registrar novo baseline e criar testes RED
  para seletores `all`/etários, ambiguidades e totais 43/48/47/666/666.
- [x] 2.2 Adicionar seletor temporal à associação de setor, constraints e
  migration aditiva que aceitem somente `all` ou o par etário completo e
  exclusivo, preservando catálogos existentes como `all`.
- [x] 2.3 Evoluir parsing, validação, persistência e resultado de ativação para
  copiar o seletor e distinguir associações de códigos-fonte.
- [x] 2.4 Adicionar novo JSON integral corrigido sem editar o catálogo inicial:
  CO unrated, Adulto 32, Infantil 16 e demais 40 grupos preservados.
- [x] 2.5 Fazer o dry-run reportar 43 grupos, 48 associações, 47 códigos
  distintos e capacidades 666/666 sem escrita; proibir ativação automática.
- [x] 2.6 Executar gates oficiais em container, inspeções e comparação de
  baseline; gerar `/tmp/sirhosp-slice-CCO3A-S2-report.md`, marcar este bloco
  somente com evidência completa, commit/push e parar.

## 3. CCO3A-S3 — Materialização occupancy-v2 e resumo elegível

- [x] 3.1 Confirmar S2 completo, ler
  `slice-prompts/SLICE-CCO3A-S3.md`, registrar novo baseline e criar testes RED
  para despacho v1/v2, CO sem taxa, partição 3A, linha desconhecida e história
  imutável.
- [x] 3.2 Adicionar campos auditáveis/migration para cobertura oficial,
  classificação parcial e contagens diária total/elegível/excluída, sem alterar
  tabelas históricas existentes.
- [x] 3.3 Implementar despacho explícito por catálogo: v1 intacto e v2 aplicando
  cada seletor à faixa da própria linha, sem deduplicar prontuário.
- [x] 3.4 Materializar CO bruto unrated, 3A Adulto/Infantil, taxa pontual parcial,
  cobertura 39/43 e capacidades 666/666 com privacidade agregada.
- [x] 3.5 Excluir integralmente medição v2 age-partial das estatísticas diárias,
  preservando total, elegíveis, excluídas e campos nulos quando nenhuma for
  elegível.
- [x] 3.6 Cobrir idempotência, sobrelotação, código desconhecido, processamento
  clínico não bloqueado e ausência de regressão v1.
- [x] 3.7 Executar gates oficiais em container, inspeções e comparação de
  baseline; gerar `/tmp/sirhosp-slice-CCO3A-S3-report.md`, marcar este bloco
  somente com evidência completa, commit/push e parar.

## 4. CCO3A-S4 — Apresentação `/beds` e decisão arquitetural

- [x] 4.1 Confirmar S3 completo, ler
  `slice-prompts/SLICE-CCO3A-S4.md`, registrar novo baseline e criar testes RED
  da apresentação v2 e regressões v1/autenticação.
- [x] 4.2 Mostrar CO uma vez, com dados brutos, sem capacidade/percentual e com
  texto explícito de exclusão da taxa da unidade.
- [x] 4.3 Mostrar Adulto 32 e Infantil 16 com ocupados classificados uma única
  vez e agrupar posições não ocupadas/idade desconhecida uma única vez em seção
  auxiliar sem capacidade.
- [x] 4.4 Mostrar cobertura oficial 39/43, capacidades 666/666 e alerta seguro de
  taxa parcial/medição excluída da média diária, preservando apresentação v1,
  fallback exato e permissões.
- [x] 4.5 Criar ADR substitutiva para as decisões de CO e 3A e atualizar o índice
  de ADRs, sem reescrever a ADR-0003.
- [x] 4.6 Executar gates oficiais em container, Markdown lint, inspeções e
  comparação de baseline; gerar
  `/tmp/sirhosp-slice-CCO3A-S4-report.md`, marcar este bloco somente com
  evidência completa, commit/push e parar.

## 5. Encerramento e ativação operacional separada

- [x] 5.1 Executar auditoria independente de consistência entre proposal,
  design, cinco delta specs, ADR, código, migrations e relatórios dos quatro
  slices; corrigir qualquer divergência antes da release.
- [x] 5.2 Executar `openspec validate correct-co-3a-occupancy-policy --strict`,
  quality gate oficial completo e Markdown lint global sem erro.
- [x] 5.3 Publicar release imutável e fazer deploy sem ativar catálogo durante
  build, migration ou subida de containers.
- [x] 5.4 Após o deploy, executar dry-run do novo documento para a primeira data
  futura local e confirmar 43 grupos, 48 associações, 47 códigos distintos,
  capacidade conhecida 666 e calculável 666.
- [x] 5.5 Ativar explicitamente para essa data futura em `America/Bahia`, sem
  editar a versão `2026-08-19` e sem backfill.
- [x] 5.6 No primeiro censo completo v2, verificar CO sem taxa, duas linhas 3A,
  cobertura 39/43, privacidade, elegibilidade diária e ausência de regressão no
  fluxo clínico.
