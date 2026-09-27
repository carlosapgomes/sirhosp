## Context

A ADR-0010 já colocou a recuperação D-1 dentro do loop adaptativo, porque apenas
ele conhece a janela real em que fila e batch estão livres. O change aberto
`orchestrate-intraday-discharge-recovery` aplica a mesma propriedade ao hourly.
A finalização estatística, porém, ainda pertence a um timer fixo às 07:30 e seu
preflight procura sucessos D-1/hourly nos journals dos services legados. O
`census_orchestrator` usa o logging `json-file` do Docker, e o Compose atual não
entrega `STATISTICS_ACTIVATION_DATE` ao container persistente.

O relatório já possui seleção censitária fail-closed, materialização atômica,
revisões idempotentes, `quality_warnings_json` e impressão digital das fontes.
Esses mecanismos devem ser reutilizados sem migration. Veja `proposal.md` e os
quatro deltas em `specs/` para o contrato observável.

## Goals / Non-Goals

**Goals:**

- Encadear D-1 e materialização sem adivinhar horários por timer.
- Distinguir “comando pendente” de “tentativas repetidas”: o loop observa o
  estado existente e chama a materialização uma vez quando a drenagem é segura.
- Publicar uma revisão degradada, mas identificada, quando o D-1 falhar e os
  limites censitários obrigatórios existirem.
- Fazer o preflight reconhecer evidências D-1 e hourly naturais do container
  sem imprimir log bruto ou executar mutação.
- Preservar deploy dormente, checkpoint humano, rollback isolado e operação
  simples com Django, PostgreSQL e Docker Compose.

**Non-Goals:**

- Alterar a janela D-1 `[01:00, 05:00)`, os limites censitários 00:00–03:00 e
  20:00–24:00 ou a regra funcional da recuperação intradiária de altas.
- Criar relatório intradiário do dia corrente, aceitar fechamento ausente ou
  reconstruir datas anteriores à ativação.
- Criar fila, worker, tabela de agendamento, Celery ou Redis.
- Remover os services one-shot usados para fallback manual.

## Decisions

### D1. Finalização é um passo pendente do loop, não um novo scheduler

Depois de uma tentativa D-1, o loop calcula
`target_date = local_date - 1 day`. Somente se a fronteira estiver configurada e
a data não a preceder, captura o resultado agregado e mantém a data pendente em
memória. Antes de
abrir o próximo ciclo, o loop chama a materialização somente quando uma nova
leitura confirma zero runs `queued`/`running` e nenhum batch aberto.

A verificação de drenagem é separada do cooldown censitário: cooldown pode
impedir um novo censo, mas não deve impedir a publicação quando todas as fontes
pendentes já foram processadas. Circuit breaker de stale recovery, run ativo e
batch aberto continuam bloqueando a publicação.

A flag da tentativa estatística é avançada antes da chamada. Uma falha consome a
tentativa lógica daquela data no processo atual; restart pode repetir, o que é
seguro pela idempotência e pelos row locks existentes.

A pendência em memória não sobrevive a restart. Para fechar o gap após a janela
D-1, cada processo, a partir das 05:00 Bahia, verifica se D-1 é elegível pela
fronteira, se ainda não tentou essa data no processo atual e se já possui
revisão `ready`. A revisão existente é o marcador durável
de conclusão. Se ela não existir, o processo cria uma única pendência de
recuperação e a executa na primeira drenagem segura com o aviso
`d1_recovery_not_confirmed`. Isso não reabre o D-1 fora da janela, não varre
histórico e não exige tabela nova. Não haverá timer de retry nem persistência
adicional para a FSM.

Alternativas rejeitadas:

- vários disparos entre 00:30 e 07:30, porque voltariam a adivinhar a drenagem;
- nova tabela de jobs, porque a revisão e a idempotência já oferecem recuperação
  suficiente para a fase 1;
- executar às 00:30 antes do D-1, porque publicaria sistematicamente antes da
  principal reconciliação diária.

### D2. A data D-1 é explícita e o modo automático permanece fallback

O orquestrador chama `materialize_daily_statistics --date <D-1>` em vez de
`--finalize`. Isso vincula a tentativa ao D-1 que acabou de ser processado e
impede que um aviso de falha seja aplicado a outras datas do lookback. O modo
`--finalize` e os units existentes permanecem disponíveis para recuperação
manual controlada, sempre limitados pela fronteira e pelo lookback. Uma revisão
com aviso degradado só pode ser reconstruída sem o aviso depois de sucesso D-1
comprovado; caso contrário, a execução manual deve preservar o mesmo código de
qualidade.

Ausência de ativação, data anterior à fronteira ou janela censitária incompleta
continuam produzindo falha segura e agregada; o loop não cria revisão e segue
para suas responsabilidades normais.

### D3. Degradação D-1 usa avisos allowlisted que participam da revisão

O comando de data explícita recebe um argumento interno repetível de qualidade,
restrito a uma allowlist. Este change introduz `d1_recovery_incomplete` para
falha observada no processo e `d1_recovery_not_confirmed` para recuperação
pós-05:00 quando um processo reiniciado não pode comprovar o resultado anterior.
O segundo código é incerteza, não afirmação de falha. O materializador une os
avisos aos códigos derivados, ordena/deduplica o conjunto e os inclui em
`quality_warnings_json` e na impressão digital já existente.

Sucesso D-1 no mesmo processo chama o comando sem aviso. Uma reexecução
posterior comprovadamente bem-sucedida pode produzir nova revisão sem o código;
a anterior permanece auditável. Texto livre não é aceito para impedir
log/persistência arbitrária e PHI.

Alternativa rejeitada: registrar a degradação somente no log, pois página e
XLSX deixariam de explicar por que uma revisão antecipada pode ter menos
eventos.

### D4. Ordem do loop e isolamento de falhas

Na primeira iteração elegível da janela D-1, a ordem será:

1. tentativa D-1 e marcador agregado de sucesso ou falha;
2. captura da data estatística pendente;
3. reavaliação de fila e batch;
4. materialização, imediatamente ou na primeira iteração drenada posterior;
5. recuperação intradiária e seu marcador agregado;
6. próximo ciclo censitário.

A partir das 05:00, antes de hourly/censo, um processo sem pendência e sem
tentativa registrada para a data verifica somente D-1: se a data respeita a
ativação e não possui revisão `ready`, cria a pendência não confirmada. Uma revisão pronta evita nova chamada. Exceções e
`SystemExit` do D-1 ou da materialização são reduzidos à classe técnica. Falha
estatística nunca aborta o loop nem transforma uma data incompleta em relatório.
A implementação não registra stdout nominal, payload clínico ou argumentos
livres.

### D5. O Compose entrega a ativação somente como configuração explícita

O serviço `census_orchestrator` recebe:

- `STATISTICS_ACTIVATION_DATE`, com default vazio fail-closed;
- `STATISTICS_FINALIZATION_LOOKBACK_DAYS`, com default limitado existente.

O caminho adaptativo usa `--date D-1`; portanto, o lookback limita somente o
fallback `--finalize` e não amplia nem reduz a data explícita do loop.

A declaração fica no override de ambiente do serviço, reutilizando o anchor
comum; nenhuma credencial nova é criada. O preflight compara o
`compose.hospital.yml` instalado byte a byte com o asset da release. Configurar
o `.env` não muda um container existente: a ativação documentada usa
`docker compose up -d --no-deps --force-recreate census_orchestrator` somente
após aceite humano.

### D6. O preflight usa Docker somente por uma interface read-only fechada

O preflight adiciona `docker` às dependências e permite apenas:

- `docker compose ... ps` para confirmar o serviço conhecido;
- `docker compose ... logs --since 2h --no-color census_orchestrator` para
  hourly;
- `docker compose ... logs --since 30h --no-color census_orchestrator` para
  D-1.

A saída é redirecionada para arquivo temporário removido por `trap`; somente
predicados allowlisted chegam a stdout. `exec`, `run`, `up`, `restart`,
`inspect`, comandos Django e acesso ao banco continuam proibidos e testados.

Os marcadores canônicos novos serão equivalentes a
`mode=d1-recovery result=success source=adaptive-orchestrator` e
`mode=hourly-discharges result=success source=adaptive-orchestrator`, emitidos
somente quando cada `call_command` retornar com sucesso. Para a transição da
RC31, o parser também aceita exclusivamente sequências ordenadas no mesmo bloco
de logs do `census_orchestrator`: início natural, dispatch do modo esperado,
resumo bem-sucedido e fim; D-1 ainda exige os quatro extratores e resumo 4/4.
Um `finished` isolado, qualquer bloco com falha, o service systemd manual ou
linhas combinadas de execuções diferentes não satisfazem o check.

Essa evidência prova saúde upstream recente; a procedência da nova
implementação continua sendo provada separadamente pela tag, imagem configurada,
Compose e assets imutáveis. Isso permite coletar a evidência natural do
orquestrador ainda em execução antes de recriá-lo com a nova release.

### D7. Bootstrap corrente é limitado pelo início da janela de fechamento

O caminho padrão continua aceitando data futura. Para o primeiro dia, o
preflight aceita `STATISTICS_ACTIVATION_DATE == hoje` somente antes das 20:00
`America/Bahia`, com os timers hourly, D-1 e estatístico
desabilitados/inativos. Às 20:00 ou depois, a mesma data falha fechado. Data
passada nunca é aceita.

O preflight não consulta nem altera o banco. O comando e a constraint existentes
continuam garantindo `report.local_date >= activation_date`; logo o bootstrap
corrente não abre backfill anterior.

### D8. Units fixos ficam como fallback inerte e changes têm ordem explícita

`sirhosp-discharges.service`, `sirhosp-historical-recovery.service` e
`sirhosp-daily-statistics.service` permanecem assets para operação manual. Seus
timers ficam desabilitados/inativos no caminho normal. Tanto hourly quanto D-1
são comprovados por execução natural do orquestrador, evitando scheduler
duplicado.

Os changes `orchestrate-d1-exit-recovery` e
`orchestrate-intraday-discharge-recovery` devem ter seus deltas sincronizados e
ser arquivados antes deste change. A implementação pode prosseguir quando não
houver escritor concorrente, mas o gate final não permite arquivar OASF sobre
specs canônicos ainda legados. A decisão arquitetural será registrada em nova
ADR, sem reescrever o histórico da ADR-0010.

## Risks / Trade-offs

- **[Processo reinicia após D-1 e antes da materialização]** → dentro da janela,
  D-1 e materialização podem repetir com segurança; após 05:00, ausência de
  revisão `ready` recria uma pendência única e pessimista com
  `d1_recovery_not_confirmed`.
- **[D-1 cria trabalho assíncrono]** → reavaliar drenagem e manter a data
  pendente; não abrir censo enquanto houver trabalho ativo.
- **[D-1 falha e relatório parece completo]** → persistir aviso allowlisted na
  revisão, página e XLSX; nunca depender apenas do log.
- **[Fechamento não existe]** → o comando explícito falha e o loop segue sem
  relatório; fallback manual exige investigação, não retry cego.
- **[Parser de log produz falso positivo]** → parser estrutural da sequência
  legada e marcador canônico único; fixtures adversariais com comentários,
  ordem incorreta, 3/4 e falha.
- **[Consulta Docker vaza log clínico]** → arquivo temporário, saída allowlisted,
  sem eco de linhas e testes com conteúdo sintético sensível.
- **[Ativação corrente vira backfill disfarçado]** → somente hoje antes das
  20:00, nenhuma data passada e gate censitário intacto.
- **[Mistura temporária de releases durante preflight]** → limitada ao
  orquestrador dormente em relação às estatísticas; procedência da release alvo
  é validada antes da recriação isolada.
- **[Maior responsabilidade do orquestrador]** → passo curto de banco após
  automação já coordenada, sem novo daemon ou infraestrutura.
- **[Changes concorrentes deixam timers em estados incompatíveis]** → exigir o
  estado terminal adaptativo para hourly e D-1 e sincronizar/arquivar ODER e
  OIDR antes de OASF.

## Migration Plan

1. Registrar ADR, implementar os slices em TDD e executar o quality gate
   completo em container.
2. Publicar uma nova RC imutável com imagem, Compose, preflight, units e runbook
   correspondentes.
3. Implantar imagem/assets mantendo os timers hourly, D-1 e estatístico
   desabilitados e sem recriar inicialmente o `census_orchestrator`, preservando
   suas evidências naturais recentes.
4. Configurar uma fronteira futura ou o bootstrap corrente antes das 20:00;
   executar o preflight read-only e preservar apenas a saída agregada.
5. Após aceite humano explícito e com evidência fresca, recriar somente o
   `census_orchestrator`; confirmar saúde, configuração agregada e ausência de
   relatórios anteriores à fronteira.
6. Observar os markers naturais D-1/hourly e o primeiro pipeline D-1 →
   drenagem → materialização; validar data, revisão, avisos e contagens sem
   imprimir identidade clínica. Após 05:00, ausência inesperada da revisão deve
   acionar a recuperação adaptativa não confirmada. Às 07:30, ausência de
   revisão `ready` gera alerta e decisão humana de fallback, nunca retry por
   calendário.
7. Sincronizar e arquivar `orchestrate-d1-exit-recovery` e
   `orchestrate-intraday-discharge-recovery` antes de arquivar este change.
8. Em rollback, remover a fronteira do `.env` ou restaurar a release anterior e
   recriar somente o orquestrador. Não apagar revisões nem habilitar timers de
   fallback. Restaurar banco apenas por decisão separada se houver
   incompatibilidade não esperada.
