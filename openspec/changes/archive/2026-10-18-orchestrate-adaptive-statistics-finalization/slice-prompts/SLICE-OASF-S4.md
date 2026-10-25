# SLICE-OASF-S4 — Handoff operacional e assets de fallback

## Handoff de entrada (contexto zero)

Comece somente após OASF-S3 aceito. Leia:

1. `AGENTS.md`;
2. `proposal.md`, `design.md` Migration Plan e os deltas
   `daily-statistics-production-activation` e
   `release-image-hospital-deploy` deste change;
3. seção 5c de `deploy/README.md`;
4. `.env.example` e os units hourly/D-1/estatísticos;
5. `tests/unit/test_deploy_daily_statistics_runtime.py`;
6. o runbook da RC31 como formato, não como contrato a copiar.

Não altere código Python, preflight, Compose ou workflow de publicação.

## Objetivo

Substituir nos assets e runbooks a antiga ativação por timer por um handoff
seguro: os três timers fixos permanecem fallback manual desabilitado, o
preflight e o aceite humano precedem a recriação isolada do
`census_orchestrator`, e o
rollback remove a fronteira sem apagar revisões. Entregar o runbook imutável da
RC32.

## Requisitos verificáveis

- **R1:** comentários/contratos dos units não apresentam os timers hourly, D-1
  ou estatístico como scheduler primário nem orientam habilitá-los.
- **R2:** `.env.example` documenta fronteira futura por padrão e bootstrap
  corrente permitido somente antes das 20:00 Bahia, sempre sem data passada.
- **R3:** instalação, configuração, preflight, aceite humano e ativação são
  checkpoints separados e ordenados.
- **R4:** ativação usa somente `docker compose up -d --no-deps --force-recreate
  census_orchestrator`; não usa `systemctl enable --now` nos timers hourly,
  D-1 ou estatístico.
- **R5:** runbook preserva as evidências naturais hourly/D-1 antes da recriação,
  valida os três timers `disabled/inactive`, confirma saúde e prova zero
  relatórios anteriores à fronteira por saída agregada.
- **R6:** rollback remove/reverte a fronteira e recria somente o orquestrador,
  sem excluir revisões, reverter migrations ou interromper a recuperação hourly
  adaptativa.
- **R7:** observação usa somente data, revisão, status, contagens e markers
  agregados; não imprime nomes, prontuários, leitos, texto clínico ou logs
  brutos.
- **R8:** `docs/releases/v0.1.0-rc.32-upgrade.md` contém backup, deploy dormente,
  preflight fail-closed, aceite, ativação, observação e rollback da tag exata.
- **R9:** runbook declara o privilégio read-only necessário ao socket Docker e
  documenta a recuperação adaptativa pós-05:00.
- **R10:** às 07:30, ausência de revisão `ready` produz alerta e decisão humana,
  não disparo automático; fallback manual só remove `d1_recovery_incomplete` ou
  `d1_recovery_not_confirmed` depois de sucesso D-1 comprovado e, sem essa
  evidência, preserva o aviso e nunca usa `--finalize` para limpá-lo.

## Matriz requisito → arquivo → teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| R1 | quatro units de fallback | contratos estáticos em `test_deploy_daily_statistics_runtime.py` |
| R2–R7, R9–R10 | `.env.example`, `deploy/README.md` | contratos estáticos e Markdown lint |
| R3–R10 | runbook RC32 | ordem de comandos, proibições e Markdown lint |

## Escopo e blast radius

```yaml
expected_files:
  - deploy/systemd/sirhosp-discharges.timer
  - deploy/systemd/sirhosp-historical-recovery.timer
  - deploy/systemd/sirhosp-daily-statistics.service
  - deploy/systemd/sirhosp-daily-statistics.timer
  - tests/unit/test_deploy_daily_statistics_runtime.py
  - deploy/README.md
  - .env.example
  - docs/releases/v0.1.0-rc.32-upgrade.md
allowed_incidental_files: []
max_changed_files: 8
out_of_scope:
  - apps/**
  - compose.hospital.yml
  - deploy/daily-statistics-activation-preflight.sh
  - .github/workflows/**
  - execução de comandos em produção
```

A workflow já anexa Compose, preflight e units dinamicamente; não a altere sem
um teste RED que prove asset ausente. Se forem necessários mais de oito
arquivos, pare.

## Plano TDD

### RED

Atualize primeiro os testes estáticos para o novo contrato e execute:

```bash
uv run pytest -q tests/unit/test_deploy_daily_statistics_runtime.py
```

Falhas esperadas: assertions antigas de `:13`/05:00/07:30 e da ativação por
`systemctl enable`, ausência de recriação isolada e documentação ainda
“estritamente futura”. Preserve a evidência RED.

### GREEN / refactor

Atualize units e documentação sem incluir comandos reais de produção fora de
blocos explicitamente guardados. O runbook deve usar `set -euo pipefail` nos
blocos mutáveis, variáveis de tag exata e checks anteriores a cada mutação.
Reexecute o teste focado até verde.

### Verificação local do slice

```bash
./scripts/test-in-container.sh unit
./scripts/markdown-format.sh
./scripts/markdown-lint.sh
openspec validate orchestrate-adaptive-statistics-finalization --strict
```

Depois do formatter, revise o diff para garantir que ele não expandiu para
Markdown não relacionado.

## Critérios de aceitação

- [ ] R1–R10 verdes.
- [ ] Nenhum timer hourly/D-1/estatístico é habilitado nos caminhos normais.
- [ ] Recriação limita-se ao orquestrador e ocorre após aceite humano.
- [ ] Checkpoint das 07:30 alerta sem executar retry ou extração.
- [ ] Bootstrap corrente tem boundary explícito 19:59/20:00 Bahia.
- [ ] Runbook não executa materialização ou D-1 manual para fabricar evidência.
- [ ] Markdown lint sem erros e sem comentários de disable.
- [ ] Diff limitado aos sete arquivos.
- [ ] `/tmp/sirhosp-slice-OASF-S4-report.md` completo.

## Contrato de handoff

Não altere tasks, não commita, não publique RC e não acesse produção. O reviewer
deve tratar como P1 qualquer ordem que permita recriação antes do preflight/
aceite, uso de marker manual, habilitação de qualquer timer legado, vazamento
de PHI ou
rollback destrutivo.
