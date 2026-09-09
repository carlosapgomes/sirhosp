## 1. Preflight do change

- [x] 1.1 Registrar `BASE_REF`, confirmar working tree adequada e validar o
  baseline relevante antes do primeiro slice; não executar qualquer comando de
  produção ou backfill

## 2. SLICE-SCPED-S1 — Gráfico principal por saída capturada

- [x] 2.1 RED: adicionar testes sintéticos que provem uma única série por
  `saida_em`, inclusão de status pendentes, eixo calendário com zeros, médias e
  distribuição horária por saída; executar os testes focados em container e
  registrar a falha esperada
- [x] 2.2 GREEN: alterar view e template do gráfico com implementação mínima e
  verificar os mesmos testes focados mais a regressão local do portal
- [x] 2.3 Gerar `/tmp/sirhosp-slice-SCPED-S1-report.md` com checklist, arquivos,
  antes/depois, comandos, riscos e próximo passo; validar Markdown alterado com
  `./scripts/markdown-lint.sh`

## 3. SLICE-SCPED-S2 — Card e listagem coerentes com saída capturada

- [x] 3.1 RED: adicionar testes sintéticos para o card diário e a listagem por
  data incluírem `saida_em` independentemente da reconciliação e não dependerem
  de `DailyDischargeCount.records/raw_data`; executar o foco em container e
  registrar a falha esperada
- [x] 3.2 GREEN: ajustar dashboard e listagem com o menor blast radius e verificar
  os testes focados mais as regressões locais de dashboard/listagem
- [x] 3.3 Gerar `/tmp/sirhosp-slice-SCPED-S2-report.md` e validar todo Markdown
  alterado com `./scripts/markdown-lint.sh`

## 4. SLICE-SCPED-S3 — Qualidade de reconciliação fora do gráfico principal

- [x] 4.1 RED: adicionar testes de integração para comparação agregada de saídas
  capturadas, saídas reconciliadas e sumários na superfície protegida, incluindo
  negação sem permissão e ausência de identidade no payload
- [x] 4.2 GREEN: implementar o comparativo agregado na superfície existente de
  reconciliação sem alterar regras ou dados clínicos e verificar testes focados
  de permissão e apresentação
- [x] 4.3 Atualizar a ADR-0009 para distinguir indicador gerencial de evidência e
  agregado canônico de domínio; gerar
  `/tmp/sirhosp-slice-SCPED-S3-report.md` e executar
  `./scripts/markdown-lint.sh`

## 5. Gate final e handoff

- [ ] 5.1 Executar `./scripts/test-in-container.sh check`, testes unitários e de
  integração relevantes, `lint` e `typecheck`, registrando resultados
- [ ] 5.2 Executar `./scripts/test-in-container.sh quality-gate`,
  `./scripts/markdown-lint.sh` e
  `openspec validate show-captured-patient-exits-on-dashboard --strict`
- [ ] 5.3 Revisar diff e artefatos para confirmar ausência de migrations, dados
  reais, credenciais, mudanças no backfill ou alteração semântica de
  `DailyDischargeCount`; preparar release code-only e parar antes de qualquer
  operação em produção
