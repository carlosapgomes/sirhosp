# SLICE-PDSPA-S3 — Checkpoint humano e runbook

## Handoff de entrada

Você inicia com contexto zero após PDSPA-S2 aceito. Leia `AGENTS.md`,
`PROJECT_CONTEXT.md`, todos os artefatos deste change, o preflight entregue, a
seção 5c de `deploy/README.md` e os relatórios PDSPA-S1/S2 em `/tmp`. Não opere
produção e não execute nenhum comando documentado contra host real.

## Objetivo

Documentar o fluxo reproduzível de download por tag, instalação desabilitada,
preflight, aceite humano, ativação explícita posterior, observação e rollback.

## Requisitos verificáveis

- **R1:** runbook baixa preflight e units da mesma tag imutável e instala sem
  habilitar/iniciar.
- **R2:** execução documentada do preflight ocorre antes do aceite humano e da
  ativação; evidência expirada exige nova execução.
- **R3:** não há bypass de falha, disparo artificial de extratores ou cópia de
  journal bruto; evidência persistível é somente agregada.
- **R4:** ativação permanece comando manual separado e exige data futura.
- **R5:** observação usa estados/contagens sem PHI; rollback toca apenas os dois
  units de estatísticas e preserva relatórios/fontes/cadências upstream.
- **R6:** documentação não afirma ausência de sobreposição entre workflows.

## Escopo e blast radius

```yaml
expected_files:
  - deploy/README.md
  - tests/unit/test_deploy_daily_statistics_runtime.py
allowed_incidental_files: []
out_of_scope:
  - script de preflight
  - workflow de release
  - units e calendários
  - código Django ou banco
  - produção, systemctl real, backfill ou extração
```

Limite: dois arquivos. Pare se a documentação revelar necessidade de alterar
contrato, horário, lock ou semântica já aprovada.

## Matriz requisito -> arquivo -> teste/check

| Requisito | Arquivo | Evidência |
| --- | --- | --- |
| R1–R5 | runbook | asserts estáticos de ordem, comandos e proibições |
| R6 | runbook/teste | rejeição de alegação absoluta de não sobreposição |

## Plano de testes

### RED

Adicione primeiro os asserts de runbook e execute:

```bash
./scripts/test-in-container.sh unit \
  tests/unit/test_deploy_daily_statistics_runtime.py
```

Falha esperada: seção 5c ainda descreve inspeção manual e informa que os assets
não são publicados. Registre a falha.

### GREEN / verificação local

Atualize somente a seção operacional necessária e repita o teste focado. Depois:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/markdown-lint.sh
openspec validate prepare-daily-statistics-production-activation --strict
```

## Critérios de aceitação

- [ ] R1–R6 cobertos por teste/inspeção.
- [ ] Instalação, evidência e ativação são etapas separadas.
- [ ] Não existe bypass ou instrução que exponha journal clínico.
- [ ] Nenhuma ação de produção foi executada.
- [ ] Relatório `/tmp/sirhosp-slice-PDSPA-S3-report.md` foi criado.
