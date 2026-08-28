# Design: Reparar o pipeline persistente de internações

## Context

O fluxo produtivo atual é:

```text
extract_census
  -> process_census_snapshot
  -> Patient/PatientMovement
  -> admissions_only + demographics_only
  -> full_sync para quem possui Admission
  -> evoluções
```

A investigação agregada confirmou snapshots completos, movimentações recentes e
10 workers persistentes ativos. A transição de capturas de internação não vazias
para zero coincide com o cutover persistente. Em
`RealHandleBridge.navigate_to_admissions()`, `_read_and_build_snapshot(page)` lê
o iframe corretamente. O resultado só é injetado quando o handle expõe
`set_html()`, método presente nos fakes, mas ausente no
`PlaywrightSessionHandle`. O fallback guarda uma URL. Em seguida,
`get_page_html()` chama `page.content()` no documento superior e tenta extrair a
tabela que existe apenas em `frame_pol`, produzindo `[]`.

O adapter aceita o array vazio; os workers persistem `admissions_seen=0` e
concluem o run. O serviço que cria `full_sync` retorna `None` sem internação. A
demografia continua funcionando, porém em duplicidade porque o censo e o
follow-up de internações são produtores concorrentes do mesmo refresh.

## Goals / Non-Goals

### Goals

- Transportar corretamente o snapshot real do iframe até o adapter.
- Impedir falso sucesso vazio em batches clínicos sem remover zero legítimo de
  uma solicitação standalone.
- Restaurar um único produtor demográfico por censo.
- Recuperar o estado atual de forma limitada, idempotente e auditável.
- Expor invariantes operacionais agregadas e alertáveis.
- Padronizar falha do processador de censo com `CommandError`.
- Manter slices pequenos, verticais e verificáveis com TDD.

### Non-Goals

- Reescrever o adapter inteiro ou eliminar todos os containers sintéticos.
- Modificar o DOM real com `page.set_content()` ou novo `set_html()`.
- Alterar modelos, migrations, locks, status FSM ou políticas de retry.
- Reabrir todos os runs do período do incidente.
- Inferir uma correção para falhas de evolução ainda não caracterizadas.
- Introduzir infraestrutura externa de alerta.

## Decisions

### 1. Cache transitório pertence ao bridge

`RealHandleBridge` manterá um payload sintético privado e opcional para a
captura de internações atual. Após `_read_and_build_snapshot()` retornar, o
bridge serializa a lista no mesmo contrato já consumido pelo adapter.
`get_page_html()` devolve esse payload em vez de reconstruir a tabela pelo HTML
do documento superior.

O payload será limpo antes de iniciar outra navegação e depois de cleanup,
restart, bootstrap, shutdown ou falha. O estado nunca será persistido, logado ou
compartilhado entre processos.

**Alternativas rejeitadas:**

- adicionar `set_html()` ao handle real: destruiria o DOM da aplicação e
  confundiria estado de navegador com fixture de teste;
- ler novamente `page.content()`: não inclui o documento interno do iframe;
- lançar novo Playwright/subprocess: viola o objetivo de sessão persistente.

### 2. Empty fail-closed é contextual ao batch

Lista vazia pode ser um resultado legítimo de sincronização manual de um
registro sem internações. Entretanto, um run ligado a batch de censo ou
recuperação representa paciente ocupado e exige ao menos uma internação
normalizada.

Os dois workers aplicarão a mesma validação imediatamente após a extração e
antes de `persist_admissions_snapshot`. Uma exceção tipada e sanitizada seguirá
a taxonomia existente de payload inválido. O run usa retry/falha já existente;
não persiste Patient/Admission a partir desse resultado, não marca estágio como
sucesso e não cria demografia/full-sync.

A validação cobre `admissions_only` e a captura inicial de intents full-sync
batch-bound. Não altera o resultado standalone vazio nem a UI histórica de
`no admissions found`.

### 3. O censo é dono da demografia batch-bound

`process_census_snapshot` já cria exatamente um `demographics_only` com o mesmo
batch para cada paciente ocupado deduplicado. Logo, os workers só criarão o
follow-up demográfico quando o `admissions_only` não possuir batch.

O `full_sync` permanece criado após captura válida e mantém o batch da origem.
Não será adicionada constraint ou tabela de deduplicação: a regra de propriedade
é suficiente e evita migration.

### 4. Recuperação usa novo batch e não reescreve história

Um comando dedicado terá dry-run como comportamento padrão e `--apply`
explícito. O planejamento seleciona somente o conjunto do último censo com
proveniência única e completude aceita, deduplica prontuários ocupados e exclui:

- paciente já representado por qualquer `admissions_only` ativo;
- paciente já representado em batch de recuperação do mesmo censo;
- linha sem identificador utilizável.

`--limit` positivo torna o primeiro apply um canário. O apply cria um
`CensusExecutionBatch` marcado apenas com metadados operacionais agregados e
referência não clínica ao run de censo, então usa o helper canônico para criar
`admissions_only`. S3 impede demografia duplicada nesse batch; uma captura
válida gera `full_sync` normalmente.

Runs históricos do incidente permanecem imutáveis para auditoria. Falhas do
novo recovery seguem retries existentes em vez de criar outra máquina de
estados.

### 5. Health check é um command alertável, não um provedor

Um serviço de consulta agregada e um management command exporão uma fotografia
de janela configurável. O comando nunca lista IDs de run, batch, paciente,
internação ou evento. Os sinais mínimos são:

- quantidade de `admissions_only` batch-bound concluídos com zero;
- capturas válidas batch-bound sem `full_sync` correspondente;
- excesso de `demographics_only` em relação a admissions no mesmo batch;
- contagem e idade do trabalho ativo;
- resultados full-sync e falhas por `failure_reason`;
- quantidade agregada de eventos criados;
- idade agregada das últimas atualizações de movimento, internação e evento,
  somente quando limiares opcionais forem fornecidos.

Violação de invariantes ou limiar retorna status não zero via `CommandError`.
Sem violação, retorna zero. Threshold de taxa só é avaliado com amostra mínima
configurável, evitando divisão instável. Integração futura com systemd ou
monitor usa o exit code; e-mail/webhook fica fora.

As falhas de evolução passam a ser diferenciadas por timeout, payload inválido
e demais categorias. Se continuarem após recuperar internações, um change
separado deverá partir dessa evidência, não de uma correção especulativa.

### 6. Management command falha com `CommandError`

`process_census_snapshot` substituirá `sys.exit(1)` por `CommandError` ao receber
resultado rejeitado. A camada de serviço continua retornando seu resultado
estruturado. `run_single_cycle()` já captura `Exception` na etapa de
processamento e passa a classificar a rejeição como `processing_failed`.

Não será adicionado `except BaseException` amplo. Testes provarão que nenhuma
fila, batch ou movimento adicional é criado na rejeição e que o loop não é
abortado por `SystemExit`.

### 7. Dimensionamento em seis slices

1. **RPAP-S1:** bridge conserva e limpa o snapshot real; dois arquivos.
2. **RPAP-S2:** vazio batch-bound falha nos dois workers; até cinco arquivos.
3. **RPAP-S3:** propriedade única da demografia; três arquivos.
4. **RPAP-S4:** recuperação atual dry-run/apply limitada; até quatro arquivos.
5. **RPAP-S5:** health check e runbook de rollout; até quatro arquivos.
6. **RPAP-S6:** `CommandError` no processador e regressão do orquestrador; três
   arquivos.

Separar S1 de S2 permite provar primeiro o transporte correto sem misturar regra
de negócio. S3 é independente e reduz carga antes do recovery. S4 depende de
S2/S3. S5 observa o fluxo já corrigido. S6 é uma proteção de censo independente,
mas fica por último para manter o hotfix clínico na frente. Mais slices gerariam
overhead; menos slices misturariam extração, domínio, operação e orquestração.

## Privacy and Security

- Testes usam apenas identificadores e conteúdo sintéticos.
- Cache do bridge vive apenas em memória e por job.
- Health e recovery imprimem somente contagens, percentuais, idades e estados.
- Relatórios temporários não podem conter `.env`, URLs reais, cookies, HTML,
  PDF, nomes, prontuários ou texto clínico.
- Nenhum artefato de produção é versionado.

## Migration and Rollout Plan

1. Implementar S1–S6 em ordem, com stop rule e verificação por terceiro LLM.
2. Rodar quality gate completo, integração, OpenSpec strict e markdown lint.
3. Criar backup operacional protegido antes do deploy.
4. Fazer deploy sem executar recovery e iniciar um único worker canário.
5. Verificar agregados: capturas não vazias, avanço de Admission, criação de
   full-sync, ausência de identificadores em logs e health check saudável.
6. Parar se houver zero vazio, crescimento anormal de retries, sessão instável,
   fila envelhecendo ou saída não sanitizada.
7. Escalar gradualmente até as réplicas autorizadas apenas com saúde estável.
8. Rodar recovery em dry-run; aplicar limite pequeno; aguardar drenagem e
   evoluções; então repetir em lotes.
9. Não reabrir runs históricos. Preservar evidência do incidente.
10. Se evoluções mantiverem falhas acima do limiar, interromper ampliação e abrir
    change específico por causa comprovada.
11. Rollback operacional: parar workers corrigidos, restaurar imagem anterior
    apenas se necessário e não desfazer internações já persistidas
    idempotentemente.

## Open Questions

- Qual janela e taxa de falha devem ser configuradas no monitor de produção após
  a primeira observação canária?
- Qual tamanho de lote de recovery mantém folga adequada no sistema fonte?
- Falhas residuais de evolução concentram-se em timeout, payload ou seletor após
  restaurar todas as internações atuais?
