
# Prompt Slice S3 (LLM Executor)

## Handoff de entrada (contexto zero)

Você inicia este slice sem contexto prévio.

Antes de codar, leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/proposal.md`
4. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/design.md`
5. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/specs/**/*.md`
6. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/tasks.md`
7. `/tmp/sirhosp-slice-S2-report.md`
8. `/tmp/sirhosp-slice-S2-1-report.md` (se existir)
9. Este arquivo (`slice-prompts/SLICE-S3.md`)

## Objetivo do slice

Implementar política cache-first com cálculo de lacunas temporais para extrair somente períodos faltantes.

## Escopo permitido

- Serviço de cálculo de cobertura temporal por paciente/período.
- Planejamento de lacunas a extrair.
- Integração com worker de runs sob demanda.
- Persistência de informação mínima das lacunas processadas no contexto da run.
- Testes unitários/integração para cenários com cobertura total, parcial e nula.

## Limites rígidos

- Máximo de **8 arquivos alterados**.
- Não ampliar escopo para sincronização diária de internados.
- Não alterar regras de domínio não relacionadas a cobertura temporal.
- Não alterar UI/rotas neste slice.

## Protocolo obrigatório de execução (sem pular etapas)

1. **Red obrigatório**
   - Criar testes falhando para os 3 cenários: cobertura total, parcial e nula.
2. **Green obrigatório**
   - Implementar algoritmo mínimo para planejamento de lacunas.
   - Integrar ao worker somente no ponto necessário.
3. **Refactor controlado**
   - Melhorar legibilidade sem ampliar escopo.
4. **Verificação anti-drift**
   - Executar `makemigrations --check --dry-run` para garantir que não esqueceu migração.

## Critérios de aceite (gate de saída)

Só considere o slice concluído se **todos** os itens abaixo forem verdadeiros:

- Cobertura total => run não chama extração externa.
- Cobertura parcial => run extrai apenas lacunas.
- Cobertura nula => run extrai janela inteira solicitada.
- Lacunas processadas ficam rastreáveis no contexto da run.
- `uv run python manage.py makemigrations --check --dry-run` passa.
- `uv run python manage.py check` sem erro.
- Testes relevantes passam.
- `uv run ruff check config apps tests manage.py` sem erro.
- `tasks.md` atualizado apenas no bloco do S3.

## Comandos mínimos de validação

```bash
uv run python manage.py makemigrations --check --dry-run
uv run python manage.py check
uv run pytest -q tests/unit tests/integration
uv run ruff check config apps tests manage.py
```

## Handoff de saída obrigatório

Gerar relatório em:

- `/tmp/sirhosp-slice-S3-report.md`

Estrutura obrigatória do relatório:

1. Resumo executivo.
2. Evidência TDD (quais testes falharam primeiro e quais passaram depois).
3. Arquivos alterados.
4. Antes/depois dos trechos centrais do algoritmo de lacunas.
5. Evidência de que extração não roda quando há cobertura total.
6. Comandos executados com resultado (exit code + resumo).
7. Auto-auditoria final (escopo respeitado, sem mudanças fora do S3).
