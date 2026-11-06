# ECD-S2 — Publicação integral e atômica do censo

## 1. Identity

- Change: `extract-daily-census-from-dom`.
- Task: `openspec/changes/extract-daily-census-from-dom/tasks.md`, grupo 2.
- Dependência: ECD-S1 aceito; contrato proposto, não autorização de execução.

## 2. Objective

Entregar um handoff produtor–command que aceite somente escopo integral,
valide os artefatos e publique snapshots/run atomicamente, sem dados clínicos
nos diagnósticos.

Entrega vertical: coleta vigente → CSV/resumo → gate do command → commit ou
rejeição no PostgreSQL. O produtor e o consumidor mudam juntos neste slice.
A coleta ainda usa o XLSX existente; trocar a aquisição será ECD-S3, reutilizando
este mesmo gate. Isso é sequência interna da mesma entrega, não um backend novo,
fallback ou autorização de deploy intermediário.

## 3. Read first

- `AGENTS.md`, `PROJECT_CONTEXT.md` e `openspec/config.yaml`.
- `openspec/changes/extract-daily-census-from-dom/proposal.md`.
- `openspec/changes/extract-daily-census-from-dom/design.md` — D1, D5, D7 e
  Migration Plan; preservar D6 já entregue por ECD-S1.
- `openspec/changes/extract-daily-census-from-dom/specs/census-extraction-completeness/spec.md`.
- `openspec/changes/extract-daily-census-from-dom/specs/census-snapshot-processing/spec.md` — rejeição sem efeitos.
- `openspec/changes/extract-daily-census-from-dom/specs/daily-census-extraction/spec.md` — transporte/privacidade.
- `automation/source_system/current_inpatients/extract_census.py` — descoberta,
  `summarize_sector_results`, `run`, `save_results`, retry e `save_debug`.
- `apps/census/management/commands/extract_census.py` — subprocesso, seleção de
  arquivos, métricas, `bulk_create` e promoção do run.
- `apps/census/services.py` — completude e processamento por run.
- `tests/unit/test_extract_census_script.py`,
  `tests/unit/test_extract_census_management_command.py` e
  `tests/unit/test_proxy_config.py`.
- README do conector; testes de integração e relatório do ECD-S1 aceito.

## 4. Requirements → Evidence

| ID  | Requisito observável                                                                                                                                           | Evidência planejada                                                                                        |
| --- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| R1  | O produtor contabiliza o escopo descoberto/selecionado, setores finalizados, vazios e com erro, linhas e páginas observadas em resumo v1 agregado.             | Testes do ciclo vigente e do artefato real, com setores vazios e falhas.                                   |
| R2  | Falha definitiva, descoberta incompleta ou setor não concluído não gera CSV canônico de sucesso; retry é limitado e diagnóstico limitado não é censo integral. | RED/GREEN de falha após 40 sucessos, retry esgotado e `--max-setores`.                                     |
| R3  | O command exige CSV/resumo únicos e coerentes, escopo integral, falhas zero e o mínimo existente de 40 setores com linhas; exit zero não basta.                | Testes do command contra ausências, tipos/contadores incorretos, row count, ambiguidades e resumo parcial. |
| R4  | Snapshots e aceitação do run publicam juntos; falha ou rejeição mantém o censo anterior e não dispara efeitos clínicos do novo run.                            | Integração PostgreSQL com baseline aceito, falha injetada e verificação dos efeitos/guardas por run.       |
| R5  | stdout/stderr, métricas e falhas não expõem dados de linha, valores temporais, credenciais ou dumps. O command usa o CSV sem cópia JSON clínica.               | Sentinelas sintéticas em dados/exceções, inspeção dos artefatos e asserções de logs/metrics.               |

Cobertura principal: delta de completude inteiro; cenários de rejeição do delta
de snapshots; requisito de transporte seguro da extração. O comportamento
DOM-sem-exportação é deliberadamente aceito só em ECD-S3.

## 5. Expected blast radius

Esperado:

- ciclo/publicação/contadores do script operacional de censo e seu README;
- validação do resumo, passagem de `--csv-only`, seleção de artefatos, erros,
  transação e métricas no command;
- helper local de schema/validação somente se necessário, sem framework novo;
- testes próximos e integração com PostgreSQL e transporte temporário real.

Sensível: conservar as duas colunas e projeções de ECD-S1, CLI e bootstrap/proxy,
threshold 40, processamento por run e domínio clínico. Não mudar extração de
campos para DOM, `Admission`, movimentos, regras de ocupação/ausência, novos
serviços ou migrations. Mudanças auxiliares em testes de ciclo são aceitáveis;
refatorar o orquestrador ou alterar sua política exige escalada.

## 6. Failing-before plan

TDD em três comportamentos reais ausentes:

1. A coleta com 40 setores bem-sucedidos e um setor definitivamente falho não
   pode produzir um CSV de sucesso; o código atual grava resultados parciais.
2. O command com exit zero e CSV acima do threshold, mas resumo ausente/parcial,
   não pode aceitar snapshots; o código atual não exige esse resumo.
3. Falhar a publicação depois de inserir linhas, antes de aceitar o run, deve
   reverter o conjunto; exercitar a fronteira transacional em PostgreSQL.

Acrescentar casos de privacidade com sentinelas e de setor explicitamente vazio.
Registrar RED sem rede hospitalar, sem fabricar somente um import ausente.

## 7. Implementation constraints

Seguir a política de engenharia de `AGENTS.md`, convenções existentes e a menor
mudança correta; sem abstrações especulativas ou refactoring não relacionado.

- Implementar o protocolo local e as invariantes de D5 no produtor **e** no
  consumidor; não entregar um command que rejeita toda saída do próprio coletor.
- Nesta transição, o produtor usa a aquisição já existente. As contagens de
  páginas representam observações realmente feitas; não inventar navegação DOM,
  totais independentes, horas ou um indicador permanente de backend.
- A descoberta/seleção limitada não pode ser promovida como escopo integral.
  Setor vazio válido é sucesso; erro ou parada sem prova de conclusão não é vazio.
- Somente saída canônica final elegível entra na persistência. Rejeitar múltiplos
  candidatos; não escolher `csv_files[0]` de maneira arbitrária.
- Dados do CSV permanecem apenas no transporte temporário existente. Resumo e
  métricas aceitam somente a estrutura permitida; JSON arbitrário não é copiado.
- Remover do caminho normal chamadas de debug e mensagens arbitrárias do browser.
  Não construir logger genérico, novo serviço ou política automática de fallback.
- Não promover o laboratório a implementação nem fazer deploy entre slices.

## 8. Validation

### Focused validation

- Exercitar o produtor real com fonte/XLSX sintéticos e browser/fronteiras
  externas controlados; verificar artefatos, contadores e publicação, não apenas
  uma função que retorna `complete=True`.
- Passar CSV/resumo reais desse protocolo ao command; usar PostgreSQL real no
  teste, sem mockar o validador, o parser ou a transação que se quer provar.
- Cobrir 39/40 setores, um erro após 40 sucessos, setores vazios, escopo limitado,
  resumo ausente/inválido, tipos e equações incoerentes, arquivo ambíguo, row
  count incompatível e exit zero mentiroso.
- Injetar falha dentro da publicação, após escrita e antes de aceitação;
  comprovar zero snapshots do run rejeitado e preservação da baseline anterior.
- Verificar que nenhuma etapa posterior do ciclo processa a extração rejeitada
  e que sentinelas não aparecem em stdout/stderr, logs, metrics ou dumps.
- Documentar protocolo e semântica de diagnóstico no README nesta entrega.

### Project-required gates

Aplicar `AGENTS.md` §4: unitários, integração, lint/typecheck pertinentes e
Markdown, pelo caminho oficial. Reexecutar regressões de ECD-S1; validação de
parser isolado ou resultados antigos não aceitam o handoff deste slice.

### Runtime / verification evidence

Demonstrar produtor → arquivos temporários → command → banco em dois cenários
sintéticos: completo aceito e parcial rejeitado apesar de 40 setores/exit zero.
Registrar também a reversão da publicação e a limpeza dos artefatos temporários.
Não é necessário ou autorizado consultar o hospital para essa prova.

## 9. Acceptance criteria

- [ ] R1: resumo v1 real é produzido e inclui vazios sem inventar linhas.
- [ ] R2: falha/limitação não vira censo integral nem CSV canônico de sucesso indevido.
- [ ] R3: command valida os dois lados e preserva o threshold 40.
- [ ] R4: publicação atômica e rejeição sem efeitos novos são demonstradas no banco.
- [ ] R5: saída, métricas e artefatos de falha passam nas sentinelas de privacidade.
- [ ] O coletor vigente e o command ainda funcionam juntos, sem depender de ECD-S3.
- [ ] RED/GREEN, documentação e verification estão no relatório e gates pertinentes passam.

## 10. Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` diante de contradição ou nova decisão de
produto, arquitetura, compatibilidade pública, persistência/FSM, segurança,
privacidade, integridade ou comportamento clínico, ou expansão material.

Parar, em particular, antes de diminuir o threshold, aceitar falha como vazio,
relaxar o resumo para contornar teste, criar outro backend/fallback ou permitir
que uma rejeição altere o estado clínico anterior.

## 11. Evidence report

Produzir `/tmp/sirhosp-slice-ECD-S2-report.md`, conforme `AGENTS.md` §13:
status, R1–R5 → evidência/resultado, arquivos e motivo, RED/GREEN, comandos e
exit status, verification, desvios, levers, riscos e decisões pendentes.
Registrar explicitamente que a aquisição ainda é a vigente e DOM não está entregue.
Sem dados reais e sem duplicar o Git diff.

## 12. Worker handoff

Quando aprovado, implementar somente ECD-S2 a partir do ECD-S1 aceito. Reconstruir
contexto pelas referências, produzir RED/GREEN, a menor mudança correta,
validações e relatório. Não atualizar `tasks.md`, criar commit/push/merge/archive
nem iniciar outro slice. Havendo decisão nova, retornar `BLOCKED_NEEDS_DECISION`;
caso contrário, finalizar com `READY_FOR_REVIEW` e
`REPORT_PATH=/tmp/sirhosp-slice-ECD-S2-report.md`.
