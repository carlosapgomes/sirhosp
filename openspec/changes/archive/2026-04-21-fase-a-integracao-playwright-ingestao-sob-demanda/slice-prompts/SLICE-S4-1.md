<!-- markdownlint-disable MD013 -->
# Prompt Slice S4.1 (LLM Executor)

## Handoff de entrada (contexto zero)

Você inicia este slice sem contexto prévio.

Antes de codar, leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/tasks.md`
4. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/slice-prompts/SLICE-S4.md`
5. `/tmp/sirhosp-slice-S4-report.md`
6. Este arquivo (`slice-prompts/SLICE-S4-1.md`)

## Objetivo do slice

Eliminar acesso público indevido ao fluxo de ingestão sob demanda, exigindo autenticação para criação de run e consulta de status.

## Escopo permitido

- Proteger endpoints `ingestion:create_run` e `ingestion:run_status` com autenticação obrigatória.
- Garantir redirecionamento de anônimo para `LOGIN_URL` com parâmetro `next`.
- Atualizar testes HTTP do S4 para executar com usuário autenticado nos cenários de sucesso.
- Adicionar testes explícitos para confirmar bloqueio de acesso anônimo.
- Manter endpoint `/health/` público e inalterado.

## Limites rígidos

- Máximo de **8 arquivos alterados**.
- Não alterar regras de negócio de ingestão.
- Não alterar worker, gap planner ou extractor.
- Não criar/implementar sistema de permissões por perfil neste slice.
- Não alterar outros endpoints além do necessário para este hardening.

## Protocolo obrigatório de execução (sem pular etapas)

1. **Red obrigatório**
   - Criar testes de acesso anônimo para `create_run` e `run_status` esperando redirecionamento para login.
   - Executar testes e registrar falha inicial.
2. **Green obrigatório**
   - Aplicar proteção de autenticação nos endpoints.
   - Ajustar testes de sucesso para login prévio de usuário.
3. **Refactor controlado**
   - Melhorar clareza sem ampliar escopo.
4. **Verificação anti-drift**
   - Executar `makemigrations --check --dry-run`.

## Critérios de aceite (gate de saída)

Só considere o slice concluído se **todos** os itens abaixo forem verdadeiros:

- Usuário anônimo não acessa `ingestion:create_run` nem `ingestion:run_status`.
- Usuário autenticado mantém fluxo S4 funcionando (cria run, consulta status, vê mensagens).
- Redirecionamento de anônimo inclui `next=<url original>`.
- `/health/` continua público.
- `uv run python manage.py makemigrations --check --dry-run` passa.
- `uv run python manage.py check` sem erro.
- `uv run pytest -q tests/integration/test_ingestion_http.py tests/unit/test_health.py` passa.
- `uv run ruff check config apps tests manage.py` sem erro.
- `tasks.md` atualizado apenas no bloco do S4.1.

## Comandos mínimos de validação

```bash
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run pytest -q tests/integration/test_ingestion_http.py tests/unit/test_health.py
uv run ruff check config apps tests manage.py
```

## Handoff de saída obrigatório

Gerar relatório em:

- `/tmp/sirhosp-slice-S4-1-report.md`

Estrutura obrigatória do relatório:

1. Resumo executivo.
2. Evidência TDD (red -> green) com saída dos testes de acesso anônimo.
3. Arquivos alterados.
4. Antes/depois das proteções de autenticação nas views/rotas.
5. Evidência de redirecionamento com `next`.
6. Evidência de que `/health/` permaneceu público.
7. Comandos executados com resultado (exit code + resumo).
8. Auto-auditoria final (escopo respeitado e limites atendidos).
