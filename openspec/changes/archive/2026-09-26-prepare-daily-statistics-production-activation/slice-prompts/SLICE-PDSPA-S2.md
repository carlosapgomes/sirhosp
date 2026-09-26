# SLICE-PDSPA-S2 — Assets na release imutável

## Handoff de entrada

Você inicia com contexto zero após PDSPA-S1 aceito. Leia `AGENTS.md`,
`PROJECT_CONTEXT.md`, `proposal.md`, `design.md`, a delta spec
`release-image-hospital-deploy`, `.github/workflows/publish-release-image.yml`,
os testes atuais de release e o relatório `/tmp/sirhosp-slice-PDSPA-S1-report.md`.
Não crie tag, draft, imagem, release nem execute GitHub Actions.

## Objetivo

Fazer a release validar e anexar o preflight e os dois units de estatísticas na
mesma criação de draft que precede a publicação da imagem.

## Requisitos verificáveis

- **R1:** os três novos assets são verificados com `test -f` antes de
  `gh release create`.
- **R2:** preflight e units são argumentos da única criação do draft.
- **R3:** draft completo continua anterior ao build/push da imagem e à
  publicação.
- **R4:** asset ausente interrompe o workflow sem release parcial.
- **R5:** nenhuma etapa posterior adiciona, substitui ou edita assets.
- **R6:** contratos existentes de release estável/prerelease permanecem iguais.

## Escopo e blast radius

```yaml
expected_files:
  - .github/workflows/publish-release-image.yml
  - tests/unit/test_release_hospital_deploy.py
  - tests/unit/test_deploy_daily_statistics_runtime.py
allowed_incidental_files: []
out_of_scope:
  - deploy/README.md
  - conteúdo do preflight ou dos units
  - GitHub, GHCR e produção reais
  - tags, drafts, imagens ou releases reais
```

Limite: três arquivos. Pare se a solução exigir novo workflow, credencial,
dependência ou mutação posterior de release.

## Matriz requisito -> arquivo -> teste/check

| Requisito | Arquivo | Evidência |
| --- | --- | --- |
| R1–R5 | workflow | testes estáticos de ordem e conjunto de assets |
| R6 | testes de release existentes | regressão focada |

## Plano de testes

### RED

Ajuste primeiro os testes de contrato e execute:

```bash
./scripts/test-in-container.sh unit \
  tests/unit/test_release_hospital_deploy.py \
  tests/unit/test_deploy_daily_statistics_runtime.py
```

Falha esperada: workflow ainda omite os três assets. Registre a falha.

### GREEN / verificação local

Atualize somente o workflow e repita o teste focado. Depois execute:

```bash
./scripts/test-in-container.sh check
./scripts/test-in-container.sh lint
./scripts/test-in-container.sh typecheck
./scripts/markdown-lint.sh
```

Não invoque `gh`, `docker buildx`, `git tag` ou o workflow.

## Critérios de aceitação

- [ ] R1–R6 cobertos pelos testes.
- [ ] Draft continua completo e anterior à publicação da imagem.
- [ ] Nenhuma release/tag/imagem foi criada ou alterada.
- [ ] Relatório `/tmp/sirhosp-slice-PDSPA-S2-report.md` foi criado.
