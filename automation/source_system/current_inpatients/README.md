# Current Inpatients Connector

Extrai pacientes internados atualmente de todos os setores do Censo Diário do
sistema fonte diretamente da UI (DOM), sem exportação de planilha.

A exportação XLSX e `parse_setor_xlsx` permanecem no repositório apenas como
referência de laboratório/regressão; a execução operacional não os chama e não
possui fallback automático para planilha.

## Uso

```bash
uv run python automation/source_system/current_inpatients/extract_census.py \
    --headless \
    --csv-only \
    --output-dir downloads/
```

## Aquisição DOM

Para cada setor descoberto no autocomplete nativo:

1. o setor é selecionado por **código + descrição normalizada**; a identidade
   efetivamente selecionada é conferida antes de ler as linhas. Grafia nativa
   com acentos é preservada e códigos compartilhados não são colapsados.
2. a pesquisa é executada e o resultado atualizado/AJAX precisa estabilizar
   antes de qualquer leitura. O tamanho nativo de página **100** é aplicado e
   verificado; se não existir, usa-se a menor opção nativa maior que 100. Nenhuma
   opção compatível rejeita o setor.
3. as colunas são mapeadas semanticamente pelos cabeçalhos, sem índices fixos.
   Para `Alta` e `Origem`, a primeira ocorrência é a variante do contrato de
   exportação, mesmo quando oculta; a variante visível é apenas apresentação.
4. são extraídos exatamente os 11 campos usados pelo sistema (`qrt_leito`,
   `prontuario`, `nome`, `esp`, `dt_int`, `tempo`, `idade`, `convenio`,
   `dt_mvt`, `alta`, `origem`) mais `setor_codigo`/`setor`. Profissional,
   nascimento, transferência e controles visuais não entram no payload.
5. `Dt Int` e `Dt Mvt` usam o tooltip associado à própria célula/descendente
   (alvo do widget PrimeFaces ou atributo local), nunca o tooltip global nem a
   hora de outra linha. Datas preenchidas aguardam até 10 segundos pela
   inicialização; ausência, ambiguidade, calendário inválido ou data divergente
   rejeitam o setor. Data genuinamente vazia permanece vazia e nenhuma
   meia-noite/horário de coleta é inferido.
6. todas as páginas são percorridas até o controle de próxima estar
   explicitamente desabilitado, com prova de avanço e estabilização. Página
   repetida/não avançada, estado terminal desconhecido ou mais de 50 páginas
   rejeitam o setor. O acumulador não tem teto de 100 linhas.
7. quando o paginator expõe um total nativo confiável, ele é confrontado com as
   linhas físicas lidas (incluindo omitidas). Quando não expõe, essa limitação
   fica explícita: a contagem extraída não é apresentada como total independente.

Linhas com prontuário vazio e rótulo de situação (`DESOCUPADO`, `RESERVA`,
`LIMPEZA`, etc.) são preservadas como linhas de leito. Apenas linhas com
prontuário **e** nome/situação vazios são omitidas, conforme o parser
estabelecido, e contadas em `rows_omitted`. Linhas conflitantes de mesma
posição/paciente não são deduplicadas.

## Artefatos do handoff

Em execução completa são publicados, no diretório de saída:

- CSV canônico `censo-todos-pacientes-<timestamp>.csv`, com as 13 colunas
  de transporte já existentes;
- resumo agregado `censo-extraction-summary.json`, versão 1.

O CSV é escrito primeiro em arquivo temporário e só recebe o nome canônico
depois que todo o escopo solicitado termina sem falhas. Execução incompleta não
publica CSV canônico. Artefatos temporários não são deixados no diretório.

O comando Django executa o coletor com `--csv-only`, portanto o caminho
operacional não cria cópia JSON dos dados clínicos. O JSON de linha continua
disponível apenas para uso manual fora do caminho operacional.

## Resumo de completude (versão 1)

O resumo contém somente contadores estruturais, sem nomes, prontuários,
horários, credenciais ou HTML:

| Campo                | Significado                                                      |
| -------------------- | ---------------------------------------------------------------- |
| `summary_version`    | Versão do contrato; atualmente `1`.                              |
| `sectors_discovered` | Setores distintos descobertos no dropdown.                       |
| `sectors_selected`   | Setores efetivamente solicitados após `--max-setores`.           |
| `sectors_processed`  | Setores com resultado terminal, incluindo vazios e falhos.       |
| `sectors_empty`      | Subconjunto processado sem linhas emitidas.                      |
| `sectors_failed`     | Subconjunto processado com erro definitivo.                      |
| `rows_read`          | Linhas físicas lidas; igual a emitidas mais omitidas.            |
| `rows_omitted`       | Linhas omitidas por prontuário e nome/situação ambos vazios.     |
| `rows_emitted`       | Linhas entregues no CSV.                                         |
| `pages_processed`    | Páginas de resultado efetivamente navegadas.                     |
| `scope_limited`      | `true` quando `--max-setores` truncou o escopo descoberto.       |
| `scope_complete`     | `true` quando todos os setores selecionados terminaram sem erro. |

Invariantes: `rows_read = rows_emitted + rows_omitted`,
`sectors_selected <= sectors_discovered`,
`sectors_empty + sectors_failed <= sectors_processed` e
`scope_complete` só é verdadeiro com todos os setores selecionados processados
e zero falhas. Setor vazio válido é sucesso e não inventa linhas.

Na aquisição DOM cada página de resultado efetivamente lida é contada em
`pages_processed`; não é um total presumido. Quando o paginator não expõe um
total nativo confiável, a completude é sustentada por página aplicada, sequência
de páginas, término explícito e contadores do escopo, sem inventar total.

## Falha e escopo limitado

Cada setor tem no máximo duas retentativas. Erro definitivo produz exit code
não zero, grava apenas um resumo de falha com contadores seguros e não publica
CSV canônico. `--max-setores` continua sendo diagnóstico: um recorte limitado
pode ser publicado como resultado diagnóstico, mas o resumo marca
`scope_limited=true` e o comando Django não o aceita como censo operacional
integral, mesmo com 40 setores de dados.

Falhas e retentativas imprimem códigos fixos de motivo (`tooltip_not_ready`,
`tooltip_ambiguous`, `pagination_no_progress`, `page_size_unsupported` etc.),
nunca mensagens arbitrárias do browser ou valores de linha. O caminho normal não
grava screenshots, HTML, traces, storage, dumps clínicos ou cópias JSON dos
dados. `--max-setores` continua sendo diagnóstico e não pode ser promovido a
censo operacional integral.

## Consumo pelo comando

O comando `extract_census` exige exatamente um CSV canônico e exatamente um
resumo no diretório temporário. Não escolhe `csv_files[0]` nem usa fallback
para outro CSV. Antes de qualquer persistência ele valida schema, tipos,
limites, equações, escopo integral, conclusão, falhas zero, contagem de linhas
do CSV e o mínimo existente de 40 setores distintos não vazios. Exit code zero
do subprocesso não é suficiente. Snapshots e promoção do run são publicados na
mesma transação curta; uma falha reverte o conjunto novo e mantém o censo aceito
anterior.

## Precisão temporal de origem

O transporte CSV mantém as mesmas colunas. A aquisição DOM carrega
`DD/MM/AAAA HH:MM` em `dt_int` e `dt_mvt` quando o tooltip da célula existe. O
parser do SIRHOSP valida esse formato estritamente, interpreta o valor em
`TIME_ZONE` (`America/Bahia`) e persiste
`source_admission_at`/`source_movement_at` aware em `CensusSnapshot`, vinculados
ao run de ingestão.

Compatibilidade e limites:

- datas legadas sem hora (`DD/MM` ou `DD/MM/AAAA`) continuam aceitas; os
  campos de origem ficam nulos e nenhuma hora é inferida ou preenchida;
- valores vazios continuam vazios;
- um timestamp completo inválido rejeita o lote antes de qualquer snapshot,
  sem registrar o valor rejeitado;
- `data_internacao` e `data_movimentacao` continuam somente com a data local;
  movimentos, ocupação e a Trajetória preservam a semântica por dia e não
  exibem horas nesta entrega.

O parser XLSX de referência entrega apenas datas e produz snapshots com
precisão nula; ele não faz parte da aquisição operacional.

## Variáveis de ambiente

- `SOURCE_SYSTEM_URL` — URL do sistema fonte
- `SOURCE_SYSTEM_USERNAME` — Usuário de acesso
- `SOURCE_SYSTEM_PASSWORD` — Senha de acesso
