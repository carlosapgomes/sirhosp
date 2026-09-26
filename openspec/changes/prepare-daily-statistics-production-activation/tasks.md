## 1. Preflight somente leitura

- [x] 1.1 RED: adicionar testes sintéticos para tag/release imutável, comparação de assets, `.env` allowlisted, data futura, timer diário inativo, cadências recentes e saída sem PHI; executar o teste focado em container e registrar a falha esperada
- [x] 1.2 GREEN: implementar o preflight host-level fail-closed sem comandos mutáveis, rede/systemd/journal reais nos testes ou persistência de evidência; repetir o teste focado e regressões locais
- [x] 1.3 Gerar `/tmp/sirhosp-slice-PDSPA-S1-report.md` com antes/depois, comandos, riscos e prova de que nenhuma operação de produção foi executada; validar lint, typecheck e Markdown proporcionais

## 2. Assets na release imutável

- [x] 2.1 RED: adicionar testes de contrato para exigir preflight e os dois units de estatísticas antes da criação do draft, anexá-los na mesma operação e impedir publicação parcial; registrar RED em container
- [x] 2.2 GREEN: atualizar o workflow de release para validar e anexar os três assets sem alterar releases já publicadas; repetir testes focados e regressões de release
- [x] 2.3 Gerar `/tmp/sirhosp-slice-PDSPA-S2-report.md` e validar workflow, check, lint, typecheck e Markdown alterado sem criar tag, draft, imagem ou release

## 3. Checkpoint humano e runbook

- [x] 3.1 RED: adicionar testes estáticos para instalação desabilitada, execução do preflight, aceite humano, revalidação por expiração, ativação explícita posterior, observação agregada e rollback isolado; registrar RED em container
- [x] 3.2 GREEN: atualizar o runbook com o fluxo por tag exata e motivos fail-closed, sem documentar bypass, execução artificial de extrator ou persistência de journal clínico; repetir testes focados
- [x] 3.3 Gerar `/tmp/sirhosp-slice-PDSPA-S3-report.md` e executar check, lint, typecheck, Markdown e OpenSpec strict sem operar produção

## 4. Gate final do change

- [x] 4.1 Executar integrações relevantes e `./scripts/test-in-container.sh quality-gate`, `./scripts/markdown-lint.sh`, `openspec validate prepare-daily-statistics-production-activation --strict` e `git diff --check`, registrando os resultados em `/tmp/sirhosp-slice-PDSPA-S4-report.md`
- [x] 4.2 Revisar diff, scripts e documentação para confirmar ausência de PHI/credenciais, comandos mutáveis no preflight, tag/release criada, ativação, backfill, execução de extrator, Celery/Redis ou alteração clínica; parar para aceite humano
