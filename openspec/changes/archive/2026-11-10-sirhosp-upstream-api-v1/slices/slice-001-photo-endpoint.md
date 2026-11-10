# Slice UPA-001 — App isolado, auth, foto de internados e logging sanitizado

## Identity

- Change: `sirhosp-upstream-api-v1`.
- Slice: `UPA-001`.
- Tasks: grupos 1, 2 e 3 de `tasks.md` (itens 1.1–1.4, 2.1–2.3, 3.1–3.2).

## Objective

Entregar o primeiro endpoint funcional de ponta a ponta —
`GET /api/v1/inpatients/current` autenticado, servindo a foto do último
ciclo elegível com envelope de erros padronizado, fronteira de middlewares
correta, token ligado aos composes e logging sanitizado desde o primeiro
commit (nenhuma rota da API existe sem sua proteção de logs).

## Read first

- `AGENTS.md` e `PROJECT_CONTEXT.md`.
- `openspec/changes/sirhosp-upstream-api-v1/proposal.md`.
- `openspec/changes/sirhosp-upstream-api-v1/design.md` (D1–D7, D9, D10).
- `openspec/changes/sirhosp-upstream-api-v1/specs/upstream-read-api/spec.md`.
- `config/urls.py` (padrão de `include` das rotas).
- `config/settings.py` (settings via env + stack de middlewares).
- `config/gunicorn.conf.py` (onde o `logger_class` será ligado).
- `docker/gunicorn-wrapper.sh` (como o gunicorn é invocado).
- `apps/accounts/middleware.py` (allowlist `ALLOWED_PATH_PREFIXES`).
- `compose.prod.yml` (environment enumerado do serviço web).
- `compose.hospital.yml` (`x-app-environment` compartilhado).
- `apps/census/models.py` (`CensusSnapshot`, `BedStatus`).
- `apps/ingestion/models.py` (`IngestionRun`: `status`, `intent`).
- `apps/census/management/commands/extract_census.py` (prova de que a
  persistência do ciclo é atômica).
- `apps/core/views.py` + `apps/core/urls.py` (padrão `JsonResponse`).
- `.env.example` (padrão de documentação de env vars).

Follow the repository engineering policy in `AGENTS.md` and preserve existing
conventions. Prefer the smallest correct change; avoid speculative
abstraction and unrelated refactoring.

## Requirements

| ID  | Requisito                                                                                                                                                                                                                                                                                 | Evidência planejada                                                                         |
| --- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| R1  | App isolado criado com rotas `/api/v1/` registradas, token ligado aos environments de `compose.prod.yml` e `compose.hospital.yml`, e `check` passando                                                                                                                                     | `check` verde + teste que resolve as URLs + inspeção dos composes                           |
| R2  | Auth Bearer com `401` sem/cabeçalho malformado/token errado e fail-closed com precedência (`500` sempre que o setting estiver ausente, qualquer que seja a credencial)                                                                                                                    | Unit da matriz completa setting × credencial                                                |
| R3  | Envelope `{"error": {"code", "message"}}` com códigos `unauthorized`/`patient_not_found`/`no_snapshot`/`bad_request`/`internal_error` + `Cache-Control: no-store`, sem stack trace em `500`                                                                                               | Unit do envelope + headers em toda resposta                                                 |
| R4  | Fronteira de middlewares: views com `csrf_exempt`, prefixo `/api/v1/` na allowlist de troca de senha; POST sem token → `401`, POST com token → `405`, portal intacto                                                                                                                      | Testes pela stack real de middlewares + suítes do portal verdes                             |
| R5  | Foto resolvida pelo último run elegível (`census_extraction`/`succeeded`/≥1 linha; ordem: `MIN(captured_at)` DESC, pk DESC); `running`/`failed`/sem linhas/run nulo nunca surfam; ordem de captura vence ordem de finish; empate resolve por pk                                           | Unit da query com runs mistos, finish×capture conflitantes, empate e linhas legadas sem run |
| R6  | Linha 1:1 com o contrato (9 campos), só pacientes por padrão, par setor preservado, `leito` vazio permitido, `nome` não vazio, ordem `setor`/`setor_codigo`/`leito`/`prontuario`/pk ASC estável com chaves duplicadas; linha de paciente com `nome` vazio recusa a foto inteira com `500` | Integration do payload + chaves duplicadas + linha inválida sintética                       |
| R7  | Foto vazia retorna `200` com `patients: []`; sem foto elegível retorna `404 no_snapshot`; polls repetidos retornam payload idêntico                                                                                                                                                       | Integration dos três cenários                                                               |
| R8  | Sanitizador reduz todo `/api/v1/*` (rotas conhecidas, desconhecidas/malformadas, qualquer query string) a padrão de rota fixo, preservando método e status; outros paths passam intactos                                                                                                  | Unit do sanitizador com paths variados + queries                                            |
| R9  | Logger customizado ligado via `config/gunicorn.conf.py` (só `logger_class`); boot rootless íntegro                                                                                                                                                                                        | Teste de config + boot do container                                                         |
| R10 | Requests reais em container (foto, foto com query, path desconhecido, request malformado, erro forçado) emitem access record só com método, rota sanitizada e status; error output sai sanitizado ou comprovadamente ausente sob supressão; aplicação não loga target, query ou PHI       | Verificação containerizada com captura dos logs + teste de captura de logs da aplicação     |

## Expected blast radius

Superfícies esperadas:

- `apps/upstream_api/` (novo: `apps.py`, `urls.py`, `views.py`, auth helper,
  envelope de erro, query da foto, módulo do logger).
- `config/urls.py` (um `include`).
- `config/settings.py` (leitura de `SIRHOSP_UPSTREAM_API_TOKEN`).
- `config/gunicorn.conf.py` (adição de `logger_class` apenas).
- `apps/accounts/middleware.py` (entrada `/api/v1/` na allowlist apenas).
- `compose.prod.yml` + `compose.hospital.yml` (uma env var cada).
- `.env.example` (documentação da nova env var).
- `tests/unit/test_upstream_*.py` e `tests/integration/test_upstream_*.py`
  (novos, seguindo os layouts existentes).

Superfícies sensíveis / fora de escopo sem escalada:

- `apps/census`, `apps/patients`, `apps/ingestion` (leitura via ORM apenas,
  nenhuma alteração).
- Lógica dos middlewares além da allowlist e do `csrf_exempt` path-scoped;
  diretivas do gunicorn além de `logger_class`; demais diretivas dos
  composes; `docker/gunicorn-wrapper.sh` (não alterar salvo inviabilidade
  provada da ligação via conf — escalar antes).
- Migrations, extração, workers, portal, templates.
- Endpoint de demografia (slice UPA-002).
- Output do `runserver` de desenvolvimento: fora de escopo (dev usa só
  dados sintéticos, conforme `AGENTS.md` §19); o contrato cobre os logs do
  servidor implantado.

Arquivo adicional só com justificativa no relatório.

## Failing-before plan

1. Teste que resolve `GET /api/v1/inpatients/current` falha (rota não
   existe → `404` do Django, não o envelope).
2. Teste de auth com token válido falha (helper/decorator não existe);
   teste da matriz setting-ausente × credencial falha idem.
3. Teste pela stack real com POST sem token falha (espera `401`, recebe
   `403` de CSRF ou `404`).
4. Teste da query com runs `running`/`failed`/sem linhas misturados,
   finish×capture conflitantes e empate de `captured_at` falha (query não
   existe; após GREEN, prova exclusão + ordenação exata).
5. Teste de foto vazia, de `404 no_snapshot`, de chaves duplicadas e de
   linha inválida falham (endpoint não existe).
6. Unit que espera request target sanitizado falha (sanitizador/logger não
   existem).
7. Verificação containerizada pré-logging mostra request target bruto
   (path com query, path desconhecido) e output de erro não verificado
   (falha observável registrada como evidência before, valores sintéticos).

## Implementation constraints

- Auth executa antes de qualquer outra checagem: sem credencial válida a
  resposta é `401`, exceto com setting ausente, que responde `500` sempre
  (precedência fail-closed, derivada do spec).
- Comparação do token com `secrets.compare_digest`; setting ausente ou
  vazio falha fechado (nenhum request autenticado).
- Query da foto por `ingestion_run_id` do último run elegível, ordenação
  exata de D3/spec; `finished_at` nunca usado; nunca `Max("captured_at")`
  puro; não reutilizar a abordagem do `/beds/`.
- Linha inválida (`prontuario` não vazio + `nome` vazio) recusa a foto com
  `500` genérico: nunca omitir a linha nem inventar nome.
- Isenções de middleware path-scoped a `/api/v1/`; nenhuma mudança no
  comportamento do portal; suítes de accounts/csrf continuam verdes.
- Nos composes, adicionar só a env var (seguir o estilo de cada arquivo:
  lista em prod, mapa em hospital); não alterar portas, binds ou serviços.
- Sanitização por padrão de rota fixo por prefixo, queries descartadas,
  nunca por detecção de valores nominais; se algum error-path do stack
  implantado logar target bruto, ligar supressão/sanitização nele em vez
  de documentar exceção.
- Manter `preload_app` e o boot rootless funcionando; regressão no boot é
  bloqueadora do slice.
- Serialização fiel 1:1; não criar abstração de framework API, paginação,
  filtros ou segundo formato; não antecipar UPA-002.
- Nenhuma migration; nenhuma dependência nova.

## Validation

### Focused validation

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh unit
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

Mais a verificação containerizada de R10 (subir o serviço; chamar foto,
foto com query, path desconhecido, request malformado e erro forçado com
valores sintéticos; inspecionar access output e error output/ausência).

### Project-required gates

Seguir `AGENTS.md`; gates finais do change rodam após todos os slices.
`.env.example` alterado passa por `./scripts/markdown-lint.sh` apenas se
algum `.md` for tocado (não esperado neste slice). Execução host-only não
vale como evidência de R9/R10 (o logger só existe sob gunicorn em
container).

### Runtime/verification evidence

Requests reais contra instância containerizada com fixtures sintéticas:
`401` sem token, `500` com setting ausente, `200` com token e corpo da
foto conferido campo a campo, `captured_at` único em todas as linhas,
`404 no_snapshot` sem foto elegível, access log sanitizado nos cinco casos
e error output sanitizado ou comprovadamente ausente. Sem Playwright (API
é HTTP direto); sem dados reais.

## Acceptance criteria

- [ ] R1: app registrado, rotas resolvidas, env var nos dois composes,
      `check` verde.
- [ ] R2: matriz setting × credencial completa; `500` com precedência sem
      setting; comparação em tempo constante.
- [ ] R3: envelope exato em todos os erros incluindo `no_snapshot`;
      `no-store` em toda resposta; `500` sem stack trace.
- [ ] R4: `csrf_exempt` + allowlist path-scoped; POST sem token `401`,
      POST com token `405`; portal intacto pela stack real.
- [ ] R5: foto igual ao último run elegível pela ordenação exata; finish
      nunca decide; empate por pk; demais runs e linhas legadas excluídos.
- [ ] R6: 9 campos por linha, só pacientes, pares de setor preservados,
      `leito` vazio ok, ordem exata estável com duplicadas; linha inválida →
      `500` da foto inteira.
- [ ] R7: foto vazia `200` com `[]` e `row_count: 0`; sem foto `404
no_snapshot`; repeats idênticos.
- [ ] R8: sanitizador cobre rotas conhecidas, desconhecidas/malformadas e
      queries, preservando demais paths, por unit test.
- [ ] R9: `logger_class` ligado só via conf; boot do container íntegro;
      demais diretivas intactas.
- [ ] R10: access record real nos cinco casos só com método, rota
      sanitizada e status; error output sanitizado ou comprovadamente
      ausente; aplicação sem PHI em logs.

## Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` se houver contradição
proposal/spec/design, necessidade de migration/dependência nova/mudança na
extração ou nos middlewares/gunicorn além do path-scoped, expansão
material, risco novo de privacidade/integridade, regressão no boot
rootless, ou impossibilidade de cumprir ordenação exata ou sanitização de
error-path sem redesign.

## Evidence report

Caminho: `/tmp/sirhosp-slice-UPA-001-report.md`. Seguir relatório
obrigatório de `AGENTS.md` (requirements → evidence, RED/GREEN, arquivos,
comandos/exit, verification, desvios, riscos). Sem dados reais; valores
sintéticos do before/after explicitamente marcados como sintéticos.

## Worker handoff

Implement only this approved slice.
Treat the slice and referenced OpenSpec artifacts as the implementation contract.
Reconstruct context from the listed files; do not rely on prior conversation.
Follow the repository engineering policy.
Produce failing-before evidence, implement the smallest correct change, run focused validation, and produce the required evidence report.
Do not update `tasks.md`, commit, push, merge, archive, or start another slice.
If a new decision is required, stop with `BLOCKED_NEEDS_DECISION` and evidence.
Otherwise finish with `READY_FOR_REVIEW` and `REPORT_PATH=/tmp/sirhosp-slice-UPA-001-report.md`.
