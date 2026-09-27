## Why

A finalização estatística diária ainda depende de um timer fixo às 07:30 e seu
preflight exige o timer D-1 legado das 05:00, embora a ADR-0010 e o runtime de
produção já atribuam a recuperação D-1 ao orquestrador adaptativo. Essa
inconsistência bloqueia a ativação legítima e atrasa um relatório necessário à
gestão hospitalar mesmo quando o próprio orquestrador já encontrou uma janela
segura com fila drenada e batch fechado.

## What Changes

- O orquestrador adaptativo passa a materializar a data D-1 uma vez por dia,
  depois da tentativa D-1 e na primeira iteração em que a fila esteja drenada e
  nenhum batch permaneça aberto, antes de iniciar o próximo ciclo censitário.
- A finalização usa a data-alvo D-1 capturada em `America/Bahia`, permanece
  idempotente após restart e nunca amplia a fronteira ou a janela de backfill.
  Após 05:00, se o processo perdeu a pendência em memória, a ausência de uma
  revisão `ready` funciona como marcador durável para uma única tentativa de
  recuperação na primeira drenagem segura.
- Se o D-1 falhar, a revisão ainda pode ser publicada com o aviso técnico
  enumerado `d1_recovery_incomplete`; se um processo reiniciado não puder
  comprovar o resultado anterior, usa `d1_recovery_not_confirmed`. Ausência de
  abertura ou fechamento censitário aceito continua impedindo a publicação.
- O Compose hospitalar passa explicitamente a configuração estatística para o
  `census_orchestrator`; os services one-shot de D-1, altas e estatísticas
  permanecem instaláveis apenas como fallback manual, com seus timers
  desabilitados e inativos no caminho primário.
- **BREAKING (operacional):** a ativação deixa de habilitar
  `sirhosp-daily-statistics.timer` e passa a recriar somente o serviço
  `census_orchestrator`, após preflight `PASS` e aceite humano, para carregar a
  fronteira declarada.
- O preflight reconhece somente marcadores agregados de execuções D-1 e hourly
  naturais e bem-sucedidas do orquestrador, consultados por operação Docker
  estritamente read-only; ele exige os timers legados D-1, hourly e estatístico
  desabilitados/inativos e não aceita disparos manuais como evidência.
- A fronteira continua explícita e sem backfill anterior, mas admite bootstrap
  na data local corrente somente antes das 20:00 `America/Bahia`, com o runtime
  ainda dormente; datas passadas ou bootstrap após o início da janela de
  fechamento continuam recusados.
- Runbook, ADR e evidências de release/rollback são alinhados ao novo
  proprietário adaptativo do agendamento.

## Capabilities

### New Capabilities

Nenhuma.

### Modified Capabilities

- `adaptive-census-orchestration`: adiciona a finalização estatística diária
  coordenada pelo estado real da fila, após o passo D-1, com recuperação
  pós-05:00 baseada na ausência durável da revisão.
- `daily-statistics-reporting`: define a publicação antecipada de D-1, avisos
  persistidos para recuperação falha ou não comprovada e a preservação dos
  gates censitários obrigatórios.
- `daily-statistics-production-activation`: substitui a ativação do timer pelo
  runtime adaptativo, corrige as evidências D-1/hourly e admite bootstrap
  controlado na data corrente.
- `release-image-hospital-deploy`: exige que o Compose imutável entregue a
  configuração estatística ao orquestrador e documente sua recriação isolada.

## Impact

- **Risco:** CRÍTICO — altera agendamento de produção, publicação de relatório
  clínico nominal, preflight e procedimento de ativação/rollback.
- **Código:** `apps/census/orchestration.py`, comando/materializador de
  estatísticas e testes unitários/de integração relacionados.
- **Deploy:** `compose.hospital.yml`, preflight, contratos estáticos dos units,
  workflow/assets imutáveis e runbook da próxima RC.
- **Persistência:** reutiliza `DailyStatisticsReport` e
  `quality_warnings_json`; não requer migration nem nova tabela.
- **Operação:** D-1, hourly e finalização pertencem ao pipeline adaptativo; os
  timers fixos de D-1, altas e estatísticas ficam desabilitados, enquanto seus
  services permanecem como fallback manual.
- **Não-objetivos:** alterar janelas de abertura/fechamento, criar prévia do dia
  corrente, aceitar relatório sem fechamento, introduzir Celery/Redis, executar
  backfill anterior à ativação ou usar dados clínicos em logs/evidências.
- **Dependências:** os changes `orchestrate-d1-exit-recovery` e
  `orchestrate-intraday-discharge-recovery` devem ser sincronizados e arquivados
  antes do arquivamento deste change; o estado terminal assume ambos os timers
  legados desabilitados.
- **Riscos principais:** restart após a janela D-1, fila reocupada pelo D-1,
  marcador de sucesso falso-positivo, bootstrap tardio e publicação degradada
  sem aviso. Os slices exigem TDD, revisão independente, gate completo, plano
  de rollback e observação da primeira execução natural.
