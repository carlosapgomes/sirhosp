# ECD-S1 — Precisão de origem do CSV ao snapshot

## 1. Identity

- Change: `extract-daily-census-from-dom`.
- Task: `openspec/changes/extract-daily-census-from-dom/tasks.md`, grupo 1.
- Dependências: nenhuma; contrato proposto, sujeito à aprovação antes de executar.

## 2. Objective

Persistir as duas precisões de origem a partir do transporte existente, mantendo
as projeções de data e os efeitos atuais dos consumidores.

Entrega vertical: CSV sintético → parser → command → snapshot PostgreSQL →
leitura de volta e consumo das datas antigas. Não é um slice somente de schema.

## 3. Read first

- `AGENTS.md` e `PROJECT_CONTEXT.md`.
- `openspec/config.yaml`.
- `openspec/changes/extract-daily-census-from-dom/proposal.md`.
- `openspec/changes/extract-daily-census-from-dom/design.md` — D6 e limites de D7.
- `openspec/changes/extract-daily-census-from-dom/specs/census-snapshot-processing/spec.md`.
- `apps/census/models.py` — `CensusSnapshot` e `PatientMovement`.
- `apps/census/services.py` — `_parse_dt_int`, `parse_census_csv`, classificação
  de leitos/idade, `process_census_snapshot` e `upsert_patient_movements`.
- `apps/census/management/commands/extract_census.py` — persistência do CSV.
- `tests/unit/test_extract_census_command.py`,
  `tests/unit/test_extract_census_management_command.py`,
  `tests/unit/test_census_age_band.py`,
  `tests/unit/test_patient_movement_service.py` e
  `tests/unit/test_patient_trajectory.py`.
- `automation/source_system/current_inpatients/README.md`.

## 4. Requirements → Evidence

| ID  | Requisito observável                                                                                                                  | Evidência planejada                                                                             |
| --- | ------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------- |
| R1  | Um CSV com ambas as datas/horas produz `source_admission_at` e `source_movement_at` aware na timezone configurada, vinculados ao run. | Integração do command com CSV sintético e leitura de volta dos campos.                          |
| R2  | As colunas antigas continuam somente com a data local; hora não modifica identidade clínica, movimentos ou renderização.              | Regressões de parsing, movimento idempotente, ocupação e UI.                                    |
| R3  | Datas legadas e vazios continuam aceitos; horas novas ficam null e não há backfill.                                                   | Testes de formatos legados, modelo/migração e snapshot anterior preservado.                     |
| R4  | Timestamp completo inválido falha antes de persistir parte do lote, sem emitir seu valor.                                             | CSV com linha válida seguida de inválida; zero snapshots do novo run e saída sanitizada.        |
| R5  | Reserva/vaga sem prontuário permanece linha de leito, não paciente identificado.                                                      | Integração sintética com status de leito e ausência de novos pacientes/admissões para o rótulo. |

Os requisitos derivam de `Census snapshots retain optional source temporal
precision` e `Added precision does not redefine clinical state` no delta citado.

## 5. Expected blast radius

Esperado:

- `apps/census/models.py`, uma migração aditiva em `apps/census/migrations/`;
- parser em `apps/census/services.py` e passagem dos dois valores pelo command;
- testes unitários próximos e integração específica em `tests/integration/`;
- README do conector com precisão, timezone e compatibilidade.

Sensível/fora de escopo: schema de `Admission`/`PatientMovement`, chaves de
movimentos, reconciliação, classificação de leitos/idade, seleção da Trajetória,
novas horas nas telas, coletor DOM, resumo de completude e serviços de deploy.
A expansão necessária de arquivos exige justificativa no relatório, não autorização
para mudar esses comportamentos.

## 6. Failing-before plan

Usar TDD em duas fronteiras práticas:

1. Parser recebe `DD/MM/AAAA HH:MM` sintético: demonstrar falha na separação
   entre datetime aware de origem e projeção antiga de data.
2. Command recebe um CSV válido com no mínimo 40 setores sintéticos: demonstrar
   que o snapshot persistido ainda não retém os dois timestamps.

O RED deve verificar comportamento ausente, não apenas import de símbolo ou
existência de coluna. Cobrir também timestamp inválido e null legado. Registrar
comandos, assertivas e saída sem payload clínico; não acessar a fonte real.

## 7. Implementation constraints

Seguir a política de engenharia de `AGENTS.md`, convenções existentes e a menor
mudança correta; sem abstrações especulativas ou refactoring não relacionado.

- Implementar somente os dois campos opcionais definidos em D6; migração sem
  backfill e sem índices novos. Não preencher hora ausente com meia-noite.
- Não reinterpretar `_parse_dt_int` globalmente nem mudar formatos/efeitos
  legados para acomodar a precisão nova.
- O coletor e o handoff atuais continuam funcionais neste slice: XLSX ainda
  entrega datas sem hora, portanto campos novos null. O resumo de ECD-S2 não
  pode ser exigido antes de seu produtor existir.
- Não fazer scraping ou trocar `run` para DOM; essa capacidade pertence a ECD-S3.
- Exceções da transformação nova não podem carregar timestamp, identificador
  ou conteúdo de linha para stderr, logs ou métricas.

## 8. Validation

### Focused validation

- RED/GREEN do parser e integração do command, usando fixtures de transporte e
  subprocesso controlado; o processamento do CSV e o banco devem ser reais.
- Confirmar timezone local, projeções de calendário, datas legadas e vazias,
  ordem de linha válida/inválida e vínculo ao run.
- Revisar migração e plano com `uv run python manage.py migrate --plan` apenas
  no ambiente isolado de teste; comprovar preservação de snapshots antigos.
- Executar regressões de idade, leitos, movimentos e renderização atingidas.
- Documentar a coexistência de precisões junto com esta entrega.

### Project-required gates

Aplicar `AGENTS.md` §4 e a política de validação do slice, incluindo unitários,
integração, lint/typecheck pertinentes e Markdown. Host-only é diagnóstico,
não substitui o runner oficial. Não usar resultados antigos da investigação.

### Runtime / verification evidence

Demonstrar uma execução do command com transporte sintético: sucesso retém
ambos os timestamps e as datas antigas; entrada inválida não publica snapshots
parciais. Asserções sobre o banco, run e consumidores são a evidência do produto.

## 9. Acceptance criteria

- [ ] R1: ambos os timestamps de origem persistem com timezone e proveniência.
- [ ] R2: projeções, movimentos e telas mantêm os resultados de data anteriores.
- [ ] R3: dados antigos/null permanecem intactos e a migração não faz backfill.
- [ ] R4: timestamp inválido não persiste parte do lote nem vaza seu valor.
- [ ] R5: linhas sem paciente mantêm o tratamento anterior.
- [ ] RED, GREEN, integration evidence e gates pertinentes estão documentados.
- [ ] O caminho operacional atual ainda funciona sem depender de ECD-S2/ECD-S3.

## 10. Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` se houver contradição com specs/design ou
necessidade de nova decisão de produto, arquitetura, compatibilidade pública,
persistência/FSM, segurança, privacidade, integridade ou comportamento clínico.

Em particular, parar antes de mudar timezone por conta própria, atribuir horas
a movimentos/admissões, fazer backfill ou ampliar as duas colunas propostas.
Não resolver incompatibilidade alterando silenciosamente o design.

## 11. Evidence report

Produzir `/tmp/sirhosp-slice-ECD-S1-report.md`, conforme `AGENTS.md` §13:
status, R1–R5 → evidência/resultado, arquivos e motivo, RED/GREEN, comandos e
exit status, verification, desvios de escopo, levers, riscos e decisões pendentes.
Sem dados reais e sem duplicar o Git diff.

## 12. Worker handoff

Quando aprovado, implementar somente ECD-S1 usando as referências deste
contrato, sem depender da conversa. Produzir failing-before evidence, a menor
mudança correta, validações e o relatório. Não atualizar `tasks.md`, criar
commit/push/merge/archive nem iniciar outro slice. Havendo decisão nova, parar
com `BLOCKED_NEEDS_DECISION`; caso contrário, retornar `READY_FOR_REVIEW` e
`REPORT_PATH=/tmp/sirhosp-slice-ECD-S1-report.md`.
