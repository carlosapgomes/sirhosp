<!-- markdownlint-disable MD013 -->

# Prompt Slice S1.5 (LLM Executor)

## Handoff de entrada (contexto zero)

Você inicia este slice sem contexto prévio.

Antes de codar, leia obrigatoriamente:

1. `AGENTS.md`
2. `PROJECT_CONTEXT.md`
3. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/proposal.md`
4. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/design.md`
5. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/specs/**/*.md`
6. `openspec/changes/fase-a-integracao-playwright-ingestao-sob-demanda/tasks.md`
7. `/tmp/sirhosp-slice-S1-report.md`
8. Este arquivo (`slice-prompts/SLICE-S1-5.md`)

## Objetivo do slice

Corrigir pontos críticos encontrados após revisão de S1 para garantir segurança de integração antes da orquestração assíncrona do S2.

## Escopo permitido

- Ajustar normalização do extractor para incluir `patient_source_key` com base em `patient_record`.
- Padronizar formato de data de entrada do adapter para o contrato interno (`YYYY-MM-DD`) com conversão explícita para o formato esperado pelo `path2.py` (`DD/MM/YYYY`).
- Validar campos obrigatórios de cada item do JSON extraído e falhar com erro tipado quando faltarem campos essenciais.
- Ajustar/expandir testes unitários existentes do extractor para cobrir os cenários acima.

## Limites rígidos

- Máximo de **6 arquivos alterados**.
- Não iniciar worker, fila, transição de estados ou qualquer item do S2.
- Não alterar UI.
- Não introduzir Celery/Redis.
- Não usar dados reais.

## TDD obrigatório (red -> green -> refactor)

1. Criar testes falhando para os três problemas-alvo:
   - propagação de `patient_source_key`;
   - compatibilidade/conversão de datas;
   - validação de campos obrigatórios por item.
2. Implementar mínimo necessário para passar.
3. Refatorar sem ampliar escopo.

## Critérios de aceite

- `patient_source_key` presente no payload normalizado consumido pela ingestão.
- Datas passadas ao subprocesso no formato esperado pelo extractor externo, com regra documentada e testada.
- JSON inválido por ausência de campos obrigatórios falha com erro de domínio explícito.
- Testes unitários do extractor passando.
- `uv run python manage.py check` sem erro.

## Comandos mínimos de validação

```bash
uv run python manage.py check
uv run pytest -q tests/unit/test_evolution_extractor.py
uv run ruff check config apps tests manage.py
```

## Handoff de saída obrigatório

Gerar relatório em:

- `/tmp/sirhosp-slice-S1-5-report.md`

Estrutura obrigatória do relatório:

1. Resumo executivo.
2. Checklist de aceite.
3. Arquivos alterados.
4. Fragmentos de código antes/depois por arquivo alterado.
5. Comandos executados e resultados.
6. Riscos remanescentes e recomendação para iniciar S2.

Também atualizar `tasks.md` marcando apenas itens do S1.5 concluídos.
