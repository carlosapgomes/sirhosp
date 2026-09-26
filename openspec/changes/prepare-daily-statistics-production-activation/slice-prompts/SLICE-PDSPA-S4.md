# SLICE-PDSPA-S4 — Gate final e parada operacional

## Handoff de entrada

Você inicia com contexto zero após PDSPA-S3 aceito. Leia `AGENTS.md`, todos os
artefatos do change, os três relatórios PDSPA anteriores e o diff completo desde
o `BASE_REF`. Este é um gate de validação e inspeção; não implemente feature,
não crie release/tag e não opere produção.

## Objetivo

Executar uma única vez o gate global, confirmar os contratos de segurança e
entregar evidência consolidada para aceite humano antes de qualquer release ou
ativação.

## Requisitos verificáveis

- **R1:** integração relevante, quality gate, Markdown, OpenSpec strict e diff
  check passam.
- **R2:** diff não contém PHI, credenciais, dado real ou alteração de fonte
  clínica.
- **R3:** preflight não habilita/inicia services, não chama Docker/Django, não
  executa extrator/materialização/backfill e não imprime journal bruto.
- **R4:** workflow valida/anexa todos os assets antes do draft e não muta release
  publicada.
- **R5:** runbook exige checkpoint humano e não apresenta preflight como
  autorização automática.
- **R6:** nenhuma operação externa de tag, release, GHCR, systemd ou produção é
  executada neste slice.

## Escopo e blast radius

```yaml
expected_files: []
allowed_incidental_files:
  - openspec/changes/prepare-daily-statistics-production-activation/tasks.md
out_of_scope:
  - qualquer código novo ou correção não autorizada
  - GitHub/GHCR, tag, release, systemd e produção
  - backfill, extração ou materialização real
```

Se o gate encontrar defeito, pare e reporte em vez de ampliar este slice.

## Plano de validação

Execute com isolamento Docker próprio:

```bash
./scripts/test-in-container.sh integration
./scripts/test-in-container.sh quality-gate
./scripts/markdown-lint.sh
openspec validate prepare-daily-statistics-production-activation --strict
git diff --check
```

Faça inspeção estática explícita de comandos mutáveis, PHI/credenciais, assets,
ordem do workflow e ausência de operações externas.

## Critérios de aceitação

- [ ] R1–R6 comprovados.
- [ ] Todas as tasks estão concluídas ou o bloqueio está documentado.
- [ ] Relatório `/tmp/sirhosp-slice-PDSPA-S4-report.md` foi criado.
- [ ] Execução para antes de tag, release, instalação ou ativação.
