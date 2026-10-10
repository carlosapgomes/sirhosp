# ORIG-001 — Origens privadas de ponta a ponta em CLI e MCP

## Identity

- Change: `externalize-verification-origins`.
- Slice: `ORIG-001`.
- Tasks: [grupo 1 de tasks.md](../tasks.md).
- Estado: aprovado pelo operador para execução via `/change-loop`.

## Objective

Operar as jornadas existentes usando uma origem dev privada e validada, sem
FQDNs operacionais na árvore atual nem dependência de URL para revogar sessões.

## Read first

- `AGENTS.md` e `PROJECT_CONTEXT.md`.
- [Proposal](../proposal.md), [design D1–D8](../design.md) e
  [spec](../specs/verification-origin-configuration/spec.md).
- `scripts/verify_portal.py`: Target, DoctorReport, OpenCredentials,
  `_default_driver_factory`, cmd_doctor/open/run/close/status/callback.
- `automation/verification/browser.py`: origem atual, construtores,
  RequestPolicy, jornadas e `case_policy_allowlist`.
- `tests/unit/test_verification_session.py` e
  `tests/unit/test_verification_browser.py`: fixtures, factories e cleanup.
- `tests/integration/test_verification_session.py`: contratos herdados.
- `docs/dev-verification.md` e `.pi/skills/verify-sirhosp/`.
- `pyproject.toml`, somente para confirmar `python-dotenv` existente.
- `openspec/changes/add-dev-browser-verification-suite/specs/`: contratos
  herdados de sessão e browser; não modificar a change anterior.

Paths em backticks são relativos ao repo; links `../` são relativos a este
arquivo. Não ler o `.env` real da aplicação nem copiar URLs reais ao plano.

## Requirements

| ID | Requisito do slice | Evidência planejada |
| --- | --- | --- |
| R1 | Loader único do arquivo privado, sem fallback/override | Unit com diretório temporário, duas chaves e variável do processo conflitante |
| R2 | Configuração ausente/inválida não produz efeitos de abertura | Tests de doctor/open/run com sentinelas de serviços, state, timer, prepare/open e senhas |
| R3 | Normalização HTTPS e dev diferente de produção | Matrix de URI/porta/case/path/userinfo e prova de nenhuma consulta à produção |
| R4 | `origin` aditiva em doctor/open e propagação explícita no runner | JSON/factory/context/policy tests e auth/smoke CLI real autorizado |
| R5 | Close/recovery/callback/status e imports independentes do perfil | Command paths existentes com arquivo ausente/malformado e revogação fenced observada |
| R6 | Nenhum FQDN operacional da baseline nos arquivos atuais/candidatos | Inventário/scan executável por paths/contagens, sem blacklist literal nova |
| R7 | Roteiro MCP usa origem canônica, sem inventar proteção de rede | Auth MCP real e dry-run/inspeção do fluxo doctor/open divergentes, distinguindo os tipos de prova |
| R8 | Fences, cleanup, cobertura e template permanecem honestos | Regressões herdadas, template vazio bloqueia abertura, reports e review |

A spec e o design são canônicos para detalhes; não ampliar requisitos durante
a implementação. Os testes do loader não são prova de funcionamento da UI.

## Expected blast radius

Superfícies esperadas:

- Novo `automation/verification/origins.py` e
  `tests/unit/test_verification_origins.py`.
- `scripts/verify_portal.py` e `automation/verification/browser.py`.
- `tests/unit/test_verification_session.py` e
  `tests/unit/test_verification_browser.py` para fixtures/factories explícitas.
- `docs/dev-verification.md` e novo
  `docs/examples/verification.env.example`.
- `.pi/skills/verify-sirhosp/SKILL.md`, `features/README.md`,
  `features/authentication.md` e `features/census.md`; outros mapas somente
  se for necessário ajustar o consumo da metadata, com justificativa.

Sem número rígido de arquivos: a origem é uma dependência transversal pequena,
não licença para refatorar o verificador inteiro. Superfícies sensíveis fora
do escopo: apps/accounts, models/migrations, FSM/records, engine/volume/fences,
configuração MCP, autenticação do produto, TLS/edge/DNS e workers.

Preservar flags existentes, campos JSON atuais e formato dos records de S1.
Novos metadados e remoção dos defaults internos estão aprováveis no design;
compatibilidade diferente disso exige decisão. Não corrigir o P2 fake-detach.

## Failing-before plan

1. Adicionar regressões do novo contrato antes de mudar a implementação.
   Esperar origem compilada/default, falta de loader/metadata e open/run
   sem bloqueio de configuração quando o alvo é stubbed e está apto.
2. Registrar que o scan atual encontra nomes nos arquivos da baseline,
   mostrando somente paths e contagens. Obter valores da baseline para esse
   diagnóstico, sem copiá-los a teste ou arquivo versionável novo.
3. Caracterizar close/recovery/callback/status sem perfil: alguns controles
   já passam antes e devem continuar passando; não declarar RED artificial.
4. Usar somente fixtures sintéticas e temporários. Falha por dependência
   ausente no container não é RED funcional; tratar infraestrutura conforme
   `AGENTS.md`.

## Implementation constraints

- Loader não escreve arquivos, não altera `os.environ` nem lê o `.env` da app.
- Nenhuma leitura obrigatória de configuração ocorre no import ou no cleanup.
- Uma origem capturada na abertura permanece até o fim daquela operação.
- Não publicar produção via uma opção de target ou sondá-la para validar URL.
- Preservar interceptação, sanitização, fatal sincrônico e TLS; não habilitar
  `ignore_https_errors` nem alargar origens/CDNs para passar a prova.
- Atualizar fixtures/defaults somente onde a mudança explicitamente requer;
  não enfraquecer assertions ou converter BLOCKED em PASS.
- Alterar código/documentação atomicamente neste slice, sem parser-only slice
  que deixe a skill apontando para o destino antigo.
- Preparar arquivo privado e dirigir dev/MCP são operações separadamente
  autorizadas pelo operador, não consequência da mera existência do plano.

## Validation

### Focused validation

RED/GREEN pelo test-runner oficial, acrescentando o arquivo novo de testes:

```bash
POSTGRES_PORT=55433 docker compose -p sirhosp-test \
  -f compose.yml -f compose.test.yml run --rm test-runner \
  uv run --no-sync pytest -q tests/unit/test_verification_origins.py \
  tests/unit/test_verification_browser.py tests/unit/test_verification_session.py
```

Manter regressões nativas de S2 executadas, sem skips como evidência positiva.
Ruff/mypy explícitos para `scripts/verify_portal.py` e
`automation/verification`, via test-runner e `--explicit-package-bases`.
Encerre somente recursos de testes owned, sem remover volumes.

### Project-required gates

Seguir `AGENTS.md` para check/unit/lint/typecheck e gate final completo;
manter a integration de S1 verde. Aplicar design D9 da change anterior aos
checks de scripts/automation. Todos os `.md` alterados devem passar Markdown;
validar explicitamente `.pi/skills/verify-sirhosp/**/*.md` porque o script
global exclui `.pi`. OpenSpec strict nesta change também deve passar.

### Runtime/verification evidence

Somente após aprovação e autorização operacional, com arquivo privado
preparado pelo operador e expectativas fictícias conhecidas:

```bash
uv run python scripts/verify_portal.py doctor --target dev --confirm-fictitious
uv run python scripts/verify_portal.py run --feature auth --role both \
  --confirm-synthetic-data
uv run python scripts/verify_portal.py run --feature smoke --role both \
  --confirm-synthetic-data --expectations /CAMINHO/PRIVADO/expectations.json
```

Executar autenticação MCP pelo roteiro atualizado, consumindo `origin` e
comparando doctor/open antes de navegar. Comprovar isolamento e cleanup.
A divergência recebe dry-run com respostas sintéticas e review do roteiro;
registrar a decisão de não navegar e de usar close, sem alegar que esse
ensaio revogou contas reais. A jornada positiva comprova a revogação real.
Não repetir toda a matriz MCP de funcionalidades nem as campanhas de
fault-injection antigas sem alteração material naquelas fronteiras.

Provar a independência do cleanup com perfil temporário/falha de leitura no
seam, nunca apagando o arquivo real com sessão ativa. Caso a prova local não
represente um command path canônico, não contá-la como R5.

## Acceptance criteria

- [ ] R1–R3: resolução determinística e configuração inválida sem efeitos,
      testes RED/GREEN registrados e diagnósticos sem valores inválidos.
- [ ] R4: metadata aditiva, origem igual em factory/session/driver/policy,
      CLI auth/smoke autorizados PASS e sem caso solicitado omitido.
- [ ] R5: imports e comandos de cleanup/status sem URL configurada,
      preservando fingerprint, ownership, revogação e timer.
- [ ] R6: scan da árvore atual/candidatos sem os nomes operacionais antigos;
      histórico explicitamente não purgado.
- [ ] R7: MCP autentica pela origem canônica e comprova estado/cleanup;
      o dry-run de divergência escolhe não navegar e o close canônico, com
      os limites dessa evidência explicitados e confirmados no review.
- [ ] R8: template sem valores reais, runbook/mapas coerentes, guards
      herdados e regressões nativas intactos; gates e review aprovados.

## Escalation conditions

Retornar `BLOCKED_NEEDS_DECISION` se houver contradição de contratos, novo
requisito/arquitetura, necessidade de alterar FSM/schema/auth/fences,
compatibilidade não prevista, impossibilidade de isolamento/TLS/cleanup,
expansão material ou risco de dados. Perfil/expectations/autorização ausentes
bloqueiam a verification; não fabricar valores, seeds ou confirmação.

Sem outra rodada automática após o limite do controller. Não acessar outros
engines/alvos nem reescrever histórico para cumprir R6.

## Evidence report

Caminho: `/tmp/sirhosp-slice-ORIG-001-report.md`.
Seguir o relatório obrigatório de `AGENTS.md`: requirements → evidence,
RED/GREEN, arquivos/motivos, comandos/exit, verification, desvios e riscos.
Não incluir URLs reais em arquivos candidatos a Git nem credenciais/cookies
no relatório. Os registros runtime privados seguem o contrato de evidências
herdado; não criar commit de `/tmp`.

## Worker handoff

Implement only this approved slice after explicit approval.
Treat the slice and referenced OpenSpec artifacts as the implementation
contract; reconstruct context from files, not the prior conversation.
Follow AGENTS.md, produce failing-before evidence, implement the smallest
correct change, validate and write the report. Do not update tasks, commit,
push, merge, archive, rewrite history or start another slice. If a new
decision is needed, stop with BLOCKED_NEEDS_DECISION and evidence.
Otherwise finish with READY_FOR_REVIEW and
REPORT_PATH=/tmp/sirhosp-slice-ORIG-001-report.md.
