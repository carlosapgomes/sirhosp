# Proposal

## Why

A feature de pendências (`track-inpatient-pending-items`, commits `7eadffe`..`2e5382f`) só possui verification na suíte isolada de integração (browser real contra `live_server` com fixtures sintéticas). O skill assistido `verify-sirhosp` — camada complementar que dirige o **portal dev implantado** (release, gunicorn/edge/TLS, dataset dev do pipeline) — não mapeia a feature. Mapeá-la em nível somente leitura dá assurance de release barato: prova que as superfícies novas sobrevivem ao deploy e se comportam com o dataset operacional, sem alterar a política business-read-only da suíte.

## What Changes

- Novo feature map `pending-items.md` (somente leitura, status honesto `future` para MCP): painel `/pendencias/` via menu `Pendências`, alternância de visões, filtros GET, indicadores, histórico recolhível e página contextual por internação; jornada explicitamente na perspectiva de leitor (`verify_user` não pertence ao grupo `Desospitalização`).
- `features/README.md`: entrada no índice + extensão das listas de rotas (leituras autorizadas e proibições).
- `SKILL.md`: disciplinas de rota dos passos "Drive" atualizadas (novas leituras permitidas; `export.xlsx` e superfícies de escrita proibidas mesmo como GET).

### Fora de escopo

- Escritas (criar/editar/finalizar), download XLSX e qualquer mudança na allowlist/política da suíte (`dev-browser-verification` intocada).
- Runner `scripts/verify_portal.py` (S2) e feature ids dele.
- Execução de um round MCP agora: o mapa nasce `future`; demonstrar exige janela dev autorizada, dataset fictício confirmado e workers parados.

## Capabilities

### New Capabilities

Nenhuma — mudança de conteúdo operacional do skill, sem alteração de comportamento especificado (`skip_specs: true`).

### Modified Capabilities

Nenhuma.

## Impact

- Apenas documentação do skill (3 arquivos em `.pi/skills/verify-sirhosp/`).
- Sem código, migrations, dependências ou gates afetados; validação por markdown lint e conferência mecânica de handles/rotas contra o código.
