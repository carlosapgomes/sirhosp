# ECD-S3 — Censo DOM até o snapshot, sem exportação

## 1. Identity

- Change: `extract-daily-census-from-dom`.
- Task: `openspec/changes/extract-daily-census-from-dom/tasks.md`, grupo 3.
- Dependências: ECD-S1 e ECD-S2 aceitos; contrato proposto, não execução autorizada.

## 2. Objective

Substituir a aquisição operacional por DOM, entregando os mesmos campos e ambas
as precisões temporais através do handoff já fechado até o snapshot persistido.

Entrega vertical: UI sintética em browser → `run` operacional DOM → CSV/resumo
ECD-S2 → parser/command → snapshot ECD-S1. Helpers ou probe isolado não aceitam
o slice. Integração, runbook e gate final pertencem à mesma entrega funcional.

## 3. Read first

- `AGENTS.md`, `PROJECT_CONTEXT.md` e `openspec/config.yaml`.
- `openspec/changes/extract-daily-census-from-dom/proposal.md`.
- `openspec/changes/extract-daily-census-from-dom/design.md` — D1–D7 e Migration Plan.
- Todos os três deltas em
  `openspec/changes/extract-daily-census-from-dom/specs/`.
- Contratos ECD-S1/ECD-S2 neste diretório e seus relatórios aceitos.
- `automation/source_system/current_inpatients/extract_census.py` — `run`,
  seleção/refresh, export/parse vigentes e saída já protegida por ECD-S2.
- `apps/ingestion/extractors/legacy_session_bootstrap.py` e
  `automation/source_system/proxy_config.py` — contratos a preservar.
- `apps/census/management/commands/extract_census.py`, parser e modelo de
  `apps/census/` — consumidor aceito dos slices anteriores.
- `tests/unit/test_extract_census_script.py`,
  `tests/unit/test_extract_census_command.py`,
  `tests/unit/test_extract_census_management_command.py`,
  `tests/unit/test_proxy_config.py` e testes de integração entregues antes.
- `research/census-dom-xlsx-comparison.md`,
  `research/census-dom-production-fields-evidence.json` e os probes de
  `automation/lab/playwright_experiments/` — descoberta, não implementação aprovada.
- README do conector e `deploy/README.md` — operação e rollback existentes.

## 4. Requirements → Evidence

| ID  | Requisito observável                                                                                                                   | Evidência planejada                                                                                                 |
| --- | -------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------- |
| R1  | O entry point operacional coleta diretamente da UI sem exportar XLSX nem usar fallback.                                                | Browser sintético sem superfície de exportação; `run` entrega CSV/resumo utilizáveis pelo command.                  |
| R2  | São emitidos exatamente 11 campos + dois metadados, com normalização equivalente ao parser XLSX e elegibilidade de linhas preservada.  | Golden workbook sintético lido pelo parser real, paridade de valores e shape, casos de leito e conflitos.           |
| R3  | Setor nativo e variante exportada de cabeçalhos são reconhecidos sem depender só de visibilidade ou primeira sugestão.                 | Fixtures de acentos, código compartilhado, setor errado, variantes Alta/Origem e ordem de colunas não relacionadas. |
| R4  | `Dt Int`/`Dt Mvt` vêm do tooltip da mesma célula, após espera limitada; vazio é preservado, ausência indevida ou inconsistência falha. | Browser com inicialização tardia, tooltip de outra linha, ambiguidade, data inválida, mismatch e timeout.           |
| R5  | Página nativa 100 ou maior é confirmada, com todas as páginas adicionais e término comprovado, sem truncamento/deduplicação clínica.   | Cenários 45, 100+1 linhas, reset do tamanho, total disponível/ausente, não avanço e limite de 50 páginas.           |
| R6  | O coletor DOM usa o mesmo resumo/gate ECD-S2 e conserva bootstrap, proxy, CLI, processamento por run e privacidade.                    | Regressões anteriores mais falha DOM após 40 sucessos, último censo preservado e sentinelas.                        |
| R7  | As horas chegam aos campos opcionais e os consumidores antigos mantêm datas/efeitos.                                                   | Integração PostgreSQL com handoff real, novo run concorrente, movimentos, ocupação/ausência e UI.                   |
| R8  | A operação e o rollback estão documentados sem novo serviço, deploy executado ou promessa de ganho não medido.                         | README/runbook revisados, manifesto do que foi efetivamente verificado e gates finais.                              |

Referência normativa: delta `daily-census-extraction` inteiro; deltas de
completude e snapshots na composição, sem reinterpretar as decisões D1–D7.

## 5. Expected blast radius

Esperado:

- adaptador do censo e módulo de produção adjacente somente se necessário;
- fixtures e testes do script/proxy/parsing, integração específica e verificador
  restrito `automation/lab/playwright_experiments/verify_census_dom.py` a criar;
- README do conector e seção operacional relevante de `deploy/README.md`;
- ajustes mínimos no handoff/command já aceito somente se necessários à composição.

Sensível: não mudar o protocolo aprovado em ECD-S2, schema além de ECD-S1,
bootstrap/proxy central, serviços/timers, domínio clínico ou UI de Trajetória.
Código operacional não importa laboratório. Não adotar os arquivos ainda não
rastreados da investigação como implementação pronta nem alterá-los por conveniência.

## 6. Failing-before plan

Antes da troca, o entry point ainda usa XLSX:

1. Criar cenário de browser sintético com tabela/tooltips, mas sem exportação.
   Demonstrar que `run` não conclui a coleta apenas pelo DOM.
2. Caracterizar a falta das horas de ambas as datas no caminho anterior, usando
   o mesmo workbook sintético de referência e asserções do transporte/snapshot.
3. Adicionar RED para atraso de widgets, variantes, seleção e paginação nova.

O primeiro RED não pode ser substituído por testar apenas uma nova função ainda
inexistente. Usar TDD nos seams determinísticos e verification executável no
browser. Nenhum teste/fixture usa o hospital ou dados reais.

## 7. Implementation constraints

Seguir a política de engenharia de `AGENTS.md`, convenções existentes e a menor
mudança correta; sem abstrações especulativas ou refactoring não relacionado.

- Trocar a aquisição no entry point existente; não adicionar backend selecionável,
  fallback XLSX, dependência, serviço ou controller novo.
- Produzir o payload de 11 campos, não a tabela clínica inteira. Paridade ignora
  somente diferenças de representação previstas, comparando a componente de
  data com o XLSX sem alegar que a planilha comprova a hora ausente nela.
- Datas preenchidas aguardam tooltips por até 10 segundos; se faltarem, forem
  inválidos, ambíguos ou incompatíveis, falhar. Não transformar timestamp da
  coleta ou do processamento em evento clínico.
- Preservar reserva/vaga, ausência de `Dt Int`, omissão legada por ambas as
  identidades vazias e linhas conflitantes distintas. Rejeitar replay de página
  não é licença para deduplicar pacientes ou posições da fonte.
- Usar a página longa e os limites de D4; total nativo indisponível deve ficar
  explícito. Não inventar total, sucesso de setor ou conclusão após timeout.
- Atualizar os testes antigos de refresh-antes-de-exportar para a mesma garantia
  antes da captura DOM; não apagar a proteção contra resultado vazio obsoleto.
- Regenerar evidência no código operacional novo; o sucesso anterior dos probes
  e as contagens da investigação não são acceptance criteria fixos do hospital.

## 8. Validation

### Focused validation

- TDD para schema, variantes e normalizações com workbook/HTML sintéticos.
- Exercitar associação dos dois tooltips e sua inicialização após pesquisa,
  paginação e mudança de tamanho. A ausência genuína de data não é erro.
- Exercitar os casos R3–R5 com browser real local, sem rede externa, credenciais
  ou `.env` hospitalar na opção sintética do verificador.
- Integrar CSV/resumo efetivamente produzidos com o command e PostgreSQL,
  preservando asserções e sentinelas de ECD-S1/ECD-S2.
- Atualizar README e runbook: implantação conjunta, conferência agregada,
  campos opcionais sem backfill e rollback de imagem sem apagar dados. Não
  executar deploy nem criar pacientes de teste em produção.

### Project-required gates

Aplicar integralmente o gate final de `AGENTS.md` §12, além dos gates por slice
em §4: quality gate completo, integração separada, Markdown e verification
obrigatória abaixo no estado final. Não declarar pronto com resultados anteriores
à alteração mais recente ou confundir status dos artefatos com aceite do código.

### Runtime / verification evidence

Criar e executar:

```bash
uv run python automation/lab/playwright_experiments/verify_census_dom.py --synthetic
```

O comando ainda não existe no baseline: é entrega deste slice, não pré-condição
oculta. Deve dirigir o coletor operacional com UI/catalogação sintética e
comprovar os casos R1–R6, não apenas importar o probe anterior. Usar catálogo
completo sintético quando a prova atravessar o gate mínimo de 40 setores.

Compor essa evidência com integração PostgreSQL para R7: ambos os timestamps
persistidos, datas antigas iguais, run correto e rejeição parcial sem efeitos.
Registros de evidência devem distinguir o que foi provado por browser do que
foi provado no banco. Registrar tempos com seu escopo, sem fator de aceleração
ponta a ponta não medido. Nova visita à fonte exige autorização separada.

## 9. Acceptance criteria

- [ ] R1: `run` operacional conclui sem exportação e não tem fallback automático.
- [ ] R2: paridade sintética dos 11 campos/metadados e elegibilidade está provada.
- [ ] R3: seleção e variantes preservam semântica ou falham explicitamente.
- [ ] R4: ambos os horários chegam da célula correta; atrasos, vazios e erros têm prova.
- [ ] R5: página longa, 100+1 e término/erros de paginação têm prova sem corte.
- [ ] R6: completude, sessão, CLI, proxy e privacidade continuam protegidos.
- [ ] R7: snapshot preserva precisão sem modificar o resultado clínico ou a UI.
- [ ] R8: docs/runbook, gates finais e evidências estão completos, sem deploy.
- [ ] Os relatórios distinguem descoberta anterior, verification nova e pendências reais.

## 10. Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` por contradição ou necessidade de nova decisão
de produto, arquitetura, compatibilidade pública, persistência/FSM, segurança,
privacidade, integridade ou comportamento clínico, ou expansão material.

Parar antes de depender de API interna não aprovada, usar outra unidade como
substituta, relaxar tooltip/completude, mudar a variante sem evidência, criar
fallback, propagar horas ao domínio/UI ou exigir dados reais para aceitar o slice.

## 11. Evidence report

Produzir `/tmp/sirhosp-slice-ECD-S3-report.md`, conforme `AGENTS.md` §13:
status, R1–R8 → evidência/resultado, arquivos/motivo, RED/GREEN, comandos e exit
status, browser/banco, desvios, levers, riscos e decisões pendentes. Não duplicar
Git diff. Entregar também a matriz final dos três deltas com ponteiros aos testes
e cenários, sem payloads clínicos ou alegação de verificação não executada.

## 12. Worker handoff

Quando aprovado, implementar somente ECD-S3 sobre ECD-S1/ECD-S2 aceitos, usando
as referências em contexto fresh. Produzir failing-before evidence, a menor
mudança correta, verification/gates e o relatório. Não atualizar `tasks.md`,
criar commit/push/merge/archive ou iniciar outra unidade. Havendo decisão nova,
retornar `BLOCKED_NEEDS_DECISION`; caso contrário, finalizar com
`READY_FOR_REVIEW` e `REPORT_PATH=/tmp/sirhosp-slice-ECD-S3-report.md`.
