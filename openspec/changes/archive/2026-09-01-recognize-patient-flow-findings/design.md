## Context

O pipeline de censo cria `admissions_only`, `demographics_only` e, quando há
Admission, `full_sync`. A regra fail-closed atual transforma toda lista vazia de
internações batch-bound em `invalid_payload`. A investigação agregada de 24
horas mostrou que a maior parte dessas ocorrências repetidas estava ligada a
atendimentos recentes ou recém-nascidos; uma revisão manual confirmou também
internações recentes sem primeira evolução e um grupo menor de suspeitas
residuais. Em `full_sync`, porém, a maioria dos pacientes também obteve sucesso
na mesma janela e a razão dominante era timeout, então ausência de evolução
local não prova sucesso da extração.

Um spike read-only no legado, executado em container efêmero e sem salvar
payload, confirmou:

- `Atendimentos` é um único item visível do mesmo menu lateral;
- a tabela fica em `frame_pol`, sob o componente
  `tabela_resultados:resultList`;
- o corpo usa `tabela_resultados:resultList_data`, rows `data-ri`/`data-rk` e
  quatro células: Data, Tipo, Especialidade/Serviço e Profissional;
- Data contém somente `DD/MM/AAAA`, sem horário;
- é possível retornar a `Internações` na mesma sessão.

O sistema não deve persistir profissional ou linha bruta. Stakeholders são a
gestão de prontuários, qualidade e operação da ingestão, que precisam separar
fluxo hospitalar ainda em consolidação de falha técnica e de caso que requer
revisão no legado.

## Goals / Non-Goals

**Goals:**

- consultar `Atendimentos` apenas após `admissions_only` batch-bound vazio;
- aceitar somente evidência recente inequívoca e manter o restante fail-closed;
- preservar paridade de resultado entre worker persistente e clássico;
- separar achado operacional de resultado técnico de extração;
- projetar rótulos atuais e auto-resolvíveis sem nova tabela de estado;
- exibir os rótulos em `/censo`, `/beds`, admissões e métricas de batch;
- manter consultas de UI limitadas e logs/relatórios sanitizados;
- preservar monólito, fila PostgreSQL e runtime systemd atuais.

**Non-Goals:**

- abrir detalhe de atendimento para descobrir horário;
- capturar todos os atendimentos de todos os pacientes;
- persistir profissional, HTML, screenshot, cookies ou conteúdo clínico;
- transformar timeout/erro de PDF/full-sync em sucesso;
- criar modelo de workflow manual, status novo, fila, worker ou dependência;
- alterar exportação XLSX, medição de ocupação ou capacidade oficial;
- executar acesso real ao legado em testes, slices ou quality gate;
- fazer deploy/rollout durante a implementação.

## Decisions

### D1 — Um contrato mínimo compartilhado representa o resultado da busca

Um value object imutável e testável, `PatientFlowSnapshot` ou nome equivalente,
transportará:

- a lista normalizada de internações;
- presença e data válida do atendimento mais recente, somente em memória;
- uma faixa de recência calculada no fuso `America/Bahia`.

O contrato não transportará nome do paciente/profissional, texto, HTML, setor
inferido, URL ou cookies. Métodos públicos antigos que retornam apenas a lista
de internações permanecem como wrappers de compatibilidade; os workers usam o
contrato enriquecido onde suportado.

**Alternativas rejeitadas:** persistir a lista completa (dados desnecessários),
guardar em `parameters_json` (mistura input e resultado), retornar dict livre
(frágil para dois workers) ou criar model/migration antes de existir workflow
manual (YAGNI).

### D2 — O fallback é condicional, bounded e equivalente nos dois workers

Somente `admissions_only` ligado a batch e com lista normalizada vazia consulta
`Atendimentos`. Snapshot não vazio, standalone e full-sync preservam seus
caminhos atuais. O worker persistente reutiliza `frame_pol` e a sessão aberta; o
clássico estende `path2.py` com saída lateral opcional, preservando o JSON de
internações existente. Nenhum caminho lança outro browser ou login dentro do
job.

O parser identifica o corpo por
`#tabela_resultados\:resultList_data > tr`, exige quatro células e aceita datas
`DD/MM/AAAA`. Rows inválidas são ignoradas; se nenhuma data válida permanecer,
o vazio continua fail-closed. Testes usam DOM/JSON sintéticos e nunca o legado.

A ordem S1→S2 cria primeiro o produtor de produção persistente e depois fecha a
paridade clássica. A verificação independente de S2 encontrou uma lacuna de
navegação mascarada por mocks; PFIF-S2R passa a ser gate corretivo obrigatório
antes de S3. Deploy é proibido entre S1, S2 e S2R.

**Alternativas rejeitadas:** consultar atendimentos para todo paciente (carga
sem valor), criar intent/queue nova (complexidade), abrir detalhe de cada row
(mais ações e fragilidade) ou usar texto/nome de setor como única evidência.

### D3 — Data sem hora produz três estados conservadores

Como a fonte não fornece horário:

- hoje ou ontem local: `recent_confirmed`, garantidamente dentro de 48 horas;
- anteontem: `boundary`, intervalo ambíguo;
- três ou mais dias: `stale`;
- sem data válida: `none`.

Somente `recent_confirmed` aceita o vazio como achado
`recent_encounter_without_admission`. `boundary`, `stale` e `none` seguem a
exceção vazia atual. Data futura é inválida. O cálculo é puro e recebe `today`
injetável para testes.

### D4 — Achado recente conclui o run sem inventar internação

Quando o fallback comprova atendimento hoje/ontem:

- `admissions_only` termina `succeeded` com `admissions_seen=0` e demais
  contadores clínicos zero;
- nenhuma Patient/Admission é criada por essa captura;
- nenhum full-sync é enfileirado;
- o `demographics_only` já pertencente ao batch permanece;
- stage metric registra um enum fechado de outcome e recência, sem data ou
  identificador;
- cleanup, attempt success e batch drainage seguem os caminhos canônicos.

O stage dedicado `encounter_fallback` separa a captura de atendimento da etapa
`admissions_capture`. Qualquer falha de navegação/parser continua com taxonomia
sanitizada existente. Full-sync vazio permanece inválido.

**Alternativas rejeitadas:** criar Admission sintética (falsifica domínio),
desligar a regra de vazio por setor/idade (oculta payload ruim), ou manter run
failed e apenas trocar texto (batch continuaria alarmando falsamente).

### D5 — Rótulos são uma projeção atual, não uma segunda fonte de verdade

Um serviço de domínio/apresentação em `apps.ingestion` fará consultas bulk e
retornará DTOs com `code`, `label`, `severity` e `requires_manual_review`. Ele
não grava estado. A evidência vem de dados existentes e do outcome fechado no
stage metric. Uma execução posterior, uma nova internação/evolução ou saída do
censo muda a projeção automaticamente.

Prioridade inicial:

1. atendimento recente sem internação;
2. RN de 0–4 dias sem internação: aguardando registro;
3. RN de 5–28 dias, sem internação e no setor obstétrico 3A: possível
   acompanhante, revisão manual;
4. internação com menos de 48 horas e sem eventos: aguardando primeira evolução;
5. internação ativa com pelo menos 48 horas, presente no censo e sem evento nas
   48 horas anteriores: suspeita residual, revisão manual.

Nas regras 2 e 3, "sem internação" significa sem internação **ativa**
(`discharge_date` nula): internação já encerrada é fato histórico que não
representa a presença atual no censo. Leitura fixada na verificação de
PFIF-S3 (fail-soft: severity `info`, auto-resolução com internação ativa
posterior ou saída do censo); mudança exige evidência do canário S5 e
decisão de produto, não antecipação.

Observação adulto código 954, CRPA e demais setores podem enriquecer o texto de
um fluxo recente, mas setor isolado não prova atendimento. Timeout ou
`invalid_payload` continuam em eixo técnico paralelo; particularmente, a regra
residual nunca converte full-sync falho em sucesso.

O serviço deve resolver muitos pacientes em conjunto, com orçamento fixo de
queries e sem N+1.

**Alternativas rejeitadas:** tabela de flags com resolução manual ainda
inexistente (estado stale), lógica em templates/views (duplicação) e rótulo
baseado somente em ausência local de eventos (pode ser efeito do timeout).

### D6 — As três páginas reutilizam o mesmo mapa de achados

`/censo`, `/beds` e a página de admissões recebem o mesmo mapa bulk por patient
id/registro. Templates apenas renderizam badges acessíveis; não classificam.
Autenticação atual não muda. `/beds` mantém medição e reconciliação intactas;
`/censo` mantém filtros/ordenação/exportação, e o XLSX não ganha coluna neste
change.

Uma template filter mínima pode resolver lookup dinâmico em mapas, mas não pode
conter regra de negócio.

### D7 — Batch e health preservam o status auditável

Não haverá novo choice nem reescrita histórica de `CensusExecutionBatch.status`.
A apresentação deriva:

- `Concluído com achados` quando o batch persistido succeeded possui outcomes
  operacionais;
- `Falha parcial` quando coexistem achados e falhas técnicas;
- os rótulos atuais existentes quando não há achado.

O health check passa a contar `recognized_recent_encounter` separadamente e
exclui somente runs vazios com stage/outcome allowlisted da invariante
`empty_success`. Qualquer `admissions_seen=0` succeeded sem essa evidência
continua violação. Saídas são agregadas e não listam paciente/run/batch.

### D8 — Cinco entregas e um gate corretivo mantêm verticalidade

1. **PFIF-S1:** fallback persistente realista até run/batch reconhecido; máximo
   seis arquivos.
2. **PFIF-S2:** paridade do worker clássico no mesmo contrato; máximo quatro
   arquivos. A primeira implementação foi reprovada por verificação
   independente.
3. **PFIF-S2R:** correção bloqueante da navegação clássica e da elegibilidade do
   sidecar; máximo três arquivos de código/teste.
4. **PFIF-S3:** classificador bulk e rótulo end-to-end em `/censo`; máximo
   quatro arquivos.
5. **PFIF-S4:** reutilização dos rótulos em `/beds` e admissões; máximo seis
   arquivos.
6. **PFIF-S5:** métricas/health/runbook com distinção agregada; máximo seis
   arquivos.

Separar S1/S2 evita um slice Playwright de dez arquivos. S2R não adiciona
capacidade: fecha o objetivo vertical de S2 com um teste stateful que não mocka
a unidade sob avaliação. S3 cria o único classificador e já o prova numa tela.
S4 contém apenas consumidores restantes. S5 observa o comportamento definitivo.
O slice corretivo adicional é justificado pelo defeito crítico encontrado após
o commit; incorporá-lo a S3 misturaria ingestão e apresentação e violaria a
Stop Rule.

## Risks / Trade-offs

- **[Atendimento anteontem pode ter menos de 48 horas]** → estado limítrofe,
  nunca aceito automaticamente.
- **[Fallback aumenta carga no legado]** → somente após vazio batch-bound e uma
  leitura tabular; sem detalhe por row.
- **[Workers divergem entre S1 e S2]** → proibir deploy intermediário e exigir
  PFIF-S2R aprovado antes de S3.
- **[Mock de alto nível mascara navegação ausente]** → teste stateful deve manter
  a página em `Internações` até o clique exato em `Atendimentos`, executar o
  parser real e falhar se a ordem for invertida.
- **[Outcome em JSON livre sofre typo]** → enums/constantes fechados e testes de
  contrato; health aceita somente valor allowlisted.
- **[Rótulo residual mascara timeout]** → eixo técnico sempre preservado e UI
  pode mostrar ambos.
- **[Classificador causa N+1 em `/beds`]** → API bulk e teste de orçamento fixo.
- **[Label atual muda historicamente]** → comportamento intencional nas páginas
  clínicas; batch conserva status e stages auditáveis.
- **[DOM do legado muda]** → parser fail-closed, seletor encapsulado e fixture
  sintética baseada apenas na estrutura confirmada.
- **[Vazamento em logs/relatórios]** → sentinelas sensíveis em testes, enum-only
  stages e proibição de HTML/row values.

## Migration Plan

1. Manter S2 como incompleto após a reprovação independente e não fazer deploy.
2. Implementar PFIF-S2R sem acesso real, preservando o commit correto de S1 e as
   partes válidas de S2; exigir nova verificação independente.
3. Somente após S2R aprovado, implementar S3–S5 e executar quality gate,
   integração, OpenSpec strict e markdown lint.
4. Antes do deploy, registrar baseline agregado de 24 horas: empty success,
   falhas por intent/reason e achados reconhecidos.
5. Fazer backup operacional conforme runbook da release mesmo sem migration,
   pois o change altera semântica de batch.
6. Implantar um worker persistente canário; observar pelo menos um ciclo
   completo sem escalar.
7. Confirmar saída sanitizada, queda de `admissions_only invalid_payload`,
   ausência de aumento de timeout e health saudável.
8. Escalar somente após canário; não reclassificar runs históricos.
9. Rollback: voltar à imagem anterior. Stage details adicionais são JSON
   inócuo e runs já sucedidos por evidência recente permanecem auditáveis.

## Open Questions

Nenhuma bloqueante. O detalhe de `Atendimentos` poderá ser estudado em change
futuro se a faixa limítrofe tiver volume operacional relevante; não pertence a
este escopo.
