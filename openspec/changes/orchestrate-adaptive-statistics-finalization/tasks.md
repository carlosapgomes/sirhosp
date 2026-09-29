## 1. Preflight do change

- [x] 1.1 Registrar `BASE_REF`, confirmar working tree sem mudanças relacionadas e executar `openspec validate orchestrate-adaptive-statistics-finalization --strict`; preservar a saída no relatório do primeiro slice.
- [x] 1.2 Confirmar que `orchestrate-d1-exit-recovery` e `orchestrate-intraday-discharge-recovery` não possuem implementação concorrente no mesmo arquivo; registrar que seus deltas devem ser sincronizados e ambos os changes arquivados antes do arquivamento de OASF.

## 2. SLICE-OASF-S1 — Revisão degradada auditável

- [x] 2.1 Adicionar testes RED dos avisos allowlisted `d1_recovery_incomplete` e `d1_recovery_not_confirmed` no comando de data explícita, incluindo persistência, fingerprint/revisão, remoção posterior e recusa de texto livre; verificar a falha focada antes da implementação.
- [x] 2.2 Implementar a passagem determinística de avisos operacionais pelo comando e materializador, sem migration e sem alterar `--finalize`; verificar GREEN nos testes focados.
- [x] 2.3 Executar `./scripts/test-in-container.sh integration`, lint/typecheck proporcionais e OpenSpec strict; gerar `/tmp/sirhosp-slice-OASF-S1-report.md` com RED/GREEN e snippets antes/depois.
- [x] 2.4 Obter revisão independente do slice e corrigir apenas achados P0/P1 antes de marcar o slice concluído.

## 3. SLICE-OASF-S2 — Pipeline adaptativo D-1 → estatísticas

- [x] 3.1 Adicionar testes RED para ordem D-1 → drenagem → materialização → hourly → censo, pendência sem chamadas repetidas, reavaliação da fila, restart após 05:00 com/sem revisão pronta, recusa de segunda tentativa no mesmo processo, falhas isoladas e logs agregados.
- [x] 3.2 Implementar a FSM em memória, a recuperação pós-05:00 baseada em revisão `ready` e os marcadores canônicos D-1/hourly, chamando a data D-1 explícita uma vez por processo na primeira drenagem segura; verificar GREEN focado.
- [x] 3.3 Passar fronteira/lookback ao `census_orchestrator` no Compose, manter os timers hourly/D-1/estatístico como fallback inerte e fixar esses contratos em testes estáticos.
- [x] 3.4 Criar ADR-0012 e atualizar seu índice com propriedade adaptativa, alternativas, rollback e ausência de nova infraestrutura; executar Markdown lint.
- [x] 3.5 Executar `./scripts/test-in-container.sh unit`, lint/typecheck proporcionais e OpenSpec strict; gerar `/tmp/sirhosp-slice-OASF-S2-report.md` com RED/GREEN e snippets antes/depois.
- [x] 3.6 Obter revisão independente do slice e corrigir apenas achados P0/P1 antes de marcar o slice concluído.

## 4. SLICE-OASF-S3 — Preflight reconhece o runtime adaptativo

- [x] 4.1 Adicionar testes RED do preflight para Compose imutável, bootstrap corrente antes das 20:00, timers hourly/D-1 legados desabilitados, evidências naturais hourly/D-1 do container e allowlist de comandos Docker read-only.
- [x] 4.2 Implementar o parser fail-closed dos marcadores canônicos e das sequências transitórias ordenadas da RC31, sem ecoar log bruto, combinar execuções ou aceitar journals manuais; verificar GREEN focado com fixtures sintéticas adversariais.
- [x] 4.3 Executar `./scripts/test-in-container.sh unit`, lint/typecheck proporcionais e OpenSpec strict; gerar `/tmp/sirhosp-slice-OASF-S3-report.md` com RED/GREEN e snippets antes/depois.
- [x] 4.4 Obter revisão independente do slice e corrigir apenas achados P0/P1 antes de marcar o slice concluído.

## 5. SLICE-OASF-S4 — Handoff operacional e assets de fallback

- [x] 5.1 Atualizar os contratos estáticos dos units hourly, D-1 e estatístico para fallback desabilitado e adicionar testes RED/GREEN que rejeitem a antiga ativação por timer.
- [x] 5.2 Atualizar `deploy/README.md`, `.env.example` e o runbook `v0.1.0-rc.32` para instalação dormente, preflight, aceite humano, recriação isolada do orquestrador, checkpoint de ausência às 07:30, fallback que preserva avisos sem D-1 comprovado, observação e rollback; verificar contratos estáticos.
- [x] 5.3 Executar `./scripts/test-in-container.sh unit`, Markdown lint e OpenSpec strict; gerar `/tmp/sirhosp-slice-OASF-S4-report.md` com RED/GREEN e snippets antes/depois.
- [x] 5.4 Obter revisão independente do slice e corrigir apenas achados P0/P1 antes de marcar o slice concluído.

## 6. Gate final e ativação operacional

- [x] 6.1 Executar `./scripts/test-in-container.sh integration` e `./scripts/test-in-container.sh quality-gate`, além de `./scripts/markdown-lint.sh` e `openspec validate orchestrate-adaptive-statistics-finalization --strict`; registrar contagens e resultados no relatório final.
- [x] 6.2 Verificar diff completo, ausência de PHI/credenciais, migrations inesperadas, comandos mutáveis no preflight e inconsistências entre specs, ADR, Compose, assets e runbooks; gerar `/tmp/sirhosp-slice-OASF-FINAL-report.md`.
- [x] 6.3 Publicar a RC32 imutável somente após o gate verde e confirmar imagem, digest, Compose, preflight, units e runbook na mesma release.
- [x] 6.4 Implantar a RC dormente, manter timers hourly/D-1/estatístico desabilitados, configurar a fronteira permitida, executar preflight `PASS` e obter aceite humano explícito antes de recriar somente `census_orchestrator`.
- [x] 6.5 Observar execuções naturais hourly e D-1 → drenagem → materialização, confirmar ausência de relatório anterior à fronteira e, após 05:00, verificar que ausência de revisão aciona uma única recuperação `d1_recovery_not_confirmed`; às 07:30, alertar e exigir decisão humana se ainda não houver revisão `ready`, registrando somente evidência agregada.
- [ ] 6.6 Sincronizar e arquivar `orchestrate-d1-exit-recovery` e `orchestrate-intraday-discharge-recovery` antes de arquivar OASF; em falha operacional, executar o rollback documentado sem apagar revisões.
