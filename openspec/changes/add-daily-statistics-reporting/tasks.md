## 1. Preflight do change

- [x] 1.1 Registrar `BASE_REF`, confirmar working tree adequada, validar o baseline relevante e documentar que nenhum comando de produção, backfill histórico ou dado real será usado
- [x] 1.2 Criar e aceitar a ADR da projeção diária materializada/versionada, autorização de dados sensíveis, revisão automática e rollback; validar o Markdown com `./scripts/markdown-lint.sh`

## 2. SLICE-DSRS-S1 — Seleção do dia estatístico

- [x] 2.1 RED: adicionar testes sintéticos para censo aceito, abertura, fechamento, âncora, limites `America/Bahia`, distinção do lote clínico e dias incompletos; executar os testes focados em container e registrar a falha esperada
- [x] 2.2 GREEN: criar o módulo de relatórios e o serviço mínimo de seleção determinística sem persistir relatórios; repetir os testes focados e executar check, lint e typecheck proporcionais
- [x] 2.3 Gerar `/tmp/sirhosp-slice-DSRS-S1-report.md` com checklist, arquivos, antes/depois, comandos, riscos e próximo passo; validar todo Markdown alterado com `./scripts/markdown-lint.sh`

## 3. SLICE-DSRS-S2 — Fotografia final materializada

- [x] 3.1 RED: adicionar testes sintéticos para schema, revisão corrente única, idempotência, catálogo/medição exatos, setores oficiais e pacientes do censo de fechamento; executar os testes focados em container e registrar a falha esperada
- [x] 3.2 GREEN: adicionar modelos, migration e materialização atômica mínima da fotografia final, sem eventos clínicos nem backfill; repetir testes focados e regressões locais
- [x] 3.3 Gerar `/tmp/sirhosp-slice-DSRS-S2-report.md` e validar migration, check, lint, typecheck e Markdown alterado

## 4. SLICE-DSRS-S3 — Entradas e transferências detectadas

- [x] 4.1 RED: adicionar testes para comparação âncora→abertura→fechamento, internação externa, transferência hospitalar, troca de leito sem evento, identidade ambígua, origem desconhecida, evento único com duas pernas e ordenação natural; registrar RED em container
- [x] 4.2 GREEN: implementar política versionada de origem e derivação idempotente de entradas/transferências a partir de censos consecutivos, mantendo intervalos de detecção e os rótulos explícitos `Entrada no setor — origem não identificada` e `Transferência interna — origem não identificada`; repetir testes focados e regressões locais
- [x] 4.3 Gerar `/tmp/sirhosp-slice-DSRS-S3-report.md` e executar check, lint, typecheck e Markdown alterado

## 5. SLICE-DSRS-S4 — Saídas, precedência e revisões automáticas

- [x] 5.1 RED: adicionar testes para óbito exato ou sem hora, `saida_em`, transferência, `Transferência interna — destino não identificado`, `Saída do setor — destino não identificado`, setor inferido/desconhecido, precedência sem dupla contagem e revisão por evidência tardia; registrar RED em container
- [x] 5.2 GREEN: implementar classificação de saídas e publicação transacional de revisões automáticas sem alterar fontes clínicas nem oferecer correção manual; repetir testes focados e regressões locais
- [x] 5.3 Gerar `/tmp/sirhosp-slice-DSRS-S4-report.md` e executar check, lint, typecheck e Markdown alterado

## 6. SLICE-DSRS-S5 — Fechamento diário operacional

- [x] 6.1 RED: adicionar testes de integração para comando por data, finalização limitada a datas pós-ativação, no-op idempotente, falha segura, qualidade degradada e concorrência; registrar RED em container
- [x] 6.2 GREEN: implementar management command de materialização/finalização diária com coordenação PostgreSQL, saída sem identidade clínica e nenhum rebuild histórico implícito; repetir testes focados e regressões operacionais locais
- [x] 6.3 Gerar `/tmp/sirhosp-slice-DSRS-S5-report.md` e executar check, lint, typecheck e Markdown alterado

## 7. SLICE-DSRS-S6 — Página e navegação autorizadas

- [x] 7.1 RED: adicionar testes para `/statistics/`, permissões, default de data, estado sem relatório, `no-store`, menu entre Leitos e Fluxo Hospitalar, badges, collapsibles acessíveis, eventos com origem/destino não identificado e ordenação por leito; registrar RED em container
- [x] 7.2 GREEN: implementar rota, view fina, apresentação, template e menu consumindo somente a revisão materializada; repetir testes focados e verificar orçamento de queries
- [x] 7.3 Gerar `/tmp/sirhosp-slice-DSRS-S6-report.md` e executar check, lint, typecheck e Markdown alterado

## 8. SLICE-DSRS-S7 — XLSX e auditoria de exportação

- [x] 8.1 RED: adicionar testes para permissão independente, uma folha por setor, nomes válidos/únicos, seções vazias, quantidades, campos/ordenação, formula injection, `no-store`, ausência de arquivo persistido e log somente após resposta pronta; registrar RED em container
- [x] 8.2 GREEN: implementar exporter `openpyxl`, endpoint e log agregado de arquivo gerado/servido a partir da mesma projeção da página; repetir testes focados e regressões locais
- [x] 8.3 Gerar `/tmp/sirhosp-slice-DSRS-S7-report.md` e executar check, lint, typecheck e Markdown alterado

## 9. SLICE-DSRS-S8 — Ativação futura e observabilidade

- [ ] 9.1 RED: adicionar validações sintéticas/estáticas para serviço e timer de fechamento, data de ativação obrigatória, ausência de backfill implícito, precedência operacional e logs sem identidade; registrar a falha esperada
- [ ] 9.2 GREEN: adicionar runtime systemd, documentação de ativação/rollback e observabilidade agregada, condicionado à evidência das cadências de altas intradiárias, D-1 e óbitos; executar validações focadas sem operar produção
- [ ] 9.3 Gerar `/tmp/sirhosp-slice-DSRS-S8-report.md`, validar deploy/docs e executar `./scripts/markdown-lint.sh`

## 10. Gate final e handoff

- [ ] 10.1 Executar `./scripts/test-in-container.sh check`, testes unitários e de integração relevantes, `lint` e `typecheck`, registrando resultados
- [ ] 10.2 Executar `./scripts/test-in-container.sh quality-gate`, `./scripts/markdown-lint.sh` e `openspec validate add-daily-statistics-reporting --strict`
- [ ] 10.3 Revisar diff, migrations, permissões, logs e artefatos para confirmar ausência de dados reais, correção manual, backfill histórico, workbook persistido, Celery/Redis e alteração das fontes clínicas; preparar ativação futura e parar antes de qualquer ação em produção
