# ADR-0003 — Catálogo temporal de capacidade e materialização imutável de ocupação

## Status

Accepted

## Contexto

O SIRHOSP apresentava em `/beds` as contagens cruas do censo mais recente, mas
não possuía capacidade oficial por setor, percentual de lotação nem histórico
auditável das medições. A diretoria forneceu capacidades oficiais via planilha
administrativa e a produção já demonstrou que identidade, nome e agrupamento de
setores mudam ao longo do tempo — o código `2155` mudou historicamente de 2A
Gastro para 2A Clínica Isolamento, por exemplo.

Calcular indicadores históricos com a configuração vigente do momento da
consulta reescreveria o significado do passado: um percentual de lotação de um
censo antigo passaria a ser calculado com grupos, nomes e capacidades atuais,
produzindo indicadores incorretos e apagando o contexto usado em cada cálculo
original.

O censo legado também contém estados administrativos que devem ser
representados exatamente como registrados: pacientes suspeitos de permanência
indevida continuam marcados como ocupados no sistema fonte, setores sem
capacidade cadastrada seguem visíveis e a Obstetrícia 3A tem capacidade oficial
32, mas sua lotação não é calculável enquanto os 16 pares cama-berço forem
desconhecidos. A estatística não pode transformar ausência de evolução em alta
presumida nem inventar capacidade.

A fase 1 do projeto opera um monólito modular Django com PostgreSQL e jobs
coordenados no próprio banco (ADR-0001), sem Celery/Redis. O change
`add-versioned-sector-capacity-occupancy-history` que introduziu esta
funcionalidade é classificado como CRITICAL/HIGH-ARCH — introduz modelos
temporais, migrations e indicadores hospitalares auditáveis — e, por isso,
exige rastreabilidade completa entre decisão, especificação e implementação.

## Decisão

Adotar as seguintes decisões para o histórico de capacidade e ocupação:

- **Catálogo publicado como fotografia completa versionada**: cada publicação
  cria uma versão integral de grupos, códigos fonte, nomes configurados e
  capacidades; nunca uma edição parcial de versões anteriores.
- **Vigência diária em `America/Bahia`, iniciando somente em data futura**: a
  ativação exige `effective-from` estritamente posterior ao dia corrente, no
  formato `YYYY-MM-DD`, por comando controlado, idempotente por data/hash e com
  `--dry-run` que não persiste nada.
- **Mudanças começam à meia-noite do dia seguinte ou em data futura aprovada**:
  uma configuração vale para o dia local inteiro; nenhum censo combina grupos
  de versões diferentes.
- **Sem backfill de censos anteriores à ativação**: censos cuja data local
  precede a primeira versão aplicável recebem estado `pre_activation` e nunca
  geram medição; o passado não é recalculado.
- **Uma medição imutável por `IngestionRun` de censo aceito**: a chave de
  idempotência é o run do censo (one-to-one com `PROTECT`), não o
  `captured_at`; repetir a materialização retorna a medição existente sem
  recalcular com catálogo novo.
- **Filhos copiam o contexto resolvido**: cada grupo medido persiste chave
  estável, nome, política, capacidade, códigos componentes, contagens por
  status e versão do algoritmo usados naquele momento; consultas históricas
  nunca dependem do catálogo atual.
- **Algoritmo inicial `occupancy-v1`**: a versão do algoritmo é gravada na
  medição e nos resumos; mudanças de fórmula exigem versão nova e não
  reescrevem medições existentes.
- **Resumo diário derivado de medições imutáveis com peso aritmético igual**:
  cada censo do dia conta uma observação; médias usam numeradores exatos e só
  o resultado final é arredondado com `Decimal` e `ROUND_HALF_UP`; sem
  ponderação temporal, interpolação ou scheduler.
- **PostgreSQL garante unicidade, constraints e coordenação transacional**:
  medição, filhos e resumo diário são persistidos na mesma transação;
  constraints impedem duplicidade por run, por data local e por grupo;
  corridas concorrentes são resolvidas por locks e recuperação por hash.
- **Estados não calculáveis permanecem explícitos e não bloqueiam**: setores
  desconhecidos (`unmapped`), sem capacidade (`unrated`), pendentes de pares
  (`linked_slots_pending`) e divergências de nome são resultados válidos,
  visíveis na medição e na interface, e nunca interrompem o processamento
  clínico do censo.
- **3A fica sem taxa enquanto os pares cama-berço forem desconhecidos**:
  capacidade 32 é exibida e excluída simetricamente do numerador e do
  denominador da taxa hospitalar; nenhum percentual aproximado é calculado.
- **Somente agregados seguros entram no histórico**: as novas tabelas armazenam
  identificadores de setor, contagens e metadados de cálculo — nunca nomes de
  pacientes, prontuários ou texto clínico.
- **Mudança futura requer nova versão diária futura, nunca edição retroativa**:
  o comando de ativação não altera nem remove versões publicadas; correções
  afetam apenas o futuro.
- **Rollback funcional preserva o histórico**: desativar a integração e a UI
  enriquecida não apaga versões, medições ou resumos já materializados, que
  permanecem como evidência de auditoria.

## Alternativas Consideradas

1. **Configuração única mutável** (tabela editável de setores/capacidades)
   - Vantagens: menos tabelas; alteração imediata pelo Django Admin.
   - Desvantagens: qualquer edição reescreve retroativamente o significado de
     todas as medições e resumos; impossível auditar qual configuração valeu em
     cada data; vigências inconsistentes entre linhas.
   - Motivo da rejeição: viola o requisito de histórico reproduzível e permite
     quebrar imutabilidade sem validação atômica.

2. **Cálculo sob demanda usando o catálogo atual**
   - Vantagens: sem tabelas de medição; percentual sempre "atualizado".
   - Desvantagens: o indicador de um censo antigo muda silenciosamente quando a
     configuração muda; impossível reproduzir o número apresentado ontem;
     recálculo repetido de ~862 linhas por consulta.
   - Motivo da rejeição: indicadores hospitalares auditáveis exigem que o
     valor exibido em uma data permaneça igual para sempre.

3. **Vigência independente por linha/campo** (intervalos por setor em vez de
   snapshot integral)
   - Vantagens: menor duplicação de dados entre versões.
   - Desvantagens: combinações temporais inválidas (setor em versão A com
     membro em versão B); seleção por data exige junção de muitos intervalos;
     auditoria e rollback mais frágeis.
   - Motivo da rejeição: a fotografia completa elimina estados inconsistentes
     e garante uma única configuração por dia; a duplicação de ~42 grupos por
     publicação é custo pequeno e aceitável.

4. **Backfill dos censos históricos após a primeira ativação**
   - Vantagens: série histórica completa desde o início da extração.
   - Desvantagens: aplicaria capacidades aprovadas em 2026 a censos capturados
     sob outra realidade operacional; reescreveria o passado com a configuração
     de hoje, exatamente o que a decisão evita; risco de decisão clínica ou
     gerencial baseada em números fabricados.
   - Motivo da rejeição: a linha de base oficial começa na primeira data de
     vigência; o histórico anterior permanece apenas como contagens cruas.

5. **Scheduler/infraestrutura assíncrona adicional** (Celery/Redis ou timer
   dedicado para materialização e resumos)
   - Vantagens: processamento desacoplado do fluxo do censo.
   - Desvantagens: contraria a ADR-0001 para a fase 1; mais serviços para
     operar; janela de inconsistência entre censo aceito e estatística;
     complexidade desproporcional ao volume (~1 censo por ciclo).
   - Motivo da rejeição: a materialização síncrona, transacional, após o gate
     de completude GCEC e antes dos efeitos clínicos, mantém consistência sem
     novo runtime.

## Consequências

### Positivas

- Histórico de ocupação reproduzível e auditável: cada medição preserva
  catálogo, algoritmo e valores resolvidos usados no cálculo.
- Indicadores estáveis: o percentual exibido em uma data não muda quando o
  catálogo ou o algoritmo evoluem.
- Extremos do legado permanecem visíveis: sobre-lotação (por exemplo, CO com
  54/8 = 675,00%) e estados não calculáveis são representados como
  registrados, sem ajuste silencioso.
- Operação simples: ativação e recuperação por management commands; resumo
  diário síncrono sem scheduler, dentro do fluxo já orquestrado pelo systemd.
- Privacidade por construção: as tabelas novas contêm somente agregados de
  setor, sem identificadores clínicos.
- Consistência transacional: censo incompleto nunca gera medição (gate GCEC);
  falha estrutural ocorre antes de qualquer efeito clínico.

### Negativas / Trade-offs

- Maior número de tabelas e snapshots: cinco modelos novos (versão, grupo,
  membro, medição, medição de grupo) mais dois de resumo diário.
- Necessidade de publicação operacional controlada: toda mudança de capacidade
  exige fotografia completa futura e aprovação explícita — mais cerimônia que
  editar uma tabela.
- Catálogo incorreto afeta o futuro: um erro na configuração só pode ser
  corrigido publicando versão nova para data futura; medições já criadas com o
  erro permanecem (corrigíveis apenas por decisão futura documentada).
- 3A e setores sem capacidade reduzem a cobertura calculável: a taxa
  hospitalar cobre 43 de 47 setores e capacidade calculável 626 de 658 na
  configuração inicial.
- Dependência da completude GCEC: a integração automática exige a defesa em
  profundidade do change arquivado
  `guard-census-extraction-completeness` (mínimo de 40 setores distintos).
- Custo de monitoramento contínuo: códigos `unmapped` e divergências de nome
  precisam acompanhamento operacional para não degradar a cobertura.

### Riscos e Mitigações

- **Catálogo incorreto contaminar medições futuras**: validação integral do
  documento antes da escrita, dry-run, SHA-256 do documento, data
  estritamente futura e transação atômica.
- **Código mudar de significado sem aviso**: mapeamento por código com
  registro de `source_name_mismatch` por componente; nenhuma remapeação
  automática; mudança oficial exige nova versão futura.
- **Corrida concorrente duplicar medição ou versão**: one-to-one por run com
  `select_for_update`, unicidade de data efetiva e recuperação de corrida por
  comparação de hash; resumo diário por `update_or_create` sobre data local
  única (corrida teórica residual apenas recomputa o mesmo dia, sem corrupção).
- **Rollback destrutivo apagar auditoria**: migrations aditivas 0014-0017 e
  rollback funcional que desativa integração/UI sem remover tabelas ou dados
  materializados.
- **Extremos serem confundidos com erro de cálculo**: rótulo explícito
  `Lotação registrada no sistema legado`, alerta textual e visual acima de
  100% e exibição do excedente absoluto sem limitar o percentual.

## Artefatos decorrentes

- Modelos Django: `CapacityCatalogVersion`, `CapacityGroupDefinition`,
  `CapacitySectorMembership`, `OccupancyMeasurement`,
  `OccupancyGroupMeasurement`, `DailyOccupancySummary`,
  `DailyGroupOccupancySummary`.
- Migrations aditivas `0014`-`0017` em `apps/census/migrations/` (a `0015`
  apenas corrige a constraint política-capacidade da `0014`, sem tocar dados).
- Serviço de materialização e resumo: `apps/census/occupancy.py`
  (`occupancy-v1`, `materialize_occupancy_measurement`,
  `refresh_daily_occupancy_summary`, `resolve_exact_measurement`).
- Comandos: `activate_sector_capacity_catalog` (ativação controlada) e
  `materialize_occupancy_measurement --run-id` (recuperação explícita de um
  único run).
- Configuração inicial sintética:
  `apps/census/data/initial_sector_capacity_catalog.json` (42 grupos, 47
  códigos, capacidade conhecida 658, calculável 626).

## Referências

- Change OpenSpec:
  `openspec/changes/add-versioned-sector-capacity-occupancy-history/`
  (`proposal.md`, `design.md`, `specs/`, `tasks.md`).
- Change arquivado (dependência de completude):
  `openspec/changes/archive/2026-08-16-guard-census-extraction-completeness/`.
- Implementação: `apps/census/models.py`, `apps/census/capacity_catalog.py`,
  `apps/census/occupancy.py`, `apps/census/services.py`,
  `apps/census/migrations/0014`-`0017`.
- ADR-0001 — monólito Django com PostgreSQL e jobs agendados, sem
  Celery/Redis na fase 1.
