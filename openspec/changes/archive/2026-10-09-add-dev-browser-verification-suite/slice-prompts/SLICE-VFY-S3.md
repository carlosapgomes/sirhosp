# SLICE-VFY-S3 — Skill assistida por MCP e catálogo inicial

## Handoff de entrada e objetivo

Leia AGENTS.md e PROJECT_CONTEXT.md. S1/S2 devem estar aceitos.
Entregue somente a skill .pi/skills/verify-sirhosp e seu mapa inicial.
Ela ensina outro executor com contexto zero a dirigir o dev real, produzir
evidências e fechar a sessão. Não escrever outra implementação de login.

## Contexto mínimo

- ../design.md D3, D4, D6–D9 e ../specs/dev-browser-verification/spec.md.
- docs/dev-verification.md, scripts/verify_portal.py e driver de S2.
- Templates de login, sidebar, topbar_sync, base_sidebar e censo.
- /home/dev/.agents/skills/create-verification-skill/SKILL.md e seu diretório
  references/feature-map-example, como referência de formato; se indisponível,
  reportar e usar o contrato explícito abaixo, sem buscar pacotes novos.
- Metadados das ferramentas Chrome DevTools MCP disponíveis na sessão.
  Confirmar contratos reais antes de chamar ferramentas; não assumir
  disponibilidade de browser só porque o catálogo existe.

../ é relativo ao prompt; outros caminhos do projeto são relativos ao repo.
Nenhuma senha permanente é necessária: open emite credenciais efêmeras somente
para a sessão ativa, com aceitação consciente de histórico temporário.

## Requisitos verificáveis

- R1: SKILL.md com frontmatter válido name verify-sirhosp e descrição específica.
  Seções Launch, Doctor, Drive, Evidence, Cleanup e Helpers.
- R2: README do mapa e quatro features: autenticação, navegação, censo e HTMX.
  Cada feature contém Sub-features, How to get to it (user POV),
  Driving it with Chrome DevTools MCP e Gotchas; liga ações a end states.
- R3: operações e seletores concretos do repo, comandos de S1/S2 e modos
  implementados vs futuros explícitos; nenhum comando inventado como existente.
- R4: contexto MCP exclusivo por run/papel, alvo dev confirmado, leitura de
  negócio e proibição das rotas mutantes. Não tratar a skill como firewall
  ou fingir que ela aplica o interceptor de requests do Playwright.
- R5: demonstrar pelo menos autenticação end-to-end usando open, UI real,
  navegação, screenshots/observações, logout e close; reprovar sessão pessoal
  reutilizada, contexto sem isolamento ou falta de MCP.
- R6: evidências continuam existentes após cleanup; contas owned revogadas,
  timer cancelado e páginas criadas encerradas sem afetar páginas do operador.
  Limitações da API para última página/contexto exigem diagnóstico honesto.
- R7: documentar manutenção: alteração de rota/template pede atualização do
  mapa e prova; expansão para operações mutantes demanda outro escopo.
  Informar próximos candidatos, sem declarar verificados casos não executados.

## Escopo e limite de arquivos

Máximo sete arquivos documentais abaixo, mais tasks/relatório do controller.
Não criar extensão Pi/MCP, mudar configuração de browser, app ou source code.

```yaml
expected_files:
  - .pi/skills/verify-sirhosp/SKILL.md
  - .pi/skills/verify-sirhosp/features/README.md
  - .pi/skills/verify-sirhosp/features/authentication.md
  - .pi/skills/verify-sirhosp/features/navigation.md
  - .pi/skills/verify-sirhosp/features/census.md
  - .pi/skills/verify-sirhosp/features/htmx.md
  - docs/dev-verification.md
allowed_incidental_files: []
out_of_scope:
  - .pi/mcp.json, .pi-web, browser pessoal e infraestrutura
  - nova CLI/framework/MCP, alterações de driver ou auth
  - transações de negócio e novos dados clínicos
```

## RED, GREEN e prova documental

Este é um slice documental executável. RED: checklist R1–R7 não pode ser
cumprido porque a skill/mapa ainda não existem; registrar evidência da ausência.
Não criar teste artificial de existência de arquivo só para simular TDD.
Se precisar de código de comportamento novo, STOP e proponha outro slice.

GREEN: criar os documentos, validar frontmatter/links/seletores, executar
literalmente o roteiro R5 e confirmar R6. Draft nunca executado não é entrega.
Não inserir senha temporária nas evidências ou no relato; o uso em argumentos
de ferramentas MCP durante a sessão é o tradeoff aceito, não segredo permanente.

## Validação e aceite

- Markdownlint de todos os arquivos criados/alterados sem suppressions.
  O script do projeto exclui .pi; executar também explicitamente:

  ```bash
  npx --yes markdownlint-cli2 --config .markdownlint-cli2.yaml \
    '.pi/skills/verify-sirhosp/**/*.md' docs/dev-verification.md
  ```

- openspec validate add-dev-browser-verification-suite --strict.
- Prova MCP real R5/R6, com path dos artefatos após cleanup.
- Não repetir suíte global neste slice documental sem motivo; o gate final
  do change a executará uma vez após a aceitação de S3.
- [ ] R1–R7 cumpridos, mapa honesto e comandos reais comprovados.
- [ ] Nenhuma sessão/conta ativa deixada; evidências sobreviveram.
- [ ] Relatório /tmp/sirhosp-slice-VFY-S3-report.md com antes/depois documental,
  comandos, provas, capacidades indisponíveis e próximo passo.

O controller decide gates/review autorizados e atualiza tasks depois de aceite.
Não invocar subagents sem autorização nem fazer push. STOP ao final.
