# Preflight — relatório estatístico diário

## Referência e escopo

- Change: `add-daily-statistics-reporting`.
- `BASE_REF`: `a7e30d0fa8107a4f59557ff3f57bbeb0eea316cf`.
- Branch na captura: `master`.
- Commit: `a7e30d0 docs(release): rc.30 evidence pack`.
- Captura: 2026-09-24, fuso local `America/Bahia`.

Antes da criação da ADR, `git status --short --untracked-files=all` não
apresentava alterações rastreadas. Os artefatos do change já existiam, mas o
padrão `openspec/changes/*/` em `.gitignore` os oculta; eles precisarão de
`git add -f` quando o change for versionado.

Este preflight não executou comandos de produção, não fez backfill, não acessou
nem criou dados reais de pacientes e não ativou serviço, timer ou rota. O gate
utilizou exclusivamente a base de testes em container e fixtures sintéticas.

## Baseline validado

Comando oficial executado:

```bash
SIRHOSP_TEST_PROJECT=sirhosp-statistics-preflight \
  SIRHOSP_TEST_DB_PORT=55434 \
  ./scripts/test-in-container.sh quality-gate
```

Resultado:

- Django check: passou, sem issues.
- Unitários: `3601 passed`, com `492 warnings` preexistentes.
- Ruff: passou.
- Mypy: passou em 416 arquivos, somente com notas informativas.
- Resultado agregado: exit code 0.

A primeira tentativa na porta padrão `55433` foi bloqueada antes dos gates
porque `ats-web-test-db-1`, de outro projeto, já ocupava a porta. Uma tentativa
seguinte encontrou o container parado criado pela primeira tentativa; apenas
esse container do preflight foi removido. O gate foi então repetido com projeto
e porta isolados, sem alterar o container externo.

## Decisão arquitetural

A decisão exigida pelo preflight foi aceita em
`docs/adr/ADR-0011-projecao-diaria-materializada-e-versionada-para-relatorios-estatisticos.md`.
Ela cobre o read model materializado e versionado, limites de autoridade das
fontes, autorização para dados sensíveis, auditoria de exportação, revisões
automáticas, ativação sem backfill e rollback sem alteração clínica.
