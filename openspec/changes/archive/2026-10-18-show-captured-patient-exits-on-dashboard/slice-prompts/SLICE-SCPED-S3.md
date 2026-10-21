# SLICE-SCPED-S3 — Comparativo protegido de qualidade

## Handoff de entrada

Você inicia com contexto zero no repositório SIRHOSP. Leia `AGENTS.md`,
`PROJECT_CONTEXT.md`, os artefatos deste change e os relatórios S1/S2 em
`/tmp`. Confirme ambos concluídos. Implemente somente este slice com TDD. Não
acesse produção nem execute backfill.

## Objetivo

Preservar fora do gráfico principal uma visão agregada para revisão de qualidade
que compare saídas capturadas, saídas canônicas reconciliadas e sumários
médicos, usando a superfície e permissão existentes de reconciliação.

## Requisitos verificáveis

- **R1:** somente usuário com `review_reconciliation_cases` acessa o comparativo.
- **R2:** o payload agregado contém, no período explícito, contagens por dia de
  `saida_em`, saídas canônicas reconciliadas e `alta_em`.
- **R3:** todas as datas usam `America/Bahia` e o eixo é consecutivo.
- **R4:** o payload, template e logs não contêm nome, prontuário, admission key ou
  texto clínico.
- **R5:** nenhuma regra, status, evento ou internação é alterado pela leitura.
- **R6:** ADR-0009 distingue a métrica gerencial de evidência da métrica
  canônica de domínio sem enfraquecer o reconciliador.

## Escopo e blast radius

```yaml
expected_files:
  - apps/services_portal/views.py
  - apps/services_portal/templates/services_portal/reconciliation_queue.html
  - tests/integration/test_reconciliation_review_http.py
  - docs/adr/ADR-0009-reconciliacao-canonica-de-saidas-e-identidade-longitudinal-de-internacoes.md
allowed_incidental_files: []
out_of_scope:
  - nova rota pública
  - models, migrations, comandos de backfill, produção
```

Limite de quatro arquivos. Pare se for necessária nova permissão, novo endpoint
ou persistência.

## Plano de testes

### RED

Adicione testes R1–R5 e execute:

```bash
./scripts/test-in-container.sh integration \
  tests/integration/test_reconciliation_review_http.py
```

### GREEN

Implemente o mínimo, repita o teste focado e execute:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/markdown-lint.sh
```

## Critérios de aceitação

- [ ] Comparativo agregado protegido e sem identidade.
- [ ] Gráfico principal continua contendo somente `saida_em`.
- [ ] Reconciliação permanece read-only nesta superfície.
- [ ] ADR-0009 atualizada e Markdown lint verde.
- [ ] Relatório criado em `/tmp/sirhosp-slice-SCPED-S3-report.md`.
