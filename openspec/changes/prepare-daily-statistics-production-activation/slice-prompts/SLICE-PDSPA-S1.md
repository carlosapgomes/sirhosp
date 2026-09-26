# SLICE-PDSPA-S1 — Preflight somente leitura

## Handoff de entrada

Você inicia com contexto zero. Leia `AGENTS.md`, `PROJECT_CONTEXT.md`,
`proposal.md`, `design.md`, a spec `daily-statistics-production-activation`,
`deploy/exit-reconciliation-scheduler.sh`, os units de saída/estatísticas e a
seção 5c de `deploy/README.md`. Registre o `BASE_REF` e confirme working tree
adequada. Este change é CRÍTICO: não acesse produção, rede real, systemd real,
journal real, dados clínicos ou releases reais durante implementação/testes.

## Objetivo

Entregar um preflight host-level fail-closed que somente consulta procedência,
configuração e evidência agregada já existente, sem alterar estado.

## Requisitos verificáveis

- **R1:** exige tag publicada imutável e bytes locais iguais aos assets da mesma
  tag para imagem, scheduler, preflight e units relevantes.
- **R2:** lê apenas `SIRHOSP_VERSION` e `STATISTICS_ACTIVATION_DATE` do `.env`,
  recusa ambiguidades e exige data estritamente futura em `America/Bahia`.
- **R3:** exige timer diário desabilitado/inativo; timers upstream
  habilitados/ativos; sucesso horário em até duas horas e D-1 em até trinta.
- **R4:** consulta journal silenciosamente e emite somente chaves técnicas
  allowlisted, nunca mensagens brutas, credenciais ou identidade clínica.
- **R5:** não contém ação de enable/start/restart, Docker, Django, extração,
  materialização, banco ou backfill.
- **R6:** testes usam somente fixtures, diretórios temporários e command doubles.

## Escopo e blast radius

```yaml
expected_files:
  - deploy/daily-statistics-activation-preflight.sh
  - tests/unit/test_daily_statistics_activation_preflight.py
allowed_incidental_files: []
out_of_scope:
  - .github/workflows/publish-release-image.yml
  - deploy/README.md
  - units systemd existentes
  - apps Django e banco
  - qualquer comando ou dado de produção
```

Limite: dois arquivos. Pare e reporte se for necessário alterar runtime clínico,
schema, unit ou dependência do projeto.

## Matriz requisito -> arquivo -> teste/check

| Requisito | Arquivo | Evidência |
| --- | --- | --- |
| R1–R4 | script | testes executáveis com release/host sintéticos |
| R5 | script/teste | inspeção estática de comandos proibidos |
| R6 | teste | doubles sem subprocesso externo real |

## Plano de testes

### RED

Crie primeiro o teste e execute:

```bash
./scripts/test-in-container.sh unit \
  tests/unit/test_daily_statistics_activation_preflight.py
```

Falha esperada: preflight inexistente ou contratos ainda ausentes. Registre a
falha antes da implementação.

### GREEN / verificação local

Implemente o mínimo e repita o teste focado. Depois execute:

```bash
bash -n deploy/daily-statistics-activation-preflight.sh
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
```

Os testes devem substituir `curl`, `systemctl` e `journalctl`; nunca apontar para
`/etc/systemd/system`, `/srv/apps/prisma` ou GitHub reais.

## Critérios de aceitação

- [ ] R1–R6 possuem cobertura objetiva.
- [ ] Falhas são fechadas e têm motivos técnicos enumerados.
- [ ] Saída de sucesso/falha não contém mensagem bruta nem PHI.
- [ ] Nenhuma operação de produção, extração ou materialização ocorreu.
- [ ] Relatório `/tmp/sirhosp-slice-PDSPA-S1-report.md` foi criado.
