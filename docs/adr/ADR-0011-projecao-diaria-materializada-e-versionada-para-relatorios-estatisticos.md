# ADR-0011: Projeção diária materializada e versionada para relatórios estatísticos

## Status

Accepted — 2026-09-24.

## Contexto

O relatório nominal diário por setor precisa combinar fotografias censitárias,
medidas oficiais de ocupação e evidências clínicas que podem chegar ou ser
corrigidas depois do fechamento. Derivar o relatório em cada requisição faria a
página e o XLSX divergirem conforme as fontes mutáveis evoluíssem e impediria
identificar exatamente qual conteúdo foi exportado.

A fotografia autoritativa é o `IngestionRun` de extração censitária aceito,
associado a `CensusSnapshot` e à medição histórica correspondente. O
`CensusExecutionBatch` acompanha processamento clínico posterior e, portanto,
não define as janelas de abertura ou fechamento. As fontes clínicas continuam
autoritativas para altas e óbitos; o módulo de relatório não as corrige.

O resultado contém identidade de pacientes e exige autorização, controle de
cache e auditoria próprios. A implementação deve permanecer no monólito Django,
usar PostgreSQL para persistência e coordenação, executar por management command
e systemd, não reconstruir datas anteriores à ativação e não persistir arquivos
XLSX.

## Decisão

1. Criar um read model diário materializado em um módulo Django dedicado. Cada
   relatório referencia data local, revisão, estado, censos âncora/abertura/
   fechamento, medição e catálogo históricos, fingerprint das fontes,
   indicadores de qualidade e procedência.
2. Persistir por revisão os setores, métricas oficiais, pacientes da fotografia
   final e eventos derivados. Somente os campos nominais indispensáveis ao
   relatório serão duplicados; fatos clínicos e censitários de origem não serão
   alterados.
3. Publicar revisões de forma atômica e idempotente. O mesmo fingerprint é um
   no-op; nova evidência relevante produz outra revisão e torna a anterior não
   corrente sem mutá-la. Restrições transacionais garantem no máximo uma revisão
   corrente e pronta por data.
4. Fazer página e XLSX consumirem o mesmo serviço de projeção e a mesma revisão.
   O workbook será gerado apenas em memória e descartado após a resposta.
5. Exigir permissões distintas `view_daily_statistics` e
   `export_daily_statistics`, respostas privadas com `no-store` e logs sem nome,
   prontuário ou texto clínico. A auditoria de exportação registrará usuário,
   instante, data, revisão e contagens agregadas somente depois de o arquivo ter
   sido gerado e estar pronto para ser servido.
6. Permitir revisões automáticas por evidência tardia, mas não correções manuais
   neste change. Eventos com identidade, setor, origem ou destino ambíguos devem
   falhar de modo fechado ou carregar classificação explícita de qualidade.
7. Ativar somente a partir de uma data futura declarada, sem backfill implícito.
   O rollback desabilita finalização, navegação e exportação primeiro; tabelas de
   projeção e auditoria permanecem isoladas até decisão explícita de retenção ou
   remoção. Como as fontes não são modificadas e nenhum XLSX é persistido, não há
   restauração clínica nem limpeza de arquivos no rollback.

## Alternativas consideradas

1. **Derivar página e XLSX sob demanda:** rejeitada porque fontes tardias
   poderiam produzir resultados diferentes entre respostas, elevar o custo de
   consulta e impedir auditoria precisa da revisão exportada.
2. **Gravar eventos progressivamente em cada censo:** rejeitada para o MVP
   porque as fotografias aceitas já são preservadas e uma varredura idempotente
   no fechamento é mais simples. Nenhuma das abordagens detecta movimentos que
   ocorrem inteiramente entre dois censos.
3. **Usar `PatientMovement` como ledger de transferências:** rejeitada porque a
   granularidade diária e a unicidade atual colapsam visitas repetidas ao mesmo
   setor.
4. **Usar `CensusExecutionBatch.finished_at` como fechamento:** rejeitada porque
   esse lote representa sincronização clínica posterior, não a procedência da
   fotografia, e pode terminar horas depois.
5. **Persistir workbooks para reuso:** rejeitada para reduzir exposição de dados
   sensíveis e evitar governança adicional de arquivos.

## Consequências

### Positivas

- Página, XLSX e auditoria apontam para uma revisão reproduzível.
- Evidência tardia pode corrigir automaticamente a projeção sem apagar o
  histórico nem alterar fatos clínicos.
- Permissões independentes e ausência de workbook persistido reduzem a
  superfície de exposição.
- O rollback é isolado do domínio clínico e da ingestão.

### Negativas e trade-offs

- Dados nominais mínimos passam a existir também no read model e precisam seguir
  as mesmas proteções do banco clínico.
- Materialização, fingerprints, versionamento e concorrência aumentam a
  complexidade operacional e de testes.
- Revisões antigas e logs de exportação permanecem armazenados até uma política
  explícita de retenção; este change não introduz deleção automática.
- Movimentos invisíveis entre censos continuam fora da cobertura e devem ser
  apresentados como limitação, não inferidos.

### Riscos e mitigações

- **Divergência ou publicação parcial:** transação, fingerprints determinísticos,
  validação de invariantes e restrição de revisão corrente única.
- **Exposição de identidade:** mínimo de campos, permissões dedicadas,
  `no-store`, workbook em memória e logs somente agregados.
- **Classificação incorreta por ambiguidade:** precedência explícita,
  procedência, intervalos de detecção e comportamento fail-closed.
- **Backfill ou operação indevida:** data de ativação obrigatória e comandos
  limitados a uma data ou conjunto elegível e limitado.
- **Rollback com perda de auditoria:** desativação lógica primeiro; remoção de
  tabelas somente após aprovação de retenção e auditoria.

## Relações

- Change OpenSpec: `add-daily-statistics-reporting`.
- ADR-0002: modelagem canônica de eventos clínicos e reconciliação.
- ADR-0003: catálogo temporal de capacidade e materialização imutável.
- ADR-0009: reconciliação canônica de saídas e identidade longitudinal.
