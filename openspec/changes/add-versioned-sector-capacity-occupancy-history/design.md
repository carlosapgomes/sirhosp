# Design: Versioned sector capacity and occupancy history

## Context

A página `/beds` agrega o maior `captured_at` de `CensusSnapshot`, apresenta os
estados dos leitos e expande os pacientes ocupantes, mas não conhece capacidade
oficial. As tabelas `Ward` e `Bed` existem, porém estão vazias em produção e não
resolvem vigência, reutilização de código ou vários códigos consumindo uma única
capacidade.

A planilha administrativa `setores-leitos.xls`, com SHA-256
`fa5c4e95941794b4a90f2011d0584ae9eb5d4a5178e7e4022debeef4db8ca4dd`, foi
comparada com os 47 códigos presentes no censo de produção. A comparação
identificou 39 grupos com capacidade, três códigos sem capacidade e dois casos
que exigem agregação. O código `2155` também mudou historicamente de 2A Gastro
para 2A Clínica Isolamento, demonstrando que código e nome não podem ser uma
identidade eterna.

A nova estatística depende de censos completos. O change arquivado e concluído
`openspec/changes/archive/2026-08-16-guard-census-extraction-completeness`
protege a extração e, no slice GCEC-S2, o processamento direto. A integração
deste change não pode ser ativada antes dessa defesa em profundidade.

Stakeholders principais são diretoria, qualidade, gestão de leitos e equipes
assistencial e administrativa responsáveis pelo saneamento do sistema legado.
As estatísticas não podem transformar ausência de evolução em alta presumida.

## Goals / Non-Goals

**Goals:**

- representar capacidades e composições com vigência diária;
- permitir reutilização futura de código e mudança de nome sem alterar o
  passado;
- materializar uma medição auditável por censo completo e aceito;
- preservar os valores resolvidos, configuração e algoritmo de cada medição;
- persistir resumo diário por grupo e hospital;
- expor capacidade, percentual, excedente e cobertura em `/beds`;
- manter operação simples com Django, PostgreSQL e management commands;
- não armazenar dados identificáveis de pacientes nas novas tabelas.

**Non-Goals:**

- reprocessar censos anteriores à ativação;
- fornecer UI histórica nesta entrega;
- deduzir alta ou remover paciente suspeito do numerador;
- calcular a Obstetrícia 3A sem os pares cama-berço;
- importar periodicamente a planilha original;
- tornar o catálogo livremente editável no Django Admin;
- substituir `Ward` e `Bed` ou refatorar outras páginas de setores;
- criar Celery, Redis, microserviço ou scheduler novo;
- alterar o ADC existente de Fluxo Hospitalar.

## Decisions

> **Nota de governança:** as decisões abaixo estão registradas de forma
> auditável na
> [ADR-0003 — Catálogo temporal de capacidade e materialização imutável de
> ocupação](../../../docs/adr/ADR-0003-catalogo-temporal-capacidade-materializacao-imutavel.md),
> criada antes do arquivamento deste change conforme exigido pela tarefa
> 5.1. Nenhuma delas altera requisitos funcionais das specs.

### 1. Versionar o catálogo inteiro por data efetiva

Cada publicação cria uma fotografia completa do catálogo para uma
`effective_from` em `America/Bahia`. Para uma data de censo, seleciona-se a
versão mais recente cuja vigência seja menor ou igual à data local.

Estrutura conceitual:

```text
CapacityCatalogVersion
  effective_from (date, unique)
  source_reference
  source_sha256
  schema_version
  created_at

CapacityGroupDefinition
  catalog -> CapacityCatalogVersion (PROTECT)
  stable_key
  display_name
  official_capacity (nullable)
  calculation_policy

CapacitySectorMembership
  catalog -> CapacityCatalogVersion (PROTECT)
  group -> CapacityGroupDefinition (PROTECT)
  source_code
  configured_source_name
```

Restrições lógicas e de banco:

- uma versão por data efetiva;
- `stable_key` único dentro da versão;
- `source_code` único dentro da versão;
- capacidade estritamente positiva quando informada;
- política `standard` exige capacidade;
- política `linked_slots_pending` exige capacidade;
- política `unrated` exige capacidade nula;
- membro e grupo devem pertencer à mesma versão;
- referências históricas usam `PROTECT`.

Uma fotografia completa foi escolhida em vez de intervalos independentes por
setor porque elimina combinações temporais inválidas, garante uma única
configuração por dia e simplifica auditoria e rollback. A duplicação de 42
grupos por alteração é pequena e aceitável.

`stable_key` identifica uma série oficial entre versões. Quando um código passa
a representar outro setor, a próxima versão o associa a outra `stable_key`.
Isso atende ao caso futuro equivalente à mudança histórica do código `2155`.
Não haverá backfill para reconstruir a versão antiga da Gastro.

### 2. Publicar somente por comando controlado

O comando proposto é:

```text
activate_sector_capacity_catalog \
  --input <arquivo-json> \
  --effective-from YYYY-MM-DD \
  [--dry-run]
```

O comando deve:

- usar `timezone.localdate()` com `America/Bahia`;
- rejeitar vigência igual ou anterior ao dia corrente;
- validar o documento inteiro antes de gravar;
- calcular e persistir o SHA-256 do documento de entrada;
- criar versão, grupos e membros em uma única transação;
- em `--dry-run`, não gravar nada;
- para mesma data e mesmo hash, retornar sucesso idempotente sem duplicar;
- para mesma data e conteúdo diferente, rejeitar a operação;
- não editar nem remover versões existentes.

A primeira configuração fica em arquivo JSON versionado e sintético, sem dados
de pacientes. Mudanças futuras também fornecem uma fotografia completa. Django
Admin editável foi rejeitado porque permitiria quebrar vigências e
imutabilidade sem validação atômica.

### 3. Políticas de cálculo mínimas

A primeira entrega implementa somente três políticas:

- `standard`: soma ocupados dos membros e divide uma vez pela capacidade;
- `linked_slots_pending`: capacidade conhecida, mas taxa indisponível;
- `unrated`: capacidade oficial desconhecida e taxa indisponível.

Um grupo `standard` pode ter um ou vários códigos; portanto, não é necessária
uma política separada para grupos compartilhados. Leitos-dia sem código atual
ficam documentados na proveniência, mas não ganham política ou linha artificial
no catálogo, seguindo YAGNI.

### 4. Configuração inicial

A versão inicial contém 42 definições: 39 grupos com capacidade e três grupos
`unrated`. Os 39 grupos cobrem 44 códigos e somam capacidade conhecida 658.
A 3A possui capacidade conhecida 32, mas ainda não é calculável. Assim, a
capacidade calculável inicial é 626 e cobre 43 dos 47 códigos observados.

| Chave | Cap. | Política | Código(s) |
| --- | ---: | --- | --- |
| CHD | 13 | standard | 728 |
| GASTRO | 12 | standard | 2702 |
| UAVC | 14 | standard | 637 |
| UTI-CARDIO | 28 | standard | 628 |
| UTI-CIR | 10 | standard | 630 |
| UTI-G1 | 20 | standard | 633 |
| UTI-G2 | 9 | standard | 634 |
| UTI-NEURO | 10 | standard | 629 |
| UTI-PED | 16 | standard | 631 |
| UTI-NEO | 17 | standard | 636 |
| UTI-ONCO | 5 | standard | 1926 |
| UCINCA | 10 | standard | 655 |
| UCINCO | 23 | standard | 635 |
| INT-B | 30 | standard | 720 |
| INT-C | 30 | standard | 721 |
| ENF-1A | 36 | standard | 640 |
| ENF-1B | 30 | standard | 642 |
| ENF-1C | 30 | standard | 644 |
| ENF-2A-HEMA | 20 | standard | 643 |
| ENF-2A-ISO | 6 | standard | 2155 |
| ENF-2B-CARD | 15 | standard | 719, 2156 |
| ENF-2B-NEURO | 24 | standard | 651 |
| ENF-2C-CLIN | 28 | standard | 652 |
| ENF-2C-ENDO | 6 | standard | 2158 |
| OBST-3A | 32 | linked_slots_pending | 654 |
| OBST-3B | 28 | standard | 653 |
| ENF-4A | 14 | standard | 656 |
| ENF-4B | 30 | standard | 658 |
| ENF-4C | 45 | standard | 659 |
| EM-ADULTO-AMAR | 13 | standard | 731 |
| EM-ADULTO-LAR | 16 | standard | 745 |
| EM-ADULTO-VERM | 3 | standard | 729 |
| EM-ADULTO-PROC | 2 | standard | 751 |
| EM-ADULTO-OBS | 1 | standard | 954 |
| EM-PED-AMAR | 15 | standard | 738 |
| EM-PED-LAR | 4 | standard | 1004 |
| EM-PED-VERM | 3 | standard | 732 |
| EM-PED-OBS | 2 | standard | 747 |
| CO | 8 | standard | 20, 1110, 1112, 1114, 1116 |
| UNRATED-CRPA-HGRS | - | unrated | 733 |
| UNRATED-CRPA-HOMEM | - | unrated | 1522 |
| UNRATED-MED-PED | - | unrated | 1002 |

A capacidade 658 é derivada de 685 da planilha, mais uma correção da Emergência
Pediátrica, menos 20 leitos-dia, menos 16 berços vinculados sem capacidade
adicional e mais 8 posições do Centro Obstétrico.

### 5. Materializar uma medição imutável por execução de censo

Estrutura conceitual:

```text
OccupancyMeasurement
  census_run -> IngestionRun (one-to-one, PROTECT)
  catalog -> CapacityCatalogVersion (PROTECT)
  captured_at
  local_date
  algorithm_version
  observed_sector_count
  capacity_covered_sector_count
  calculable_sector_count
  known_capacity
  calculable_capacity
  occupied_for_rate
  occupancy_percentage
  exceeded_by

OccupancyGroupMeasurement
  measurement -> OccupancyMeasurement
  stable_key
  display_name
  calculation_policy
  calculation_status
  official_capacity
  occupied_count
  occupancy_percentage
  exceeded_by
  status_counts_json
  components_json
```

`algorithm_version` começa como `occupancy-v1`. Os filhos copiam chaves, nomes,
capacidade, política, contagens e códigos usados. Consultas históricas nunca
dependerão do nome ou da capacidade atual do catálogo.

A chave idempotente é o `IngestionRun` do censo. A criação do pai, filhos e
resumo ocorre em transação. Uma nova chamada para o mesmo run retorna a medição
existente, sem recalcular com catálogo ou algoritmo mais novo.

O comando de recuperação explícita é:

```text
materialize_occupancy_measurement --run-id <id>
```

Ele não varre censos e não faz backfill. Um run cuja data seja anterior à
primeira versão aplicável retorna estado `pre_activation` sem criar medição.

### 6. Contar somente status ocupado e preservar os demais estados

O numerador usa exclusivamente `BedStatus.OCCUPIED`, como o ADC existente.
Vagos, reservados, manutenção e isolamento são armazenados em contadores
agregados para apresentação, mas não entram no numerador.

Para grupo `standard`:

```text
numerador = soma de ocupados em todos os códigos membros
percentual_exato = numerador / capacidade * 100
excedente = max(numerador - capacidade, 0)
```

Percentuais persistidos são `Decimal`, arredondados para duas casas com
`ROUND_HALF_UP`. O percentual não é limitado a 100%.

Para o Centro Obstétrico, todos os registros ocupados nos códigos `20`, `1110`,
`1112`, `1114` e `1116` entram no numerador. Não há desconto por ausência de
evolução. Por exemplo, 54 ocupados sobre capacidade 8 produzem 675,00%.

Para Cardiologia, `719` e `2156` compartilham uma única capacidade 15.

### 7. Separar capacidade conhecida de lotação calculável

A medição hospitalar expõe duas coberturas, ambas calculadas sobre os códigos de
setor distintos observados no censo:

```text
cobertura de capacidade = códigos observados associados a capacidade não nula
cobertura calculável = códigos observados em grupos standard
```

Na configuração inicial e com os 47 códigos atuais:

- capacidade: 44 de 47;
- cálculo: 43 de 47;
- capacidade conhecida: 658;
- capacidade calculável: 626.

A taxa hospitalar soma somente numeradores e capacidades de grupos `standard`.
A 3A é excluída dos dois lados da taxa, embora sua capacidade 32 permaneça
visível. Grupos `unrated` também ficam fora dos dois lados.

### 8. Tratar código desconhecido e divergência de nome sem bloquear o censo

Um código observado sem membro no catálogo gera detalhe sintético com estado
`unmapped`, capacidade e percentual nulos. Ele permanece visível e reduz ambas
as coberturas. Código vazio usa o nome do setor observado como identidade de
fallback apenas para apresentação e também fica `unmapped`.

O mapeamento usa o código, não o texto do nome. Quando o nome observado divergir
do nome configurado, a medição registra `source_name_mismatch=true` nos
componentes, mas não altera automaticamente identidade, grupo ou capacidade.
Uma mudança oficial exige nova versão futura do catálogo.

Essa escolha mantém o fluxo clínico disponível diante de setor novo, sem
aplicar silenciosamente uma capacidade antiga a outro código. O gate de
completude continua responsável por rejeitar extrações parciais.

### 9. Integrar após a validação de completude e antes dos efeitos clínicos

`process_census_snapshot(run_id=...)` deve chamar a materialização depois de
selecionar e validar o conjunto completo do run e antes de criar
`CensusExecutionBatch` ou enfileirar pacientes.

Fluxo desejado:

```text
snapshot selecionado
  -> gate de completude GCEC-S2
  -> materialização idempotente de ocupação
  -> processamento e enfileiramento clínico existente
```

Isso também cria medição para um censo completo com zero pacientes ocupados e
impede efeitos clínicos parciais se uma configuração válida falhar por erro
interno. Antes da primeira vigência, a materialização retorna `pre_activation`
e o processamento clínico continua inalterado.

Capacidade ausente, setor desconhecido e nome divergente são estados válidos,
não exceções. Erro estrutural do catálogo ou de persistência é falha explícita
e deve ocorrer antes da criação do batch clínico.

O caminho legado sem `run_id` usa o run único associado ao último
`captured_at`. Se os snapshots não possuírem um único run identificável, o
processamento clínico legado continua, mas a estatística retorna
`missing_provenance` e não é criada. Não se usa `captured_at` como substituto da
chave idempotente.

### 10. Persistir resumo diário incremental e determinístico

Estrutura conceitual:

```text
DailyOccupancySummary
  local_date (unique)
  catalog -> CapacityCatalogVersion (PROTECT)
  algorithm_version
  measurement_count
  first_captured_at
  last_captured_at
  known_capacity
  calculable_capacity
  mean_occupied
  min_occupied
  max_occupied
  mean_percentage
  min_percentage
  max_percentage
  max_exceeded_by
  coverage fields

DailyGroupOccupancySummary
  daily_summary -> DailyOccupancySummary
  stable_key
  resolved name, policy and capacity
  measurement_count
  first/last captured_at
  mean/min/max occupied
  mean/min/max percentage
  max_exceeded_by
```

Após inserir uma nova medição, o serviço recompõe por consulta somente o dia
local correspondente e faz upsert do resumo. Isso permite que um censo aceito e
processado com atraso complete seu dia sem scheduler adicional.

Cada censo tem peso igual. A média usa os numeradores exatos de todas as
medições e só arredonda o resultado final para duas casas. Grupos não
calculáveis mantêm contagem e ocupação bruta, mas campos percentuais nulos.

Reexecutar um run existente não modifica resumo. Alterações futuras de catálogo
não recalculam medições nem resumos. Não existe comando de rebuild retroativo
neste change.

### 11. Usar a medição exata na página `/beds`

A view continua selecionando o censo mais recente. Quando esse conjunto possuir
um único `IngestionRun` e sua medição, a página apresenta uma linha por grupo da
medição; grupos compartilhados aparecem uma vez e os leitos dos códigos membros
ficam dentro da expansão.

A página mostra:

- rótulo `Lotação registrada no sistema legado`;
- ocupados, estados observados, capacidade, percentual e excedente;
- alerta textual e visual para percentual acima de 100%;
- `44 de 47 setores com capacidade cadastrada`, conforme a medição;
- `43 de 47 setores com lotação calculável`, conforme a medição;
- 3A com capacidade 32 e cálculo pendente dos pares cama-berço;
- setores `unrated` ou `unmapped` com capacidade não cadastrada;
- data/hora do censo e data efetiva da configuração.

Se a medição exata não existir, a página preserva a tabela atual por setor e
mostra estatística de capacidade como indisponível ou pendente. Nunca reutiliza
uma medição anterior e nunca calcula ad hoc na view.

Autenticação e visualização nominal já existentes permanecem inalteradas. As
regras de negócio ficam no serviço de domínio, não na view ou no template.

### 12. Não criar dependência externa nem novo processo operacional

Todo cálculo usa ORM/PostgreSQL dentro do app `census`. O volume típico é cerca
de 862 linhas por censo, pequeno para agregação determinística. Índices e
constraints cobrem run, data local, catálogo e chaves dos filhos.

Não haverá job contínuo novo. O comando manual serve ativação e recuperação; o
fluxo normal aproveita `process_census_snapshot` já orquestrado pelo systemd
existente.

## Risks / Trade-offs

- **Pares da 3A desconhecidos** → expor capacidade 32, mas manter taxa nula e
  excluir numerador e denominador até change futuro com os pares.
- **Taxa hospitalar parcial parecer completa** → mostrar separadamente cobertura
  de capacidade e cobertura calculável, com contagens observadas.
- **Pacientes fantasmas elevarem artificialmente a taxa** → rotular a métrica
  como registrada no legado e manter o relatório de suspeitos separado; não
  inventar alta clínica.
- **Código mudar de significado sem aviso** → registrar divergência de nome e
  exigir publicação futura; não remapear automaticamente.
- **Configuração incorreta contaminar medições futuras** → validação integral,
  dry-run, hash, data futura e transação antes da ativação.
- **Snapshot incompleto gerar indicador oficial** → bloquear a integração até
  GCEC-S2 e testar que o gate ocorre antes da materialização.
- **Concorrência duplicar uma medição** → constraint one-to-one por run e
  transação atômica.
- **Falha da medição bloquear processamento clínico** → somente falhas
  estruturais bloqueiam e acontecem antes de efeitos clínicos; estados
  desconhecidos ou sem capacidade são resultados válidos.
- **Modelagem adicionar tabelas e custo de manutenção** → manter políticas
  mínimas, fotografias pequenas e nenhuma infraestrutura adicional.
- **Rollback destrutivo apagar auditoria** → migrations aditivas e rollback
  funcional sem remoção das tabelas materializadas.

## Migration Plan

1. Concluir pelo menos GCEC-S2 e validar a defesa de snapshots completos.
2. Aplicar migrations aditivas do catálogo, medições e resumos sem ativar
   cálculo.
3. Validar o JSON inicial com `--dry-run`.
4. Publicar o catálogo para uma data posterior ao dia do deploy.
5. Confirmar que censos anteriores à data continuam sem medição.
6. No primeiro censo completo da data efetiva, confirmar medição, resumo e
   coberturas 44/47 e 43/47 quando os 47 códigos esperados forem observados.
7. Habilitar a apresentação enriquecida em `/beds`, que possui fallback quando
   não houver medição exata.
8. Monitorar códigos `unmapped`, divergências de nome e percentuais extremos.

Rollback funcional:

- interromper a chamada automática de materialização e reverter a apresentação
  para o fallback atual;
- preservar tabelas, versões e medições já criadas para auditoria;
- publicar correção somente com nova versão futura, sem editar o passado.

## Open Questions

Não há questão bloqueante para os quatro slices planejados. Permanecem como
trabalho futuro:

- obter os 16 pares cama-berço da Obstetrícia 3A;
- decidir se leitos-dia terão indicador próprio;
- criar UI histórica para as medições e resumos persistidos;
- substituir o limiar fixo de completude por catálogo esperado de setores.

A pendência de criar o ADR de catálogo temporal e materialização imutável foi
atendida: ver
[ADR-0003](../../../docs/adr/ADR-0003-catalogo-temporal-capacidade-materializacao-imutavel.md).
