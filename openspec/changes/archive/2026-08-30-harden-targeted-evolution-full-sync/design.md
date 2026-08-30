## Context

O fluxo persistente recebe `admission_id` em `IngestionRun.parameters_json`, mas
`PersistentExtractionAdapter.extract_evolutions()` envia somente paciente e
intervalo ao `RealHandleBridge`. O bridge lê a tabela legada e
`choose_overlapping_admissions()` escolhe todas as linhas sobrepostas. A
identidade `source_admission_key` não é estável entre capturas e, portanto, não
pode ser usada como chave primária de associação.

No caso caracterizado em produção, o clique Playwright actionability em
`Evolução` expirou após cerca de 30 segundos. No mesmo estado de página, a
seleção da internação ativa por período/estado e um clique DOM controlado
permitiram extrair 21 evoluções. O orçamento da janela era 132 segundos; a
falha era da ação, não do volume global.

O worker atualmente chama o adapter para todas as janelas, acumula eventos em
`all_evolutions` e só persiste após todas terminarem. `gap_planner.py` considera
um dia coberto quando existe qualquer `ClinicalEvent`, o que não prova que uma
extração daquele período terminou, sobretudo após persistência parcial.

Já existem três proteções operacionais que devem ser reaproveitadas:

- retries da mesma `IngestionRun` usam `next_retry_at` com cerca de 60 segundos;
- o orquestrador de censo usa cooldown e failure backoff de 30 minutos;
- stale recovery tem circuit breaker contra mutação em massa.

Nenhuma delas limita explicitamente uma nova `full_sync` automática da mesma
internação após falha terminal. O novo guard deve preencher somente essa
lacuna, sem duplicar fila, scheduler ou estado de circuit breaker.

## Goals / Non-Goals

**Goals:**

- honrar a internação local selecionada sem depender da estabilidade da chave
  legada;
- recuperar o clique comprovadamente frágil com timeout e pós-condição;
- tornar o commit clínico e a cobertura atômicos por chunk;
- retomar somente períodos sem cobertura explícita;
- limitar repetição entre runs automáticos a no máximo 60 minutos;
- localizar falhas por subetapa usando somente enums e contadores sanitizados.

**Non-Goals:**

- importação ou upload manual de PDF;
- Celery, Redis, nova fila, novo worker ou serviço externo;
- backoff exponencial ou espera acima de uma hora;
- substituir a taxonomia de falhas e o retry interno de 60 segundos;
- usar a chave legada como identidade canônica;
- alterar a automação exploratória `path2.py` ou acessar o legado em testes;
- declarar cobertura explícita cross-admission para runs antigos sem
  `admission_id`.

## Decisions

### D1 — Resolver a internação por fatos estáveis e falhar fechado

O worker resolve `admission_id` para uma `Admission` pertencente ao paciente do
run e passa ao adapter um contexto mínimo em memória: data de início, data de
alta quando houver, estado ativo/encerrado e `source_admission_key` como dica.
O bridge seleciona a linha atual da tabela legada por esta ordem:

1. interseção com o intervalo solicitado;
2. início igual ao da internação local;
3. estado compatível: local ativa exige linha aberta; local encerrada exige fim
   compatível;
4. a chave legada pode desempatar candidatos já compatíveis, mas nunca tornar
   compatível uma linha de período/estado diferente.

Um único candidato compatível é aceito mesmo se a chave mudou. Zero ou mais de
um candidato após o desempate produzem erro sanitizado; no modo alvo,
`open_internacao_detail` não usa o fallback atual de primeira linha. Falhas de
navegação da internação alvo também falham o chunk, em vez de retornar vazio ou
seguir para outra internação.

Sem `admission_id`, o bridge preserva o comportamento de todas as internações
sobrepostas para compatibilidade. Esse modo não cria cobertura explícita por
internação, pois não há identidade local inequívoca.

**Alternativas rejeitadas:** igualdade exclusiva de `source_admission_key`
(falhou na evidência real); primeira linha/mais recente sem validar período
(risco clínico); persistir a chave atual como nova identidade (a volatilidade
continuaria).

### D2 — Clique normal curto, fallback DOM e pós-condição única

`click_evolucao` mantém o clique Playwright normal como primeira estratégia,
mas limita essa tentativa a uma fração curta do deadline compartilhado. Se a
actionability expirar e os campos da evolução ainda não estiverem visíveis, a
função executa `element.click()` no locator já validado. Ambas as estratégias
convergem para a mesma pós-condição: os dois inputs obrigatórios de data devem
estar visíveis dentro do deadline restante.

O fallback não desabilita timeout, não usa JavaScript global, não procura outro
paciente/internação e não transforma ausência de modal em sucesso. Timeout
continua `NavigationTimeoutError`; demais falhas usam mensagem constante.

**Alternativas rejeitadas:** somente `force=True` (mantém dependência do pipeline
de actionability e não foi a estratégia comprovada); clique DOM sem
pós-condição (pode produzir falso sucesso); elevar o timeout de 30 segundos
(não corrige a causa).

### D3 — Ledger de cobertura contém somente fatos concluídos

Será criado `EvolutionExtractionCoverage` com:

- FK para a `Admission` local;
- `source_system`, `start_date` e `end_date` inclusivos;
- FK anulável para a `IngestionRun` que confirmou o chunk;
- `event_count` agregado e `completed_at`;
- unicidade por internação, origem e limites do chunk;
- validação de intervalo não invertido e índices para consulta temporal.

Não haverá estados `pending` ou `failed`: a ausência da linha significa
cobertura não comprovada. Falhas continuam no lifecycle e stage metrics já
existentes. Um chunk concluído com zero evoluções também cria cobertura, pois
"consultado e vazio" é diferente de "não consultado".

O planner alvo calcula a união dos intervalos explícitos; não infere cobertura
pela presença de `ClinicalEvent`. A extensão de overlap continua permitida para
capturar registros tardios, e a unicidade/idempotência absorve reprocessamento.
O planner legado sem internação permanece apenas para compatibilidade e não é
fonte de cobertura explícita.

**Alternativas rejeitadas:** flag em `ClinicalEvent` (não representa períodos
vazios); um JSON no run (não sobrevive como visão consolidada entre runs);
ledger diário (mais linhas sem necessidade; intervalos permitem a mesma união).

### D4 — Commit atômico e métricas cumulativas por chunk

Para runs alvo, cada janela do planner é dividida pelo chunker canônico já
existente, com no máximo 15 dias e overlap determinístico. Cada chunk chama o
adapter separadamente. O bridge recebe no máximo um chunk e seu chunker interno
produz uma única janela, evitando nova implementação do algoritmo.

Dentro de uma transação PostgreSQL externa por chunk, o worker:

1. persiste eventos pelo serviço compartilhado `ingest_evolutions`;
2. cria ou atualiza idempotentemente a cobertura;
3. incrementa os contadores cumulativos do run.

Somente depois do commit avança ao próximo chunk. Se persistência ou cobertura
falhar, ambas são revertidas. Se um chunk posterior falhar, o run segue a
política atual (`queued` para retry ou terminal `failed`), enquanto eventos,
cobertura e contadores dos chunks anteriores permanecem. O retry replana e
pula os intervalos cobertos.

Um resultado vazio só é confirmável quando o conector observou explicitamente
o diálogo/resultado sem evoluções. No modo alvo, qualquer desvio de navegação
não pode ser convertido em lista vazia.

**Alternativas rejeitadas:** callback de persistência dentro do parser PDF
(acopla domínio e conector); acumular todo o run (causa atual); uma transação
para o run inteiro (descarta progresso e prende locks por tempo excessivo).

### D5 — Guard entre runs usa `next_retry_at` e teto fixo de 60 minutos

`enqueue_most_recent_admission_full_sync()` consulta o resultado terminal mais
recente (`full_sync` ou `full_admission_sync`) da mesma `Admission`. Se ele for
falha e tiver terminado há menos de 60 minutos, a nova `full_sync` automática é
criada normalmente, no batch atual, porém com:

```text
next_retry_at = failed_run.finished_at + 60 minutes
```

Se o prazo já venceu, o run nasce elegível. Se o resultado terminal mais
recente foi sucesso, não há deferimento; isso equivale a zerar o guard sem
contador adicional. O enqueue manual de `full_admission_sync` não chama essa
política e permanece imediato. O worker já ignora rows antes de
`next_retry_at`, e o batch/orquestrador já aguardam queue drain; logo não há
polling especial nem estado novo.

O retry de uma mesma run continua +60 segundos e `invalid_payload` continua
fail-fast conforme a spec existente. O guard é fixo, não exponencial, e nunca
empurra a execução além de 60 minutos contados da falha terminal.

**Alternativas rejeitadas:** `30 min → 1 h → 2 h → 4 h` (espera excessiva para a
operação); model de circuit breaker (duplica estado derivável); apenas cooldown
do censo (não é por internação); não enfileirar (quebra vínculo/fechamento do
batch e perde o trabalho futuro).

### D6 — Subetapas são enums sanitizados e agregados

O adapter aceita callback opcional de progresso, repassado somente ao caminho
real. O bridge emite transições `started`, `succeeded` ou `failed` para um
conjunto fechado, por exemplo:

- `evolution_search_navigation`;
- `evolution_admissions_capture`;
- `evolution_target_selection`;
- `evolution_detail_open`;
- `evolution_action_activation`;
- `evolution_report_generation`;
- `evolution_pdf_download`;
- `evolution_pdf_parse`;
- `evolution_chunk_commit` (emitido pelo worker).

O callback do worker materializa `IngestionRunStageMetric` sem erro bruto e sem
parâmetros dinâmicos. `details_json` do estágio agregado registra apenas
contadores (`chunks_planned`, `chunks_committed`, `chunks_failed`,
`events_processed`) e ordinal limitado quando necessário; não registra datas,
identificadores, textos, URLs, HTML, PDF, seletores ou credenciais. Falha do
callback de observabilidade não mascara nem reclassifica a falha clínica, e o
callback ausente preserva testes/stubs e contratos anteriores.

**Alternativas rejeitadas:** logs livres com `str(exc)` (risco de vazamento);
novo sistema de telemetria (YAGNI); identificadores de paciente/chave para
correlação (desnecessários porque a métrica já referencia o run).

## Risks / Trade-offs

- **[Dados locais antigos não distinguem duas internações com mesmo início e
  estado]** → falhar fechado como ambíguo; nunca escolher primeira linha.
- **[Coverage é marcada após retorno vazio indevido]** → modo alvo torna toda
  falha de ação obrigatória; vazio só após resultado explícito do legado.
- **[Evento persiste, mas coverage falha]** → transação externa por chunk reverte
  os dois.
- **[Chunks com overlap repetem eventos]** → deduplicação/revisão canônica e
  `update_or_create` de coverage mantêm idempotência.
- **[Run automático futuro mantém batch aberto e workers ociosos]** → espera é
  intencional, visível em `next_retry_at` e limitada a 60 minutos; preserva
  queue/batch existentes.
- **[Stage metrics aumentam volume]** → enum fechado e uma linha por transição
  terminal relevante; sem payloads.
- **[Callbacks introduzem acoplamento]** → protocolo opcional mínimo; conector
  conhece somente enum/status, não ORM.
- **[Migration em tabela clínica operacional]** → tabela nova sem backfill nem
  lock de reescrita de tabela existente.

## Migration Plan

1. Aplicar migration que cria a tabela vazia de cobertura; nenhum dado existente
   é declarado coberto automaticamente.
2. Liberar seleção alvo e clique resiliente antes de ativar commits por chunk.
3. Ativar persistência incremental; primeiras execuções alvo preenchem o ledger
   organicamente.
4. Ativar deferimento automático e telemetria sanitizada.
5. Validar com fixtures sintéticas: duas internações sobrepostas, chave legada
   alterada, timeout de clique, sucesso vazio, primeiro chunk confirmado e
   segundo falho, retry que pula o primeiro e deferral de 60 minutos.

Rollback de código é seguro; a tabela de cobertura pode permanecer sem uso. Se
a migration precisar ser revertida, remover somente a tabela nova depois de
recuar o código. Eventos clínicos já confirmados não são apagados no rollback.

## Open Questions

Nenhuma. As decisões funcionais foram confirmadas: `admission_id` restringe o
alvo; ausência preserva todas as sobrepostas; progresso parcial permanece mesmo
com run falho/reenfileirado; novo model/migration está autorizado; o guard entre
runs reutiliza mecanismos existentes e tem teto fixo de 60 minutos.

## Dimensionamento dos slices

Cinco slices verticais, cada um entregando comportamento testável:

1. **HTEFS-S1** — clique `Evolução` resiliente com pós-condição.
2. **HTEFS-S2** — seleção e navegação estrita da internação alvo ponta a ponta.
3. **HTEFS-S3** — ledger, planner, commit incremental e retomada por chunk em um
   único slice transacional.
4. **HTEFS-S4** — deferimento automático fixo via `next_retry_at`.
5. **HTEFS-S5** — subetapas sanitizadas e contadores agregados.

S3 permanece único porque separar model/planner de commit produziria um slice
horizontal ou permitiria cobertura sem persistência atômica. S4 é independente
de S1–S3 e pode ser verificado isoladamente, mas a ordem recomendada prioriza a
correção da causa real. S5 vem por último para instrumentar o fluxo definitivo.
