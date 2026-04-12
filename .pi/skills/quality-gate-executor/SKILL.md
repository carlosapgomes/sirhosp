---
name: quality-gate-executor
description: Executa os comandos de validação de qualidade definidos no AGENTS.md (testes, lint, type check, build) e reporta resultados estruturados. Inclui script Python autônomo para execução determinística.
---

# Skill: Quality Gate Executor

Este skill executa o pipeline de qualidade do projeto conforme definido no `AGENTS.md`, rodando testes, lint, type check, build e outras verificações. Retorna resultados estruturados para validação antes de commits ou releases.

**Novo:** Inclui script Python autônomo (`quality_gate.py`) para execução determinística e relatórios estruturados.

## Quando usar

- Antes de commitar mudanças significativas
- Como parte do Definition of Done (DoD) de cada slice
- Durante a geração de Release Evidence Packs
- Para validação rápida do estado atual do projeto
- Em integração contínua (localmente, antes de push)

## Comandos de Validação vs Comandos essenciais

- **Comandos de Validação**: comandos usados como gate de qualidade (testes, lint, type check, build/check). Ex.: `python3 -m pytest -q`, `ruff check .`.
- **Comandos essenciais**: comandos operacionais gerais do projeto (setup, run local, migração, testes rápidos/completos). Ex.: `python3 manage.py runserver`, `python3 manage.py migrate --plan`.
- O formato canônico de `AGENTS.md` é:
  - seção `## 2. Comandos de Validacao (Quality Gate)`
  - seção `## 3. Comandos Essenciais (Operacao Local)`
- O script também aceita formatos legados (`Validação` com acento e `2) Comandos essenciais`).
- Em blocos de código, ele executa as linhas de comando detectadas. Se um binário não estiver disponível no ambiente, o item é marcado como `skipped`.

## 🐍 Método Recomendado: Script Python

### Instalação rápida

```bash
# Copiar script para seu projeto
cp quality_gate.py /caminho/do/seu/projeto/

# Ou usar diretamente do diretório do skill
python3 ./quality_gate.py
```

### Uso básico

```bash
# Executar quality gate (formato texto)
python3 quality_gate.py

# Formato JSON (para scripts/CI)
python3 quality_gate.py --format json

# Formato Markdown (para documentação)
python3 quality_gate.py --format markdown

# Modo verboso
python3 quality_gate.py --verbose

# Apenas listar comandos
python3 quality_gate.py --list
```

### Integração com Pi.dev

```bash
# Executar via skill
/skill:quality-gate-executor

# Ou executar script diretamente
!python3 quality_gate.py --format json
```

## 📋 Método Manual (Instruções Textuais)

Use este método se não quiser/puder usar o script Python.

### Comandos padrão (baseados em AGENTS.md)

#### Se AGENTS.md existir

1. Ler seção "Comandos de Validacao" do AGENTS.md
2. Executar cada comando sequencialmente
3. Reportar sucesso/falha com output resumido

#### Se AGENTS.md não existir, padrões comuns

##### Python/Django

```bash
# Testes
pytest -q
python3 -m pytest

# Lint
ruff check .
flake8 .
pylint app/

# Type check
mypy .

# Build/check
python3 manage.py check
python3 -m build
```

##### JavaScript/Node.js

```bash
# Testes
npm test
npm run test

# Lint  
npm run lint
eslint .

# Type check
npm run type-check
tsc --noEmit

# Build
npm run build
```

## Processo de execução

### 1. Detectar stack do projeto

```bash
# Verificar linguagem principal
if [ -f "pyproject.toml" ] || [ -f "requirements.txt" ]; then
  STACK="python"
elif [ -f "package.json" ]; then
  STACK="javascript"
elif [ -f "go.mod" ]; then
  STACK="golang"
elif [ -f "pom.xml" ] || [ -f "build.gradle" ]; then
  STACK="java"
fi
```

### 2. Ler comandos do AGENTS.md (se existir)

```bash
if [ -f "AGENTS.md" ]; then
  # Extrair seção de comandos (simplificado)
  sed -n '/## 2. Comandos de Validacao/,/^## [0-9]/p' AGENTS.md | grep -E "^\s*-\s*\`" | sed 's/.*`\(.*\)`.*/\1/'
fi
```

### 3. Executar comandos com tratamento de erro

Para cada comando:

```bash
echo "▶️ Executando: $command"
if eval "$command"; then
  echo "✅ Sucesso: $command"
else
  echo "❌ Falha: $command"
  FAILED=true
fi
```

### 4. Gerar relatório estruturado

```markdown
# Quality Gate Report

**Data:** $(date)
**Branch:** $(git branch --show-current)
**Commit:** $(git rev-parse --short HEAD)

## Resultados

### ✅ Testes
```

[Output resumido dos testes]

```

### ✅ Lint
```

[Output resumido do lint]

```

### ✅ Type Check
```

[Output resumido do type check]

```

### ✅ Build
```

[Output resumido do build]

```

## Status Geral
- **Testes:** Passaram/Falharam
- **Lint:** Passou/Falhou  
- **Type Check:** Passou/Falhou
- **Build:** Passou/Falhou
- **Recomendação:** ✅ Pronto para commit/release / ❌ Corrigir issues primeiro
```

## Exemplo completo

### Para projeto Python/Django

```bash
# Quality Gate para projeto Django
echo "🚀 Iniciando Quality Gate para projeto Django"

echo "1. Testes (pytest)..."
if pytest -q --tb=short; then
  echo "✅ Testes passaram"
else
  echo "❌ Testes falharam"
  exit 1
fi

echo "2. Lint (ruff)..."
if ruff check .; then
  echo "✅ Lint passou"
else
  echo "❌ Lint falhou"
  # Não falha imediatamente, apenas warning
fi

echo "3. Type check (mypy)..."
if mypy .; then
  echo "✅ Type check passou"
else
  echo "⚠️  Type check com warnings"
fi

echo "4. Django check..."
if python3 manage.py check; then
  echo "✅ Django check passou"
else
  echo "❌ Django check falhou"
  exit 1
fi

echo "🎉 Quality Gate completo - Pronto para commit!"
```

### Para projeto JavaScript/React

```bash
# Quality Gate para projeto React
echo "🚀 Iniciando Quality Gate para projeto React"

echo "1. Dependências (npm audit)..."
npm audit --audit-level=moderate

echo "2. Testes (jest)..."
if npm test -- --passWithNoTests; then
  echo "✅ Testes passaram"
else
  echo "❌ Testes falharam"
  exit 1
fi

echo "3. Lint (eslint)..."
if npm run lint; then
  echo "✅ Lint passou"
else
  echo "❌ Lint falhou"
  # Não falha imediatamente
fi

echo "4. Type check (TypeScript)..."
if npx tsc --noEmit; then
  echo "✅ Type check passou"
else
  echo "❌ Type check falhou"
  exit 1
fi

echo "5. Build..."
if npm run build; then
  echo "✅ Build passou"
else
  echo "❌ Build falhou"
  exit 1
fi

echo "🎉 Quality Gate completo - Pronto para commit!"
```

## Integração com workflow ESAA

### Para cada slice (Definition of Done)

1. Implementar código
2. Executar Quality Gate
3. Se passar → commit
4. Se falhar → corrigir e reexecutar

### No AGENTS.md

```markdown
## 2. Comandos de Validacao (Quality Gate)
- Testes: `pytest -q`
- Lint: `ruff check .`
- Type check: `mypy .`
- Build: `python3 manage.py check`

## 6. Definition of Done (DoD)
- [ ] Build sem erro (Quality Gate: Build)
- [ ] Testes passam (Quality Gate: Testes)
- [ ] Lint/type check OK (Quality Gate: Lint/Type)
```

### Exemplo de prompt

```
Execute o quality gate para validar as mudanças atuais antes do commit.
```

## Níveis de severidade

### 1. Crítico (falha impede commit)

- Testes falhando
- Build falhando
- Erros de type check (se configurado como crítico)

### 2. Warning (alerta, não impede commit)

- Lint warnings
- Type check notes
- Testes com cobertura baixa (se configurado)

### 3. Informativo

- Dependências desatualizadas
- Code smells (baixa prioridade)
- Sugestões de melhoria

## Configuração via arquivo

### .qualitygaterc (opcional)

```json
{
  "commands": {
    "tests": "pytest -q",
    "lint": "ruff check .",
    "type_check": "mypy .",
    "build": "python3 manage.py check"
  },
  "fail_fast": true,
  "critical": ["tests", "build"],
  "warnings": ["lint", "type_check"],
  "coverage_threshold": 80
}
```

### Uso com arquivo de configuração

```bash
if [ -f ".qualitygaterc" ]; then
  commands=$(cat .qualitygaterc | jq -r '.commands | to_entries[] | "\(.key):\(.value)"')
  # Processar comandos
fi
```

## Para projetos do setor público

### Verificações adicionais

```bash
# Segurança
safety check
bandit -r .

# Conformidade
# (comandos específicos para normas governamentais)

# Acessibilidade
# pa11y-ci (se aplicável)

# Performance
# lighthouse (para web)
```

### Exemplo estendido

```bash
echo "🔒 Verificação de segurança..."
if safety check; then
  echo "✅ Sem vulnerabilidades conhecidas"
else
  echo "⚠️  Vulnerabilidades encontradas - revisar"
fi

echo "📊 Cobertura de testes..."
coverage run -m pytest -q
coverage report --fail-under=80

echo "🌐 Acessibilidade (se aplicável)..."
# pa11y-ci http://localhost:8000
```

## Scripts úteis

### quality-gate.sh (executor genérico)

```bash
#!/bin/bash
# quality-gate.sh

set -e

echo "🚀 Executando Quality Gate"
echo "========================"

# Ler comandos do AGENTS.md ou usar padrões
if [ -f "AGENTS.md" ]; then
  echo "Usando comandos do AGENTS.md"
  # Extrair comandos (implementação simplificada)
  TESTS_CMD=$(grep -A5 "Comandos de Validação" AGENTS.md | grep "Testes:" | sed 's/.*`\(.*\)`/\1/')
  LINT_CMD=$(grep -A5 "Comandos de Validação" AGENTS.md | grep "Lint:" | sed 's/.*`\(.*\)`/\1/')
else
  echo "Usando comandos padrão"
  # Comandos padrão baseados em stack
  if [ -f "pyproject.toml" ]; then
    TESTS_CMD="pytest -q"
    LINT_CMD="ruff check ."
  elif [ -f "package.json" ]; then
    TESTS_CMD="npm test"
    LINT_CMD="npm run lint"
  fi
fi

# Executar comandos
[ -n "$TESTS_CMD" ] && echo "▶️ Testes: $TESTS_CMD" && eval "$TESTS_CMD"
[ -n "$LINT_CMD" ] && echo "▶️ Lint: $LINT_CMD" && eval "$LINT_CMD"

echo "✅ Quality Gate completo"
```

### quick-check.sh (validação rápida)

```bash
#!/bin/bash
# quick-check.sh - Validação rápida antes de commit

echo "⚡ Quick Check"

# Verificar se há mudanças não commitadas
if [ -n "$(git status --porcelain)" ]; then
  echo "📝 Há mudanças não commitadas"
  
  # Executar testes rápidos
  pytest -q --tb=no 2>/dev/null && echo "✅ Testes rápidos OK" || echo "❌ Testes falharam"
  
  # Verificar sintaxe Python
  python3 -m py_compile $(git diff --name-only --cached | grep .py) 2>/dev/null && echo "✅ Sintaxe Python OK"
else
  echo "📭 Nenhuma mudança para verificar"
fi
```

## Integração com Git hooks

### .git/hooks/pre-commit (exemplo)

```bash
#!/bin/bash
# pre-commit hook usando quality gate

echo "🔍 Executando verificações pre-commit..."

# Executar quality gate simplificado
./scripts/quality-gate.sh --pre-commit

if [ $? -eq 0 ]; then
  echo "✅ Verificações passaram - commit permitido"
  exit 0
else
  echo "❌ Verificações falharam - commit bloqueado"
  echo "   Execute './scripts/quality-gate.sh' para detalhes"
  exit 1
fi
```

### .git/hooks/pre-push (exemplo)

```bash
#!/bin/bash  
# pre-push hook - validação completa

echo "🚀 Executando Quality Gate completo antes do push..."

./scripts/quality-gate.sh --full

if [ $? -eq 0 ]; then
  echo "✅ Quality Gate passou - push permitido"
  exit 0
else
  echo "❌ Quality Gate falhou - push bloqueado"
  echo "   Corrija os issues antes de fazer push"
  exit 1
fi
```

## Checklist de uso

### Antes de executar

- [ ] AGENTS.md atualizado com comandos corretos (opcional)
- [ ] Dependências instaladas (venv, node_modules, etc.)
- [ ] Ambiente configurado (variáveis de ambiente, etc.)

### Comandos a incluir (mínimo)

- [ ] Testes
- [ ] Lint/formação
- [ ] Type check (se aplicável)
- [ ] Build/verificação

### Após execução

- [ ] Resultados documentados (para Release Evidence Pack)
- [ ] Issues priorizados (crítico > warning > informativo)
- [ ] Próximos passos definidos (correções necessárias)

## Dicas para eficiência

### 1. Cache para velocidade

```bash
# Usar cache do pytest
pytest -q --cache-clear

# Cache do mypy
mypy --cache-dir .mypy_cache
```

### 2. Execução paralela (se suportado)

```bash
# pytest paralelo
pytest -n auto

# ESLint paralelo (se configurado)
```

### 3. Output limpo

```bash
# Apenas erros
ruff check . --quiet

# Output resumido
pytest -q --tb=short
```

### 4. Exit codes claros

- 0: Sucesso completo
- 1: Falha crítica (testes, build)
- 2: Apenas warnings (lint, type check)
- 3: Configuração inválida

## 📁 Arquivos do Skill

```
quality-gate-executor/
├── SKILL.md                    # Esta documentação
├── quality_gate.py             # Script Python autônomo (recomendado)
├── README.md                   # Documentação do script Python
├── requirements.txt            # Dependências opcionais
├── LICENSE                     # Licença MIT
└── (scripts/ directory)        # Scripts bash de exemplo
```

## 🐍 Vantagens do Script Python

### Comparação

| Aspecto | Script Python | Instruções Textuais |
|---------|---------------|---------------------|
| **Determinismo** | ✅ Sempre mesmo comportamento | ❌ Depende da interpretação do LLM |
| **Output estruturado** | ✅ JSON, Markdown, texto | ❌ Apenas texto |
| **Reusabilidade** | ✅ Pode ser chamado de qualquer lugar | ❌ Apenas via Pi.dev |
| **Manutenção** | ✅ Código versionado, testável | ❌ Texto em Markdown |
| **Integração CI/CD** | ✅ Exit codes, formatos parseáveis | ❌ Manual |

### Use o script Python para

- Pipelines automatizados
- Integração com CI/CD
- Relatórios estruturados
- Validação determinística

### Use instruções textuais para

- Validação rápida ad-hoc
- Quando não pode instalar Python/scripts
- Como referência/documentação
