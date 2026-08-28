# Tasks: Reparar o pipeline persistente de internações

## 1. RPAP-S1 — Preservar o snapshot real do iframe

- [x] 1.1 Ler integralmente `slice-prompts/SLICE-RPAP-S1.md` antes de editar.
- [x] 1.2 Registrar baseline oficial e criar RED com handle sem `set_html()` e
      HTML superior sem a tabela do iframe.
- [x] 1.3 Implementar transporte transitório do snapshot no bridge e limpeza em
      todas as fronteiras definidas.
- [x] 1.4 Provar sequência de jobs sem reutilização, sem novo browser/subprocess
      e sem alteração do DOM real.
- [x] 1.5 Rodar inspeções e gates oficiais do slice.
- [x] 1.6 Criar `/tmp/sirhosp-slice-RPAP-S1-report.md` e parar.

## 2. RPAP-S2 — Falhar captura vazia vinculada a batch

- [x] 2.1 Confirmar S1 completo e ler
      `slice-prompts/SLICE-RPAP-S2.md` integralmente.
- [x] 2.2 Criar RED para `admissions_only` e full-sync batch-bound vazios nos
      workers atual e persistente.
- [x] 2.3 Implementar exceção/validação tipada e sanitizada antes da persistência.
- [x] 2.4 Provar falha/retry sem Patient/Admission, estágio bem-sucedido,
      contadores positivos ou follow-ups; preservar zero standalone.
- [x] 2.5 Rodar inspeções e gates oficiais do slice.
- [x] 2.6 Criar `/tmp/sirhosp-slice-RPAP-S2-report.md` e parar.

## 3. RPAP-S3 — Remover demografia duplicada do batch

- [x] 3.1 Confirmar S2 completo e ler
      `slice-prompts/SLICE-RPAP-S3.md` integralmente.
- [x] 3.2 Criar RED de paridade provando que batch-bound não gera segunda
      demografia e standalone continua gerando uma.
- [x] 3.3 Alterar ambos os workers com a menor regra de propriedade possível.
- [x] 3.4 Preservar full-sync, batch closure, contadores e worker atual.
- [x] 3.5 Rodar inspeções e gates oficiais do slice.
- [x] 3.6 Criar `/tmp/sirhosp-slice-RPAP-S3-report.md` e parar.

## 4. RPAP-S4 — Recuperação limitada do censo atual

- [x] 4.1 Confirmar S3 completo e ler
      `slice-prompts/SLICE-RPAP-S4.md` integralmente.
- [x] 4.2 Criar RED para dry-run, completude/proveniência, limite, deduplicação,
      apply atômico e saída sanitizada.
- [x] 4.3 Implementar serviço pequeno e command fino de recovery, sem modelo ou
      migration.
- [x] 4.4 Preservar proveniência pública reutilizável, atomicidade, saída
      sanitizada e proibição de reabrir runs históricos.
- [x] 4.5 Rodar inspeções e gates oficiais do slice.
- [x] 4.6 Criar `/tmp/sirhosp-slice-RPAP-S4-report.md` e parar.

## 5. RPAP-S5 — Health check agregado e alertável

- [x] 5.1 Confirmar S4 completo e ler
      `slice-prompts/SLICE-RPAP-S5.md` integralmente.
- [x] 5.2 Criar RED para cada invariante, limiar, amostra mínima, exit code e
      privacidade da saída.
- [x] 5.3 Implementar serviço de consulta agregada e management command
      fail-closed, sem provedor externo.
- [x] 5.4 Incluir falhas full-sync por motivo, eventos agregados, fila e frescor
      opcional; documentar canário, recovery em lotes, alertas e rollback.
- [x] 5.5 Rodar inspeções e gates oficiais do slice.
- [x] 5.6 Criar `/tmp/sirhosp-slice-RPAP-S5-report.md` e parar.

## 6. RPAP-S6 — Padronizar falha do processador de censo

- [x] 6.1 Confirmar S5 completo e ler
      `slice-prompts/SLICE-RPAP-S6.md` integralmente.
- [x] 6.2 Criar RED provando `CommandError`, ausência de efeitos e outcome
      `processing_failed` no orquestrador.
- [x] 6.3 Remover `sys.exit(1)` do comando sem capturar `BaseException` ou alterar
      o serviço de domínio.
- [x] 6.4 Preservar sucesso, movimentações e contratos do orquestrador.
- [x] 6.5 Rodar inspeções e gates oficiais do slice.
- [x] 6.6 Criar `/tmp/sirhosp-slice-RPAP-S6-report.md` e parar.

## 7. Verificação final do change

- [x] 7.1 Confirmar seis relatórios COMPLETE e handoffs aprovados por terceiro
      LLM.
- [x] 7.2 Executar `./scripts/test-in-container.sh quality-gate`.
- [x] 7.3 Executar `./scripts/test-in-container.sh integration`.
- [x] 7.4 Executar `openspec validate repair-persistent-admissions-pipeline
--strict`.
- [x] 7.5 Executar `./scripts/markdown-lint.sh` sem inibições.
- [x] 7.6 Revisar diff para ausência de PHI, credenciais, `.env`, HTML/PDF real,
      migrations e dependências não autorizadas.
- [x] 7.7 Não executar rollout/recovery de produção nem arquivar sem autorização
      explícita do operador.
