# SLICE-DSRS-S8 — Ativação futura e observabilidade

## Handoff de entrada

Você inicia com contexto zero após DSRS-S7 aceito. Leia `AGENTS.md`,
`PROJECT_CONTEXT.md`, `proposal.md`, a decisão 11, riscos e Migration Plan de
`design.md`, `deploy/README.md`, os units systemd existentes e os relatórios
S1–S7 em `/tmp`. Este slice prepara ativação futura; não opere produção, não
materialize datas reais e não faça backfill.

## Objetivo

Adicionar contrato systemd e runbook para finalizar somente dias pós-ativação,
com rollback, observabilidade agregada e pré-condições explícitas de cadência de
altas intradiárias, recuperação D-1 e óbitos.

## Requisitos verificáveis

- **R1:** service executa o management command pelo padrão operacional do
  projeto e timer usa calendário documentado posterior ao fechamento do dia.
- **R2:** data de ativação é obrigatória/documentada e impede qualquer backfill
  anterior implícito.
- **R3:** unidades declaram usuário, diretório, ambiente, dependências, política
  de falha e saída compatíveis com os units existentes.
- **R4:** runbook cobre instalar, habilitar, verificar, observar, rerun de uma
  data, desabilitar e rollback sem remover fontes clínicas.
- **R5:** ativação fica condicionada à evidência operacional das cadências de
  alta intradiária, D-1 e óbitos.
- **R6:** logs/health usam datas, revisões, status e contagens, sem identidade.
- **R7:** validações são estáticas/sintéticas e nenhuma ação de produção é
  executada.

## Escopo e blast radius

```yaml
expected_files:
  - deploy/systemd/sirhosp-daily-statistics.service
  - deploy/systemd/sirhosp-daily-statistics.timer
  - deploy/README.md
  - .env.example
  - tests/unit/test_deploy_daily_statistics_runtime.py
allowed_incidental_files: []
out_of_scope:
  - systemctl, docker compose ou banco de produção
  - backfill de qualquer data real
  - mudanças nas cadências existentes de alta/óbito
  - código de página, XLSX ou materialização
  - correções manuais
```

Limite: cinco arquivos. Pare se a ativação exigir trocar o orquestrador,
introduzir scheduler novo ou habilitar/desabilitar units existentes.

## Matriz requisito -> arquivo -> teste/check

| Requisito | Arquivo(s) esperado(s) | Teste/check |
| --- | --- | --- |
| R1–R3 | units, `.env.example` | parser/teste estático dos contratos |
| R4–R5 | `deploy/README.md` | asserts de runbook e inspeção humana |
| R6–R7 | units/testes | ausência de PHI e comandos mutantes |

## Plano de testes

### RED

Crie primeiro o teste de contrato e execute:

```bash
./scripts/test-in-container.sh unit \
  tests/unit/test_deploy_daily_statistics_runtime.py
```

Falha esperada: units, variáveis e runbook ainda inexistentes.

### GREEN / verificação local

Adicione apenas artefatos de deploy/documentação e repita o RED. Depois:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/markdown-lint.sh
```

Não execute `systemctl`, o service, o timer ou o command contra dados reais.

## Critérios de aceitação

- [ ] R1–R7 cobertos por teste/inspeção objetiva.
- [ ] Nenhuma operação de produção ou backfill ocorreu.
- [ ] Runbook contém ativação, observação e rollback claros.
- [ ] Relatório criado em `/tmp/sirhosp-slice-DSRS-S8-report.md`.
- [ ] Checks e Markdown alterado passam.
