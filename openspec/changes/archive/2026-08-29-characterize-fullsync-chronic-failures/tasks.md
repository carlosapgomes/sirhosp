# Tasks: characterize-fullsync-chronic-failures

## 1. CFC-S1 — Command read-only de caracterização da coorte

- [x] 1.1 Confirmar contexto: ler `AGENTS.md`, `PROJECT_CONTEXT.md`, o change
  integral (proposal/design/specs), o spec arquivado
  `openspec/specs/ingestion-pipeline-health/spec.md` como padrão de contrato
  sanitizado, `apps/ingestion/run_lifecycle.py` (taxonomia),
  `apps/ingestion/models.py` (`IngestionRun`, `IngestionRunStageMetric`,
  `FinalRunFailure`, `IngestionRunAttempt`) e
  `apps/ingestion/pipeline_health.py` como estilo.
- [x] 1.2 Criar RED (TDD) cobrindo: detecção da coorte fail-only com
  `--min-attempts` (inclui paciente com alta recente excluído pelo mínimo),
  distribuição de reasons da coorte e do contraste fail-then-ok, perfil de
  duração por estágio (mediana/p90) e estágio terminal falho, histograma
  horário agregado, idade da primeira/última falha, argumentos inválidos
  rejeitados antes de query, snapshots de contagem de models antes/depois
  idênticos, spies de rede/subprocesso/playwright/call_command e sentinelas
  de identidade/texto clínico/URL/erro bruto ausentes de stdout/stderr/error.
- [x] 1.3 Implementar GREEN mínimo: serviço
  `apps/ingestion/fullsync_failure_characterization.py` (value objects
  congelados, agrupamento por paciente somente em memória efêmera) e command
  fino `characterize_fullsync_failures` (validação antes de query, render
  allowlist, exit 0 diagnóstico); sem models, migrations ou dependências.
- [x] 1.4 Rodar inspeções `rg` (unidades nos nomes, zero mutação/rede no
  serviço+command, `parameters_json`/`pk` só em query/efêmero, cenários nos
  testes) e todos os gates oficiais; unit final >= baseline sem
  failures/errors.
- [x] 1.5 Criar `/tmp/sirhosp-slice-CFC-S1-report.md` com matriz
  requisito→arquivo→teste, snippets antes/depois, evidências e handoff para
  verificador; marcar apenas 1.x e parar.

## 2. CFC-S2 — Harness de laboratório com fixtures sintéticas

- [x] 2.1 Confirmar S1 COMPLETE (relatório + handoff aprovado); ler
  `automation/lab/` (convenções de modo laboratório),
  `apps/ingestion/extractors/persistent_evolution_pdf.py` (deadlines e
  timeouts tipados) e `persistent_extraction_adapter.py` (classificação de
  falhas) apenas nos pontos exercitados.
- [x] 2.2 Criar RED para o harness
  `automation/lab/playwright_experiments/fullsync_failure_lab.py`: fixture
  sintética de lista longa com deadline curto produz reason `timeout` com
  duração medida; fixtures de conteúdo inválido (atributo vazio, estrutura
  inesperada) mapeiam para `invalid_payload` via classificador real,
  identificando a validação disparada; artefato de veredito JSON por
  experimento (hipótese, parâmetros, duração, reason, veredito); provas de
  que fixtures são sintéticas e o harness não acessa produção/rede externa.
- [x] 2.3 Implementar GREEN mínimo: fixtures sintéticas versionadas, runner
  de experimentos H1/H2 e saída de vereditos; código claramente laboratorial
  (nunca importado por código operacional); testes sem browser real onde a
  validação for pura, marcação explícita para os que exigirem.
- [x] 2.4 Rodar inspeções `rg` (harness fora de `apps/`, zero import
  reverso, zero dado real) e gates oficiais; unit final >= baseline.
- [x] 2.5 Criar `/tmp/sirhosp-slice-CFC-S2-report.md` com evidências e
  handoff; marcar apenas 2.x e parar.

## 3. CFC-S3 — Relatório, ADR de decisão e runbook operacional

- [x] 3.1 Confirmar S2 COMPLETE; ler skill `adr-generator` e ADRs recentes
  como padrão.
- [x] 3.2 Criar RED para o gerador de relatório a partir da saída do
  command (somente agregados, seções: coorte, reasons, timing por estágio,
  histograma horário, contraste) e para o template/validador da ADR de
  decisão (vereditos confirmada/refutada/inconclusiva por hipótese com
  evidência associada; recomendação de change futuro ou próximo
  experimento; zero identidade/conteúdo clínico).
- [x] 3.3 Implementar GREEN mínimo (gerador + templates documentais
  preenchíveis com os agregados); sem tocar em worker/adapter/health check.
- [x] 3.4 Documentar em `deploy/README.md` seção própria: como rodar a
  caracterização em produção (one-shot read-only, flags, interpretação,
  exemplo systemd opcional) e o laboratório (pré-requisitos, comandos,
  artefatos de veredito), explicitando que nenhum `--apply`/mutação existe
  neste change.
- [x] 3.5 Rodar inspeções e gates oficiais; markdown lint sem erros.
- [x] 3.6 Criar `/tmp/sirhosp-slice-CFC-S3-report.md` com evidências e
  handoff; marcar apenas 3.x e parar.

## 4. CFC-S4 — Execução operacional e verificação final

- [x] 4.1 Confirmar S1–S3 COMPLETE; rodar baseline unit oficial.
- [x] 4.2 Executar a caracterização read-only em produção (janela 7d,
  contagens antes/depois) e registrar a saída agregada; laboratório e
  ambiente controlado já executados — ver nota abaixo. Fechamento via
  release `v0.1.0-rc.14` (decisão do operador, opção B). **Cumprido em
  2026-08-29**: one-shot exit 0 na produção rc.14 (coorte 23 pacientes,
  453 runs, timeout=382/invalid_payload=71, estágio terminal
  evolution_extraction=100%), relatório e `decision ADR valid` no
  container; evidência em `docs/releases/2026-08-29_v0.1.0-rc.14.md`.
- [x] 4.3 Revisar diff total: ausência de PHI, identificadores, dados
  reais, HTML/PDF real, migrations e dependências não autorizadas; a ADR
  contém somente agregados.
- [x] 4.4 Rodar todos os gates oficiais + `openspec validate
  characterize-fullsync-chronic-failures --strict` + markdown lint; abrir o
  change de correção recomendado pela ADR (proposta apenas) quando houver
  causa comprovada.
- [x] 4.5 Criar `/tmp/sirhosp-slice-CFC-S4-report.md`, marcar 4.x, aguardar
  verificação de terceiro LLM antes de qualquer arquivamento.

### Nota de execução CFC-S4 (pendência operacional única)

- O laboratório sintético foi executado nesta sessão e reproduzido
  independentemente pelo verificador: `verdicts.json` com H1/H2
  `confirmed` (9 experimentos, controles sem falha) — artefato em
  `/tmp/cfc-verdicts.json` e reproduzível via runbook §6.2.3.
- A caracterização read-only foi executada no ambiente controlado
  disponível na estação (exit 0, contagens de models antes/depois
  idênticas, saída 100% agregada); o relatório de 5 seções e a validação
  da ADR-0008 pelo validador foram confirmados pelo verificador.
- O one-shot CFC em **produção** (janela 7d) é **bloqueado por
  pré-requisito de release**, não por acesso: produção roda
  `v0.1.0-rc.13`, imagem que **não contém este change** (commits CFC são
  posteriores à tag). Verificado ao vivo pelo verificador em 2026-08-29:
  `Unknown command: 'characterize_fullsync_failures'`. Fechamento
  deliberado pelo operador via release `v0.1.0-rc.14` (runbook
  `docs/releases/v0.1.0-rc.14-upgrade.md`, etapa one-shot CFC).
- Evidência de produção registrada enquanto isso: agregados read-only
  coletados em 2026-08-28 e versionados no proposal deste change (coorte
  19 pacientes, 588 tentativas, timeout=372, invalid_payload=216,
  contraste 233/252). Os vereditos H1/H2 independem do one-shot (decisão
  vem do laboratório sobre código real).
  Ação do operador pendente: executar
  `characterize_fullsync_failures --window-hours 168 --min-attempts 3`
  conforme `deploy/README.md` §6.2.1 e, se os agregados diferirem,
  atualizar a seção Contexto da ADR-0008 (vereditos não mudam: decisão
  vem do laboratório).
