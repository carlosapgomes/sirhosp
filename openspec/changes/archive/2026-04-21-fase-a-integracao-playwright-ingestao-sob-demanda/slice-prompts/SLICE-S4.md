
# Prompt Slice S4 (LLM Executor)

## Handoff de entrada (contexto zero)

Você inicia este slice sem contexto prévio.

Antes de codar, leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/proposal.md`
4. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/design.md`
5. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/specs/**/*.md`
6. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/tasks.md`
7. `/tmp/sirhosp-slice-S3-report.md` (se existir)
8. Este arquivo (`slice-prompts/SLICE-S4.md`)

## Objetivo do slice

Entregar superfície mínima de produto para demo: trigger de ingestão sob demanda e consulta de status da run.

## Escopo permitido

- Endpoint/view para criação de run sob demanda.
- Endpoint/view para leitura de status operacional.
- Mensagens de feedback claras para: sucesso, em processamento e falha.
- Testes de integração HTTP do fluxo.

## Limites rígidos

- Máximo de **10 arquivos alterados**.
- Não implementar dashboard completo.
- Não introduzir front-end complexo além do necessário para demo.
- Não implementar novas regras de negócio de ingestão (somente orquestração/entrega).

## Protocolo obrigatório de execução (sem pular etapas)

1. **Red obrigatório**
   - Criar teste de integração HTTP falhando para:
     - criar run;
     - consultar status.
2. **Green obrigatório**
   - Implementar o mínimo para passar mantendo payload simples e rastreável.
3. **Refactor controlado**
   - Melhorar nomenclatura/organização sem ampliar escopo.
4. **Verificação anti-drift**
   - Executar `makemigrations --check --dry-run`.

## Critérios de aceite (gate de saída)

Só considere o slice concluído se **todos** os itens abaixo forem verdadeiros:

- Usuário consegue abrir run com registro+período.
- Usuário consegue consultar status com contadores e timestamps mínimos.
- Mensagens de falha preservam rastreabilidade sem esconder erro operacional.
- `uv run python manage.py makemigrations --check --dry-run` passa.
- `uv run python manage.py check` sem erro.
- Testes de integração HTTP relevantes passam.
- `uv run ruff check config apps tests manage.py` sem erro.
- `tasks.md` atualizado apenas no bloco do S4.

## Comandos mínimos de validação

```bash
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run pytest -q tests/integration tests/unit
uv run ruff check config apps tests manage.py
```

## Handoff de saída obrigatório

Gerar relatório em:

- `/tmp/sirhosp-slice-S4-report.md`

Estrutura obrigatória do relatório:

1. Resumo executivo.
2. Evidência TDD (red -> green).
3. Arquivos alterados.
4. Antes/depois de rotas/views/templates (apenas trechos alterados).
5. Exemplos de request/response do fluxo de criação e status.
6. Comandos executados com resultado (exit code + resumo).
7. Auto-auditoria final (escopo respeitado e limites atendidos).
