## Why

O espelho clínico pode manter internações abertas depois da saída efetiva do
paciente, criar um segundo registro fechado quando a chave externa muda e
continuar tratando a internação antiga como residual em uma readmissão. A
extração histórica já preserva evidências de saída, mas não as reconcilia com o
domínio, o que compromete a confiabilidade operacional para assistência,
gestão de prontuários, qualidade e auditoria.

## What Changes

- Introduzir reconciliação canônica e auditável de saídas, usando exclusivamente
  `saida_em` para encerrar internações e preservando `alta_em` como o momento de
  criação do sumário de alta.
- Tratar alta hospitalar e óbito como tipos distintos de saída, sem sintetizar
  horário para evidência que contém apenas data.
- Substituir a suposição de chave externa estável por identidade em camadas,
  histórico de aliases e quarentena de correspondências ambíguas.
- Impedir e sanear duplicatas aberto/fechado do mesmo episódio, preservando o
  registro canônico mais antigo e mantendo o duplicado como mesclado para
  auditoria.
- Detectar pacientes ausentes em dois censos completos consecutivos por pelo
  menos 30 minutos, usando a ausência apenas para enfileirar confirmação na
  fonte.
- Integrar a reconciliação às extrações de altas e óbitos, confirmar resultados
  vazios com cobertura durável e automatizar extração horária, recuperação de
  D-1 e catch-up limitado.
- Remover usuário/senha dos argumentos de subprocesso dos quatro extratores
  históricos antes de qualquer ativação programada.
- Marcar `process_discharge_pdf` como fluxo legado inativo e candidato a remoção;
  durante a transição, o comando deve falhar antes de ler PDF ou alterar dados.
- Oferecer monitoramento agregado, revisão clínica protegida por permissão
  específica e exportação CSV efêmera e autenticada sem dados pessoais em logs.
- Entregar comandos reversíveis, dry-run, lotes limitados e runbook para
  saneamento de todas as internações órfãs; a execução em produção permanece uma
  operação separada e explicitamente autorizada.
- Passar indicadores operacionais de saída para `saida_em`, mantendo indicadores
  separados para sumários de alta por `alta_em` e óbitos.

### Out of scope

- Executar o backfill no banco de produção como parte da implementação.
- Fechar internações apenas porque o paciente não aparece no censo.
- Criar pacientes ou internações sintéticas a partir de evidência de saída.
- Reativar ou usar o PDF legado como fonte clínica ou sinal operacional; a
  cobertura passa pelo XLS, catálogo de internações, óbitos e censos.
- Persistir CSVs de revisão, nomes ou prontuários em logs.
- Introduzir Celery, Redis, microserviços ou uma nova infraestrutura de filas.
- Reprocessar sumários clínicos no mesmo passo transacional do saneamento; essa
  operação terá execução posterior e separada.

## Capabilities

### New Capabilities

- `admission-exit-reconciliation`: evidência de saída, matching em camadas,
  auditoria, tipos de saída, aliases e tratamento fail-closed de ambiguidades.
- `admission-duplicate-resolution`: prevenção, confirmação na fonte e merge
  reversível de registros que representam o mesmo episódio.
- `stale-admission-detection`: detecção conservadora por censos completos,
  cooldown, fila PostgreSQL e revisão clínica autorizada.
- `admission-reconciliation-backfill`: planejamento e saneamento histórico em
  dry-run, lotes limitados, com backup, rollback e aprovação operacional.
- `production-exit-reconciliation-runtime`: runner Playwright one-shot no
  Compose hospitalar, agendamento por systemd, confirmação durável de zero,
  execução diária às 05:00 de `recover_historical_data` para `discharges`,
  `admissions`, `deaths` e `official_census`, catch-up e limites de carga sobre o
  legado.

### Modified Capabilities

- `patient-admission-mirror`: substituir a identidade exclusivamente baseada na
  chave externa por aliases, registros canônicos e estado de merge.
- `historical-extraction-services`: reconciliar altas extraídas, usar
  `saida_em`, confirmar resultado vazio e encaminhar óbitos sem horário.
- `historical-recovery-command`: expor resultados de reconciliação e preservar
  falha parcial quando a extração não for semanticamente confirmada.
- `daily-discharge-tracking`: separar sumários de alta de saídas hospitalares e
  reconstruir contagens operacionais por `saida_em` em `America/Bahia`.
- `census-snapshot-processing`: produzir observações de ausência somente após
  snapshots completos, sem fechar internações pelo censo.
- `adaptive-census-orchestration`: disparar a detecção pós-censo sem violar
  drenagem, locks ou backoff existentes.
- `ingestion-pipeline-health`: incluir cobertura de extrações, backlog de
  reconciliação, ambiguidades e duplicatas em diagnósticos agregados.

## Impact

- **Domínio e banco:** `Admission`, aliases de chave, estado de merge, evidências
  de saída, auditoria imutável, permissões e migrações aditivas.
- **Ingestão:** serviços de altas, óbitos, snapshots de internação, worker
  PostgreSQL e recuperação histórica.
- **Censo:** comparação entre execuções completas e gatilho conservador de
  confirmação, sem alterar a autoridade clínica da fonte.
- **Portal:** cards e séries separadas, fila de revisão protegida e CSV efêmero.
- **Operação:** runner profile-gated em `compose.hospital.yml`, novos comandos
  bounded-by-default, serviços/timers systemd entregues como assets da release e
  runbook de benchmark, backup, apply, validação e rollback. O runtime atual não
  possui timer de altas nem de recuperação histórica instalado; a ativação em
  `/srv/apps/prisma` será um checkpoint explícito.
- **Risco:** mudança crítica por alterar identidade e encerramento de
  internações; exige ADR, TDD, rollout em lotes e validação independente antes
  de qualquer saneamento de produção.
