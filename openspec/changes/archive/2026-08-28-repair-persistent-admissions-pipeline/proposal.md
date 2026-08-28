# Change: Reparar o pipeline persistente de internações

## Why

A validação agregada em produção confirmou que o censo, seu processamento e as
movimentações continuam operacionais, mas a captura de internações pelo worker
persistente passou a concluir com `admissions_seen=0`. O defeito ocorre porque o
bridge lê corretamente a tabela dentro de `frame_pol`, descarta esse snapshot
quando o handle real não oferece o método fake-only `set_html()` e depois tenta
reconstruí-lo a partir de `page.content()` da página principal, que não contém o
DOM interno do iframe.

A lista vazia é JSON válido e termina como sucesso. Como o `full_sync` só é
criado quando existe uma internação persistida, pacientes novos deixam de
receber evoluções. O fluxo também duplica demografia: o censo já cria
`demographics_only`, mas cada `admissions_only` cria outro run destacado do
batch. A operação não possui um comando fail-closed que detecte essas
invariantes nem uma recuperação atual, limitada e idempotente.

A correção restaura a atualização clínica necessária para gestão de
prontuários, qualidade, jurídico e diretoria sem alterar a arquitetura do
monólito ou acessar dados reais em testes e artefatos.

## What Changes

- Fazer `RealHandleBridge` conservar, em memória e por job, o snapshot
  normalizado capturado no iframe e entregá-lo ao adapter sem alterar o DOM
  Playwright real.
- Limpar o snapshot transitório em toda nova navegação, cleanup, restart,
  bootstrap, falha e shutdown, impedindo reutilização entre pacientes.
- Tornar um snapshot vazio inválido para capturas vinculadas a batch de censo ou
  recuperação, em ambos os workers, preservando o resultado vazio legítimo de
  sincronizações manuais standalone.
- Garantir que captura vazia batch-bound falhe pela taxonomia sanitizada, não
  persista internação, não gere contadores positivos e não crie follow-ups.
- Tornar o censo o único dono da demografia em runs batch-bound; manter o
  follow-up demográfico somente para `admissions_only` standalone.
- Adicionar recuperação explícita, dry-run por padrão, limitada e idempotente a
  partir do último censo completo, sem reabrir em massa runs históricos.
- Adicionar health check operacional sanitizado e alertável por exit code para
  falso sucesso vazio, cobertura de `full_sync`, duplicação demográfica,
  envelhecimento da fila e falhas de evolução agregadas por motivo.
- Substituir `sys.exit(1)` no comando `process_census_snapshot` por
  `CommandError`, permitindo ao orquestrador classificar a falha de processamento
  de forma controlada.
- Documentar rollout canário, recuperação progressiva, critérios de parada e
  rollback usando somente métricas agregadas.

## Capabilities

### New Capabilities

- `current-census-admissions-recovery`: planejamento e enfileiramento seguro de
  recuperação de internações para pacientes do último censo completo.
- `ingestion-pipeline-health`: diagnóstico agregado, sanitizado e fail-closed do
  pipeline censo → internações → demografia → full-sync → evoluções.

### Modified Capabilities

- `persistent-session-ingestion-worker`: preserva o snapshot real capturado no
  iframe e falha em vez de concluir um batch clínico com captura vazia.
- `patient-admission-mirror`: diferencia ausência válida standalone de captura
  vazia inválida em batch de paciente internado.
- `patient-demographics-ingestion`: elimina o segundo produtor demográfico para
  runs originados do censo.
- `census-snapshot-processing`: usa erro convencional de management command ao
  rejeitar processamento.
- `adaptive-census-orchestration`: recebe e classifica falha do processador sem
  permitir que `SystemExit` escape do ciclo.

## Scope

### Included

- Código e testes sintéticos do bridge, dos dois workers e dos serviços de
  recuperação/saúde.
- Um management command de recuperação e um management command de saúde.
- Runbook de canário, recuperação, observação e rollback.
- Delta specs e prompts de seis slices verticais para DeepSeek4-Flash.
- Métricas e saídas estritamente agregadas, sem identificadores clínicos.

### Excluded

- Reprocessar ou alterar o status dos runs históricos falsamente bem-sucedidos.
- Executar deploy, escalar containers ou modificar produção durante os slices de
  código sem autorização operacional explícita posterior.
- Corrigir por suposição cada `timeout` ou `invalid_payload` de evolução; este
  change os torna observáveis. Uma causa nova comprovada exige change próprio.
- Adicionar e-mail, webhook, Prometheus ou outro provedor de alertas.
- Adicionar modelo, migration, Celery, Redis, microserviço ou nova fila.
- Adicionar `set_html()` ao `PlaywrightSessionHandle` real.
- Persistir HTML, PDF, screenshot, prontuário, nome ou texto clínico em logs,
  métricas, documentação ou relatórios.

## Success Criteria

1. Um handle realista sem `set_html()` entrega ao adapter o snapshot lido do
   iframe, mesmo quando `page.content()` contém apenas a página principal.
2. Nenhum snapshot transitório pode ser reutilizado após cleanup, falha,
   restart, bootstrap, shutdown ou nova navegação.
3. Captura vazia batch-bound falha nos dois workers e não persiste nem enfileira
   efeitos clínicos; captura vazia standalone preserva o contrato existente.
4. Cada paciente do censo recebe no máximo um `demographics_only` por batch, e
   admissions standalone continuam podendo solicitar demografia.
5. Recuperação usa apenas o último censo completo, faz dry-run sem mutação,
   respeita limite, deduplica candidatos e nunca reabre os runs históricos.
6. O health check retorna estado não saudável para as invariantes configuradas,
   expõe falhas de evolução por categoria e não imprime dados sensíveis.
7. Rejeição de `process_census_snapshot` levanta `CommandError` e o orquestrador
   retorna `processing_failed` sem encerrar abruptamente o loop.
8. Rollout canário e recuperação progressiva têm comandos, critérios de avanço,
   parada e rollback documentados.
9. Todos os testes e gates oficiais em container, OpenSpec strict e markdown
   lint passam.

## Risks

- Cache transitório sobreviver ao job e contaminar outro paciente. Mitigação:
  limpeza fail-closed em todas as fronteiras e teste de sequência.
- Considerar vazia uma ausência legítima. Mitigação: regra restrita a runs com
  batch; standalone mantém o resultado explícito de zero internações.
- Recuperação gerar tempestade de fila. Mitigação: dry-run padrão, `--limit`,
  deduplicação, batch próprio e canário pequeno antes de ampliar.
- Health check gerar falso positivo por janela curta. Mitigação: limiares
  explícitos, contagem mínima e saída diagnóstica agregada.
- Falhas de evolução permanecerem após restaurar internações. Mitigação:
  agregação por motivo e stop rule para abrir correção baseada em evidência.
