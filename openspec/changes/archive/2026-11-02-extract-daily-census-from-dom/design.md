# Design

## Context

Motivação e escopo: `proposal.md`. Este documento propõe decisões para revisão;
a criação dos artefatos não aprova nem inicia a implementação.

### Estado observado

- `automation/source_system/current_inpatients/extract_census.py` autentica com
  `bootstrap_legacy_session`, usa o proxy central e descobre/seleciona setores.
  Hoje exporta XLSX por setor, aplica `parse_setor_xlsx` e escreve CSV/JSON.
- `apps/census/management/commands/extract_census.py` executa esse subprocesso
  em `TemporaryDirectory`, lê o CSV, aplica o mínimo de 40 setores e persiste
  snapshots. Hoje o threshold isolado não prova que todos os setores deram certo.
- O contrato real de `parse_setor_xlsx` contém 11 campos da tabela e dois
  metadados, não todos os 14 campos disponíveis na planilha.
- `parse_census_csv` normaliza a data de internação com `_parse_dt_int`;
  `upsert_patient_movements` também espera uma data sem hora. O portal usa os
  campos antigos diretamente, e movimentos têm identidade por data/setor.
- `CensusSnapshot.data_internacao` e `data_movimentacao` são textos de até
  20 caracteres. Armazenar timestamps neles quebraria o significado dos
  consumidores atuais, mesmo cabendo fisicamente no banco.
- O padrão atual é `TIME_ZONE = "America/Bahia"`, com `USE_TZ = True`.

### Evidência e limites

`research/census-dom-xlsx-comparison.md` e
`research/census-dom-production-fields-evidence.json` demonstram paridade em
quatro setores, 124 linhas, página de 100, 103 horários de internação e 124 de
movimentação. A ausência de `Dt Int` não implica perda de hora: há linhas sem
prontuário com rótulos de situação do leito. As contagens são fotografias da
investigação, não constantes do produto ou dados para fixtures.

Os ensaios encontraram inicialização tardia dos tooltips, diferenças entre
variantes de `Alta`, sensibilidade a acentos no autocomplete e falhas
intermitentes de acesso. A releitura foi útil para a investigação, mas não
oferece snapshot transacional da fonte.

## Goals / Non-Goals

**Goals:**

- Alterar o adaptador de origem sem transferir detalhes de Playwright ao domínio.
- Reter precisão adicional sem alterar contratos de data ou identidade clínica.
- Tornar a conclusão de cada setor e do escopo inteiro verificável antes da
  publicação operacional, e não apenas pelo número de setores com linhas.
- Manter CLI, subprocesso, CSV temporário, PostgreSQL e orquestrador existentes.

**Non-Goals:**

- Propagar horas para `Admission`, `PatientMovement` ou Trajetória nesta change.
- Refatorar reconciliação, ocupação, filas ou o controller adaptativo.
- Transformar scripts de laboratório em dependência operacional.
- Implementar um framework de scraping, múltiplos backends ou fallback XLSX.

## Decisions

### D1 — DOM no adaptador existente; transporte continua CSV

A execução normal de `run` passa a ler o DOM, mantendo a localização do script,
flags `--headless`, `--max-setores`, `--output-dir`, bootstrap e proxy existentes.
Uma sessão de browser é reutilizada no ciclo, como hoje. A ponte Django continua
executando o subprocesso; não passa a dirigir Playwright nem importa laboratório.

A leitura de dados de cada página devolve somente os 11 campos selecionados,
não médico/nascimento/transferência ou HTML completo. Extração e normalização
ficam em funções pequenas e testáveis do adaptador, em módulo de produção
próximo somente se necessário. Não há função genérica de extração de tabelas.

O command usa `--csv-only`, já existente, evitando cópia JSON redundante dos
dados clínicos. Um nome canônico `censo-*.csv` é publicado no diretório de
saída somente após os setores selecionados terminarem sem falhas. A escrita
usa arquivo temporário e substituição final; artefatos intermediários nunca
são confundidos com resultado pronto. O command não escolhe arbitrariamente
entre vários CSVs ou resumos candidatos.

**Alternativas:** importar Playwright no command ampliaria o acoplamento;
manter XLSX como fallback ocultaria perda de precisão; mudar para uma API
interna não documentada exigiria nova investigação. Todas foram descartadas.
O parser/exportador XLSX pode permanecer como referência de laboratório ou de
regressão, mas não é chamado na execução operacional DOM.

### D2 — Identidade do setor e mapeamento semântico são explícitos

A descoberta usa a coleção completa de rótulos nativos, inclusive scroll
limitado do dropdown. A identidade de seleção combina código e descrição
normalizada, sem colapsar unidades distintas com código compartilhado.
A seleção preserva a grafia nativa; não depende dos nomes digitados na conversa.
O código e a descrição efetivamente selecionados são conferidos antes de ler
as linhas. Match ausente ou ambíguo é erro, não escolha silenciosa do primeiro item.

Cabeçalhos são normalizados para mapear os campos, sem índices globais fixos.
Para `Alta` e `Origem`, a ocorrência correspondente à exportação foi a primeira
na estrutura observada, inclusive quando oculta; as variantes posteriores são
apresentação, não novos campos. Essa regra fica explícita no adaptador e nas
fixtures sintéticas. Mudança estrutural que impeça reconhecê-la falha em vez de
escolher a coluna visível. A ordem de colunas não relacionadas pode mudar.

Prontuário, idade, tempo e alta mantêm as normalizações caracterizadas contra o
parser XLSX real. Formatos de idade em meses/dias não são convertidos em números
sem unidade. O domínio continua classificando faixas etárias e leitos.

Linhas com prontuário vazio e nome/situação preenchido são preservadas. Quando
ambos são vazios, aplica-se a mesma omissão do parser XLSX, contabilizada à
parte. Não se filtra por presença de paciente. Não se deduplicam linhas clínicas
por leito ou prontuário: conflitos de posição continuam na camada de ocupação.

### D3 — Tooltips são dados associados à célula, não texto global de hover

Os alvos dos widgets PrimeFaces vinculam o tooltip à célula ou descendente.
Seu elemento de conteúdo, resolvido pelo id do widget ou elemento associado,
é lido diretamente. Não se usa o tooltip global atualmente visível nem o
horário observado em outra linha. Valores de atributos locais podem ser lidos
quando pertencem inequivocamente à mesma célula, sem um segundo backend.

Após pesquisa, troca de tamanho ou página, primeiro se confirma resultado
atualizado/AJAX concluído com as helpers existentes. Depois se permite até
**10 segundos** para os tooltips das datas preenchidas inicializarem, com
polling limitado. Zero/um candidato válido para uma célula vazia/preenchida é
tratado segundo a precisão real; múltiplos timestamps distintos, calendário
inválido ou desacordo de data são erro. Célula genuinamente vazia continua vazia.
Uma data visível cujo tooltip não fica pronto causa erro de setor, não fallback
para data sem hora. Os formatos aceitos são explícitos, sem parsing permissivo.

A mesma regra vale para `Dt Int` e `Dt Mvt`. O coletor não transforma datas
sem hora em `00:00`, não usa `captured_at`/`first_seen_at` e não atribui a um
paciente o horário de uma linha sem prontuário.

**Alternativa descartada:** simular hover por célula é mais lento e torna a
associação ao tooltip global mais frágil. O vínculo local foi demonstrado no
laboratório; a implementação deve reproduzi-lo com fixtures próprias.

### D4 — Página longa não substitui prova de término

Selecionar a opção nativa 100; se só houver opções maiores, usar a menor delas.
Confirmar o valor aplicado e o início na primeira página. A ausência de opção
compatível é erro estrutural explícito. Após nova pesquisa, confirmar de novo
o tamanho, pois a fonte pode restaurar o padrão.

Percorrer todas as páginas até o controle de próxima página estar explicitamente
desabilitado. Cada avanço deve demonstrar página nova e resultado estabilizado.
Repetição de marcador/página, timeout, estrutura desconhecida, falta de estado
terminal ou limite de **50 páginas** excedido rejeitam o setor. A leitura de
uma página preserva todas as linhas elegíveis, sem teto de 100 no acumulador.

Se um total nativo confiável estiver disponível, confrontá-lo com as linhas
físicas lidas, incluindo as omitidas pela regra de identidade vazia. A
investigação não obteve esse total pela configuração do widget; portanto, sua
existência não é presumida. Na ausência dele, registrar essa limitação e usar
página aplicada, sequência, término explícito e resumo do escopo como provas
estruturais. Não apresentar a contagem extraída como um total independente.

### D5 — Resumo agregado fecha o gate entre coletor e persistência

Adicionar um único `censo-extraction-summary.json` versionado, sem linhas
clínicas, ao mesmo diretório temporário do CSV. A versão 1 declara apenas:

- versão do resumo;
- setores descobertos, selecionados, processados, vazios e com erro;
- linhas lidas, linhas omitidas por ambas as identidades vazias e linhas emitidas;
- páginas processadas, limitação explícita de escopo e conclusão do escopo.

O adaptador só declara conclusão quando cada setor solicitado chegou a resultado
terminal válido. A soma de setores processados inclui os vazios. Erros após o
limite de retry já existente resultam em exit não zero e nenhum CSV canônico
de sucesso. Resumos de falha, se produzidos, contêm apenas contadores seguros.

`--max-setores` continua útil para diagnóstico. Se limitar a descoberta, o
resumo marca escopo limitado: o resultado pode representar a coleta diagnóstica
solicitada, mas nunca é elegível a um censo operacional integral, mesmo com 40
setores de dados. Não se fabricam linhas para setores vazios.

O command valida o schema do resumo, tipos, limites, equações dos contadores,
escopo não limitado, conclusão, erros zero, row count do CSV e o threshold
existente de **40 setores distintos com linhas**. Não troca esse threshold
por número de setores vazios descobertos. Ausência, ambiguidade de artefatos,
resumo parcial ou CSV inválido impedem qualquer `bulk_create` de snapshots.
Exit zero não basta.

Somente campos permitidos do resumo entram em stage metrics, nunca o JSON
arbitrário ou stdout bruto. A escrita dos snapshots e a promoção do run a aceito
ocorrem em uma transação curta após a validação; uma falha nessa publicação
reverte o novo conjunto. Rejeição mantém o último censo aceito e não chega a processamento,
materialização de ocupação, observação de ausência ou filas de pacientes.
As verificações já existentes no processamento por run permanecem ativas.

**Alternativa descartada:** elevar apenas o threshold de setores não detecta
um setor faltante quando outros 40 deram certo. O resumo é o menor contrato
local reproduzível para impor a conclusão integral, sem serviço adicional.

### D6 — Duas precisões coexistem sem alterar o domínio clínico

O CSV mantém as 13 colunas. `dt_int` e `dt_mvt` transportam
`DD/MM/AAAA HH:MM` quando conhecidos, ou vazio quando ausentes. O parser de
entrada aceita também datas legadas para testes, compatibilidade e leitura de
artefatos antigos; isso não reintroduz XLSX como execução operacional atual.
O contrato DOM deve ser validado antes de publicar o CSV de nova execução.

Propor dois campos em `CensusSnapshot`:

| Campo novo            | Tipo                                   | Default |
| --------------------- | -------------------------------------- | ------- |
| `source_admission_at` | `DateTimeField(null=True, blank=True)` | `None`  |
| `source_movement_at`  | `DateTimeField(null=True, blank=True)` | `None`  |

Uma transformação explícita do parser separa precisão e projeção:

- Timestamp completo: validar estritamente, interpretar na timezone local
  configurada do hospital e produzir datetime aware para o campo novo.
- `data_internacao`: continuar entregando a data local normalizada
  `DD/MM/AAAA`, como hoje.
- `data_movimentacao`: continuar entregando somente a componente de data;
  timestamps novos projetam `DD/MM/AAAA`, e datas legadas mantêm suporte aos
  formatos aceitos atualmente.
- Data legada sem hora: preservar seu processamento e deixar o novo campo null.
- Valor ausente: texto vazio no campo antigo e null no campo novo.
- Timestamp completo inválido: rejeitar a entrada antes de escrita parcial,
  com motivo sanitizado. Não mascará-lo como data legada ou vazio.

A timezone é `settings.TIME_ZONE`, atualmente `America/Bahia`, não a timezone do
host nem uma inferência baseada no horário da coleta. A migração é apenas
aditiva, sem índices novos ou backfill. As colunas existentes mantêm significado.

O command passa os dois valores opcionais ao persistir o snapshot. Não os usa
para atualizar `Admission.admission_date`, identidade de reconciliação,
`PatientMovement`, ordenação, duração ou UI. Movimentos continuam consumindo a
projeção de data, inclusive repetição idempotente no mesmo dia/setor. A
Trajetória com hora depende de change posterior com vínculo, precisão e
compatibilidade próprios; esta change só disponibiliza a evidência na origem.

**Alternativas descartadas:** colocar timestamp nos textos antigos alteraria
consumidores e telas; descartar a hora após scraping perderia a motivação;
reescrever os modelos clínicos ampliaria a mudança além da troca de extração.

### D7 — Segurança e verification são parte do contrato

No caminho normal, não chamar `save_debug`, nem persistir screenshots, traces,
HTML, browser storage ou cópias JSON clínicas em falhas. Exceções do browser e
valores inválidos são reduzidos a motivos fixos e contadores, sem mensagens
arbitrárias que possam carregar dados clínicos. Credenciais vêm das variáveis
existentes, sem valores no código, command line ou artefatos OpenSpec.

Os scripts exploratórios e os relatórios já produzidos não são implementação
aprovada. Reaproveitar conhecimento, não importar `automation/lab` em produção.
Fixtures, HTML, planilhas de referência e traces de testes devem ser sintéticos.
Os arquivos ainda não rastreados da investigação permanecem trabalho prévio;
não são alterados, apagados ou implicitamente incluídos por este planejamento.

A verificação obrigatória da implementação será local/sintética, usando o
coletor operacional com a superfície de censo em uma página fixture, não apenas
reexecutando o probe de laboratório. Deve exercitar os 11 campos, ambos os
horários, atraso de inicialização, leitos sem paciente, mais de 100 linhas,
variantes ocultas e erro de um setor após 40 sucessos. A paridade com o parser
XLSX real usa workbook sintético. Persistência e efeitos por run são provados
separadamente em integração com PostgreSQL.

Nova inspeção hospitalar, se desejada, depende de autorização específica e
produz somente evidência agregada em memória; não integra CI ou gate obrigatório.
A conferência após deploy é de leitura, sem cadastrar pacientes de teste em
produção. Não há promessa de fator de aceleração: os tempos da investigação
excluem login, pesquisa, aplicação de página longa e espera de tooltips.

## Risks / Trade-offs

- [Mudança no DOM legado] → Mapeamento explícito, schema estrito, fixtures de
  variantes e rejeição de estrutura desconhecida; não existe proteção perfeita
  contra toda alteração semântica invisível do sistema fonte.
- [Sessão ou AJAX instável] → Bootstrap e limites existentes, erro de setor
  não publicável, contadores seguros e ciclo seguinte pelo orquestrador atual.
- [Sem total independente no widget] → Verificar sequência e término, usar
  total nativo quando confiável e registrar a limitação, sem inventar certeza.
- [Espera por timestamp aumenta latência] → Polling limitado somente em páginas
  pendentes; a integridade temporal prevalece sobre aceitar uma coleta incompleta.
- [Novas colunas persistem precisão clínica] → Migração opcional aditiva, origem
  rastreável pelo run, sem backfill, sem novos consumidores ou exposição na UI.
- [Maior rigor reduz disponibilidade de censos parciais] → Manter último censo
  aceito e sinalizar falha; não avançar indevidamente ausência/reconciliação.
- [Imagens misturadas não entendem o transporte] → Coletor e command são
  implantados juntos; não compartilhar diretório de handoff entre versões.

## Migration Plan

1. Revisar e aprovar os artefatos, inclusive precisão dos snapshots e exclusão
   da UI; aprovar contratos de slices antes de executar um controller.
2. Implementar a camada de compatibilidade de datas e a migração aditiva,
   mantendo o caminho de datas legadas funcional.
3. Implementar DOM, resumo e validação do command na mesma entrega. Executar
   RED/GREEN, verification sintética e os gates definidos em `tasks.md`.
4. Na janela operacional autorizada, aplicar a migração e implantar uma única
   imagem consistente. Não ativar dois orquestradores para comparar versões.
5. Conferir somente metadados agregados do primeiro ciclo completo: setor,
   paginação, conclusão, row counts, rejeições e persistência opcional. Não
   imprimir pacientes, datas de eventos ou payloads clínicos.
6. Em falha, parar a versão nova e restaurar a imagem anterior que usa XLSX.
   As colunas opcionais ficam no banco: rollback não exige apagar snapshots
   ou reverter a migração. Horários novos ficam sem consumidor no código antigo.
   Não publicar CSV de um extrator de uma versão para command de outra.

Nenhuma migração, implementação ou ação de deploy é executada nesta fase de
planejamento. Não há pergunta material adiada para o worker: as escolhas acima
são a proposta técnica a aprovar, não decisões autorizadas silenciosamente.
