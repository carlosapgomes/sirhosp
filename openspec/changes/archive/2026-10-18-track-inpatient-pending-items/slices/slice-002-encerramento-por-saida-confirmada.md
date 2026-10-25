# PEND-S2 — Encerramento por saída confirmada

## Identity

- Change: `track-inpatient-pending-items`.
- Task: `tasks.md`, 2.1.
- Dependência: PEND-S1 aceito.
- Estado: contrato proposto, executar somente após aprovação.

## Objective

Encerrar automaticamente pendências ativas quando os fluxos canônicos confirmarem a saída do episódio, preservando auditoria, finalizações humanas e atomicidade.

## Read first

Paths relativos à raiz do repositório:

- `AGENTS.md` e `PROJECT_CONTEXT.md`.
- `openspec/changes/track-inpatient-pending-items/proposal.md`.
- `openspec/changes/track-inpatient-pending-items/design.md` — D3–D6 e D9.
- `openspec/changes/track-inpatient-pending-items/specs/inpatient-pending-items/spec.md` — PI-03 a PI-08.
- `openspec/specs/admission-exit-reconciliation/spec.md` e `openspec/specs/admission-duplicate-resolution/spec.md`.
- `apps/pending_items/` entregue por S1.
- `apps/patients/reconciliation.py`, `apps/patients/admission_merge.py`, `apps/ingestion/services.py`.
- `tests/unit/test_admission_exit_reconciliation.py`, `tests/unit/test_admission_merge.py`.
- `tests/integration/test_discharge_reconciliation.py`, `tests/integration/test_death_exit_reconciliation.py`, `tests/integration/test_admission_merge.py`.

## Requirements

| ID | Contrato observável | Evidência planejada |
| --- | --- | --- |
| R1 | PI-07: estado fechado resultante nos três writers válidos encerra todas e somente as Ativas do episódio com Sistema/motivo, mesmo sem nova data de saída recebida. | Reconciliação, snapshot e merge reais; incluir already_reconciled com ativas residuais e merge com canônica já fechada ou fim da duplicata mesmo quando a confirmação não contém fim. |
| R2 | PI-05/06/07: preservar finais e idempotência; snapshot atômico por item com falha propagada, sem desfazer itens anteriores nem processar seguintes. | Falha de revisão no segundo de três itens: verificar saída, pendências, revisões, aliases e consolidação revertidos só no segundo; no primeiro tudo persiste, terceiro não processado; reconciliação/merge mantêm sua auditoria atômica. |
| R3 | PI-03/07: ausência no censo, alta médica sem saída, ambiguidade e episódio diferente não finalizam. | Testes negativos dos fluxos existentes com expectativas sobre status e contagem de revisões. |
| R4 | PI-06/07: edição/cadastro e saída serializam, revalidando identidade canônica sob lock e sem usar objeto obsoleto. | PostgreSQL com conexões/barreiras controladas: cruzar edição e cadastro com reconciliação, snapshot compartilhado e merge; incluir identidade unificada entre resolução inicial e lock. |
| R5 | PI-08: transferências/rollbacks preservam versões, não reabrem estados finais e exibem histórico pelo episódio correto. | Merge com pendências nas duas candidatas, fechamento pelos três caminhos de combinação do período, rollback permitido e consulta HTTP após saída/rollback. |

## Expected blast radius

- Serviço de finalização e testes em `apps/pending_items/`.
- Hooks focados nos três writers identificados em D5, incluindo lock/transação do snapshot.
- Testes de saída/óbito, integração do snapshot, merge/rollback e consulta contextual.
- Preservar critérios de evidência, taxonomia de saída, aliases, retornos públicos dos serviços e processamento dos dois workers pela fronteira compartilhada.
- Fora de escopo: scraping, helpers PDF inativos, novos jobs/timers, sinais genéricos, reparo de toda a ingestão e alterações dos contratos de matching.

## Failing-before plan

Partindo do estado entregue por S1, criar pendência sintética ativa e processar uma saída por cada ponto de entrada de D5. Registrar RED: internação fechada com pendência ativa. Incluir desde o início merge sem fim na confirmação mas com fim resultante da canônica/duplicata, already_reconciled com ativas residuais e falha de revisão no segundo de três itens do snapshot. Acrescentar negativos, rollback e concorrência antes dos hooks; não substituir entradas reais por mocks que só confirmem chamada ao helper.

## Implementation constraints

Seguir `AGENTS.md`, D4–D6 e a menor alteração correta. Serviço de Sistema não é acessível por flags de formulário e não depende de um usuário humano artificial. Horário de processamento não é retrodatado para o horário efetivo da saída.

Nos três writers válidos, invocar após estabelecer o estado canônico resultante: se discharge_date não é nulo, encerrar ativas residuais, sem exigir transição nova nem fim no payload recebido. Isso inclui already_reconciled e merge com fechamento preexistente ou herdado da duplicata.

O snapshot precisa receber uma transação por item/internação, incluindo campos, finalização/revisões, aliases e consolidação daquele item. Para episódio existente, resolver identidade, bloquear Admission e revalidar identidade/paciente/período antes de gravar; não usar objeto que foi unificado nesse intervalo. Falha desfaz o item inteiro e propaga, preservando itens anteriores confirmados e sem processar os seguintes. Não envolver a lista inteira em atomic, inventar auditoria de reconciliação para snapshot ou alterar retry.

Manter ordem de locks Admission → PendingItem; reconciliação/merge preservam sua atomicidade e auditoria próprias. A corrida conservadora da guarda legada em D6 também aborta o item do snapshot. Rollback estrutural não apaga versões nem reabre pendências. Nenhuma escrita/repair em GET.

## Validation

### Focused validation

- Novo `tests/integration/test_pending_items_exit_lifecycle.py`, com testes unitários do helper idempotente onde houver seam determinístico.
- Reexecutar testes de reconciliação de alta/óbito, snapshot/identidade e merge/rollback afetados.
- Capturar falha de revisão no segundo de três itens do snapshot e verificar rollback dos campos, pendências, revisões, aliases e consolidação daquele item, primeiro preservado e terceiro não processado; sem supor auditoria de reconciliação nesse writer.
- Provar no PostgreSQL concorrência dos três writers, incluindo explicitamente snapshot × edição e snapshot × cadastro, com conexões separadas/sincronização controlada e revalidação de identidade sob lock. SQLite ou só mocks não comprovam os locks.

### Project-required gates

Executar check, unit, integration, lint e typecheck pelo caminho oficial de `AGENTS.md`, além de markdown lint quando aplicável. Integração é obrigatória.

### Runtime / verification evidence

Cenário integrado: cadastro autorizado → confirmação real pela fronteira de persistência → pendência finalizada com Sistema → consulta HTTP do histórico em internação fechada → POST rejeitado → repetição sem nova revisão. É evidência da fronteira operacional sem acessar fonte hospitalar real. Não há interação JS nova que exija outro runner ou uma sessão no portal dev.

## Acceptance criteria

- [ ] R1: os três writers encerram somente Ativas do episódio fechado resultante, incluindo already_reconciled residual e merge fechado sem fim na confirmação.
- [ ] R2: repetição/correção não duplicam versões; snapshot reverte integralmente só o item com falha, propaga erro, preserva anteriores e não processa seguintes; demais writers mantêm auditoria atômica.
- [ ] R3: cenários negativos não encerram nem registram versões artificiais.
- [ ] R4: concorrência PostgreSQL dos três writers, inclusive snapshot × edição/cadastro e identidade alterada antes do lock, passa sem escrita pós-saída ou objeto obsoleto.
- [ ] R5: merge pelos três caminhos de fim resultante, rollback e consulta histórica preservam autoria, versões e terminalidade.
- [ ] Validações obrigatórias e cenário operacional passam; relatório existe.

## Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` se surgir contradição, nova decisão de produto/arquitetura, expansão material, mudança de compatibilidade, migração/FSM não prevista ou risco clínico, de privacidade, segurança ou integridade. Se um writer operacional adicional exigir mudança de semântica de evidência, ou a atomicidade não puder ser demonstrada, registrar evidência e parar.

## Evidence report

Produzir `/tmp/sirhosp-slice-PEND-S2-report.md` conforme `AGENTS.md`, com R1–R5 → evidência, arquivos/motivos, RED/GREEN, comandos/exit status, cenário integrado, desvios, levers e pendências reais. Não registrar payloads clínicos reais nem copiar o diff.

## Worker handoff

Implementar somente este slice aprovado, pelas referências canônicas. Produzir RED, menor correção, validações e relatório; não atualizar tasks, commitar, publicar, arquivar ou iniciar outro slice. Encerrar em `READY_FOR_REVIEW` com `REPORT_PATH=/tmp/sirhosp-slice-PEND-S2-report.md`, ou `BLOCKED_NEEDS_DECISION` com evidência.
