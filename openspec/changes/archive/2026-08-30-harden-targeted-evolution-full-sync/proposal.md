## Why

A produção pode selecionar uma internação no portal, mas a extração persistente
ignora essa identidade local, percorre internações legadas sobrepostas e pode
expirar no clique de `Evolução`; além disso, uma falha tardia descarta o trabalho
já extraído e a cobertura é inferida pela mera existência de evento no dia. A
correção é necessária agora para evitar lacunas silenciosas no prontuário,
reprocessamento agressivo do legado e diagnóstico operacional insuficiente.

## What Changes

- Restringir `full_sync` e `full_admission_sync` com `admission_id` à internação
  local alvo, resolvida no legado por período e estado; a chave legada volátil é
  somente uma dica. Sem `admission_id`, preservar a seleção de todas as
  internações sobrepostas.
- Tornar a ativação de `Evolução` resiliente ao comportamento real do JSP,
  mantendo ação Playwright normal como primeira opção e usando fallback DOM
  controlado, com pós-condição explícita e timeout limitado.
- Extrair e persistir evoluções por chunks determinísticos, confirmando cada
  chunk antes de avançar, para que uma falha posterior não descarte resultados
  já processados.
- Introduzir cobertura explícita e idempotente por internação e intervalo,
  inclusive para chunks válidos sem eventos, e fazer retries planejarem apenas
  lacunas não cobertas.
- Reaproveitar `next_retry_at` para adiar automaticamente, por no máximo 60
  minutos desde a falha terminal anterior da mesma internação, um novo
  `full_sync` enfileirado pelo censo. O retry interno atual de 60 segundos e o
  `full_admission_sync` manual permanecem inalterados.
- Registrar subetapas sanitizadas da navegação e progresso agregado dos chunks,
  sem identificadores de paciente, conteúdo clínico, URLs, seletores,
  credenciais ou erros brutos.

Não objetivos: importação manual de PDF, nova fila/worker, Celery/Redis,
alteração da taxonomia de falhas, espera exponencial acima de uma hora,
mudança do worker clássico fora do compartilhamento necessário e uso de dados
reais em testes.

## Capabilities

### New Capabilities

- `evolution-extraction-coverage`: cobertura explícita, persistência incremental
  e retomada idempotente de chunks de evolução por internação.

### Modified Capabilities

- `persistent-session-ingestion-worker`: seleção da internação alvo, ativação
  resiliente da ação de evolução e enfileiramento automático diferido.
- `fullsync-failure-exhaustion-fix`: preserva retries internos atuais e limita
  repetição automática entre runs da mesma internação a uma janela fixa máxima
  de 60 minutos.
- `ingestion-run-observability`: detalha subetapas sanitizadas e progresso
  agregado por chunk sem ampliar superfícies sensíveis.

## Impact

- Código: bridge/navegação Playwright persistente, adapter, worker persistente,
  planejador de gaps, serviço de ingestão e auto-enfileiramento.
- Dados: novo modelo e migration PostgreSQL para cobertura de extração.
- Operação: runs automáticos podem nascer com `next_retry_at` futuro; a espera
  combina o cooldown de censo já existente (30 minutos) com um teto fixo de 60
  minutos após falha terminal, sem backoff exponencial.
- Riscos principais: associação incorreta entre internações sobrepostas,
  cobertura marcada antes do commit clínico, regressão no JSP e vazamento de
  contexto sensível. Testes sintéticos, transação por chunk, pós-condições e
  enums sanitizados mitigam esses riscos.
- Sem novas dependências, serviços ou APIs públicas.
