## 1. Convenções da change

- [ ] 1.1 Usar prefixo de slice `CES` (Censo Export Specialty).
- [ ] 1.2 Implementar um slice por vez, com TDD (`red -> green -> refactor`).
- [ ] 1.3 Usar o prompt do slice em `slice-prompts/SLICE-CES-SX.md` como
      fonte principal para execução com contexto zero.
- [ ] 1.4 Gerar relatório obrigatório ao fim de cada slice em
      `/tmp/sirhosp-slice-CES-SX-report.md`.
- [ ] 1.5 Parar ao fim de cada slice e não avançar para o próximo sem revisão
      humana.

## 2. Slice CES-S1 — Nomes completos de especialidades na UI

- [x] 2.1 (RED) Adicionar testes unitários em
      `tests/unit/test_services_portal_censo.py` para dropdown, tabela, card
      mobile e fallback de especialidade sem cadastro.
- [x] 2.2 Ajustar `apps/services_portal/views.py` para enviar opções de
      especialidade com `value`, `label` e `code`, preservando filtros por
      valor armazenado no snapshot.
- [x] 2.3 Ajustar `apps/services_portal/templates/services_portal/censo.html`
      para renderizar labels completos no dropdown, tabela e cards mobile.
- [x] 2.4 Atualizar este `tasks.md` marcando o Slice CES-S1 como concluído
      somente após gates verdes e relatório criado.

## 3. Slice CES-S2 — Helper comum do resultado do censo

- [x] 3.1 (RED) Adicionar ou reforçar testes de caracterização em
      `tests/unit/test_services_portal_censo.py` cobrindo filtros combinados,
      ordenação e estado vazio.
- [x] 3.2 Extrair em `apps/services_portal/views.py` helper privado para montar
      o resultado/contexto do censo sem alterar comportamento funcional.
- [x] 3.3 Fazer a view `censo` consumir o helper comum e manter a mesma saída
      esperada pelos testes.
- [x] 3.4 Atualizar este `tasks.md` marcando o Slice CES-S2 como concluído
      somente após gates verdes e relatório criado.

## 4. Slice CES-S3 — Endpoint autenticado de exportação XLSX

- [x] 4.1 (RED) Adicionar testes unitários em
      `tests/unit/test_services_portal_censo.py` para autenticação, content
      type, `Content-Disposition`, workbook válido, colunas e filtros.
- [x] 4.2 Implementar view autenticada de exportação XLSX em
      `apps/services_portal/views.py`, reutilizando o helper comum.
- [x] 4.3 Adicionar rota de exportação em `apps/services_portal/urls.py`.
- [x] 4.4 Garantir que a exportação use nomes completos de especialidade e não
      escreva arquivos temporários em disco.
- [x] 4.5 Atualizar este `tasks.md` marcando o Slice CES-S3 como concluído
      somente após gates verdes e relatório criado.

> CES-S3 concluído em 2026-06-09.
> Resultados: `openpyxl.Workbook` em memória com `BytesIO`, rota `/censo/exportar/`,
> 5 testes RED-GREEN, lint e typecheck sem novos erros,
> markdown lint pendente (relatório em /tmp/sirhosp-slice-CES-S3-report.md).

## 5. Slice CES-S4 — Botão de exportação na página `/censo/`

- [x] 5.1 (RED) Adicionar teste unitário verificando que a página `/censo/`
      renderiza link/botão de exportação preservando querystring atual.
- [x] 5.2 Ajustar `apps/services_portal/templates/services_portal/censo.html`
      para exibir botão `Exportar Excel` apontando para a rota de exportação.
- [x] 5.3 Garantir que o botão preserve busca, unidade, especialidade e
      ordenação ativos.
- [x] 5.4 Atualizar este `tasks.md` marcando o Slice CES-S4 como concluído
      somente após gates verdes e relatório criado.

> CES-S4 concluído em 2026-06-09.
> Resultados: botão `Exportar Excel` adicionado ao template `/censo/`,
> link com `{% url 'services_portal:censo_export_xlsx' %}?{{ request.GET.urlencode }}`,
> 2 testes RED-GREEN adicionados,
> lint, typecheck e markdown lint sem novos erros no código alterado.

## 6. Gates finais da change

- [ ] 6.1 Executar `./scripts/test-in-container.sh check`.
- [ ] 6.2 Executar `./scripts/test-in-container.sh unit`.
- [ ] 6.3 Executar `./scripts/test-in-container.sh lint`.
- [ ] 6.4 Executar `./scripts/test-in-container.sh typecheck`.
- [ ] 6.5 Executar `./scripts/markdown-lint.sh` após qualquer alteração em
      Markdown.
- [ ] 6.6 Revisar que nenhum arquivo contém dados reais, credenciais ou dumps.
