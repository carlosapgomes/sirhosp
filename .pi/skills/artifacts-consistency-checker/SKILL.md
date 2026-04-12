---
name: artifacts-consistency-checker
description: "Verifica consistência entre artefatos do projeto: specs vs código, ADRs vs implementação, documentação vs realidade. Valida alinhamento para rastreabilidade completa."
---

# Skill: Artifacts Consistency Checker

Este skill valida a consistência entre diferentes artefatos do projeto, garantindo que specs, código, ADRs e documentação estejam alinhados. Essencial para repositórios do setor público que precisam de rastreabilidade completa.

## Quando usar

- Antes de uma release importante
- Ao retomar trabalho após pausa longa
- Quando há suspeita de desalinhamento entre documentação e código
- Como parte da geração de Release Evidence Packs
- Para auditoria interna de qualidade

## 🐍 Método Recomendado: Script Python

Este skill inclui `check_consistency.py` para executar as checagens de forma determinística.

```bash
# relatório texto
python3 check_consistency.py --root .

# relatório JSON
python3 check_consistency.py --root . --format json

# relatório Markdown
python3 check_consistency.py --root . --format markdown

# executar comandos do AGENTS.md (opcional)
python3 check_consistency.py --root . --run-commands --timeout 60
```

## O que verificar

### 1. Specs vs Código

- Requisitos em `openspec/specs/` estão implementados no código
- Código não implementa funcionalidades não especificadas
- Cenários GIVEN/WHEN/THEN têm testes correspondentes

### 2. ADRs vs Implementação

- Decisões arquiteturais em `docs/adr/` estão refletidas no código
- Decisões deprecated não estão mais sendo usadas
- Alternativas consideradas não foram implementadas por engano

### 3. AGENTS.md vs Realidade

- Stack e versões no AGENTS.md correspondem às reais
- Comandos de validação funcionam corretamente
- Constraints arquiteturais são respeitadas

### 4. PROJECT_CONTEXT.md vs Estado Atual

- Descrição do sistema corresponde à implementação atual
- Regras não negociáveis ainda são válidas
- Arquitetura descrita reflete a real

### 5. Release Evidence Packs vs Changes

- Todas as mudanças documentadas nos packs estão no Git
- Specs referenciadas existem e estão atualizadas
- ADRs mencionadas existem e têm status correto

## Processo de verificação

### 1. Verificar specs vs código (OpenSpec)

```bash
# Listar specs existentes
find openspec/specs -name "*.md" -type f | head -20

# Para cada spec, verificar se há implementação
# (análise simplificada - procurar por nomes/padrões)
grep -r "login" openspec/specs/auth/ 2>/dev/null
grep -r "login" app/ --include="*.py" --include="*.js" 2>/dev/null | head -5
```

### 2. Verificar ADRs vs código

```bash
# Listar ADRs
ls -la docs/adr/ADR-*.md 2>/dev/null | head -10

# Exemplo: verificar se decisão sobre PostgreSQL está refletida
grep -i "postgresql" docs/adr/ADR-*.md 2>/dev/null
grep -i "postgresql" requirements.txt pyproject.toml docker-compose.yml 2>/dev/null
```

### 3. Verificar AGENTS.md

```bash
# Verificar se comandos existem/funcionam
if [ -f "AGENTS.md" ]; then
  # Extrair comando de testes
  TEST_CMD=$(grep -A2 "Testes:" AGENTS.md | grep -o "\`.*\`" | head -1 | tr -d '\`')
  if [ -n "$TEST_CMD" ]; then
    echo "Testando comando: $TEST_CMD"
    eval "$TEST_CMD" >/dev/null 2>&1 && echo "✅ Comando funciona" || echo "❌ Comando falha"
  fi
fi
```

### 4. Verificar PROJECT_CONTEXT.md

```bash
if [ -f "PROJECT_CONTEXT.md" ]; then
  # Verificar se stack mencionada existe
  grep -i "python\|django\|postgresql" PROJECT_CONTEXT.md
  # Verificar correspondência com arquivos reais
  [ -f "pyproject.toml" ] && echo "✅ pyproject.toml existe" || echo "⚠️ pyproject.toml não encontrado"
fi
```

### 5. Verificar links/referências

```bash
# Verificar links quebrados em arquivos Markdown
find . -name "*.md" -type f -exec grep -l "\[.*\](.*)" {} \; | head -5 | while read file; do
  echo "Verificando links em $file"
  grep -o "\[.*\](.*)" "$file" | sed 's/.*(\(.*\)).*/\1/' | while read link; do
    if [ -f "$link" ] || [[ "$link" =~ ^https?:// ]]; then
      : # Link OK (simplificado)
    else
      echo "⚠️  Link possivelmente quebrado: $link em $file"
    fi
  done
done
```

## Relatório de inconsistências

### Template de relatório

```markdown
# Artifacts Consistency Report

**Data:** $(date)
**Projeto:** $(basename $(pwd))
**Branch:** $(git branch --show-current)

## Resumo
- ✅ Especificações vs Código: X/Y consistentes
- ✅ ADRs vs Implementação: X/Y consistentes  
- ✅ AGENTS.md vs Realidade: X/Y consistentes
- ✅ PROJECT_CONTEXT.md vs Estado: X/Y consistentes
- ✅ Links/Referências: X/Y funcionais

## Inconsistências Encontradas

### 1. Specs vs Código
#### ❌ Spec não implementada
- **Spec:** `openspec/specs/auth/sso.md` - Requisito SSO governo
- **Evidência:** Nenhuma implementação encontrada para "sso_gov"
- **Arquivos verificados:** `app/auth/`, `views/auth.py`
- **Sugestão:** Implementar ou marcar spec como futura

#### ⚠️ Código não especificado
- **Código:** Função `process_payment_pix()` em `services/payments.py`
- **Evidência:** Não há spec para pagamentos PIX
- **Sugestão:** Criar spec ou remover código se não usado

### 2. ADRs vs Implementação
#### ❌ ADR não seguida
- **ADR:** ADR-0003 - Uso de PostgreSQL com pgcrypto
- **Evidência:** Configuração atual usa SQLite em desenvolvimento
- **Sugestão:** Migrar para PostgreSQL ou atualizar ADR

### 3. AGENTS.md vs Realidade
#### ❌ Comando inválido
- **Comando:** `python3 manage.py test --coverage`
- **Evidência:** Opção `--coverage` não existe no Django test runner
- **Sugestão:** Corrigir para `coverage run manage.py test`

### 4. PROJECT_CONTEXT.md vs Estado
#### ⚠️ Informação desatualizada
- **Mencionado:** "Sistema usa Django 4.2"
- **Realidade:** `pyproject.toml` especifica Django 5.0
- **Sugestão:** Atualizar PROJECT_CONTEXT.md

### 5. Links/Referências
#### ❌ Link quebrado
- **Arquivo:** `docs/adr/README.md`
- **Link:** `ADR-0005-sso-implementation.md`
- **Realidade:** Arquivo não existe (talvez seja `ADR-0004-sso-governamental.md`)
- **Sugestão:** Corrigir referência

## Recomendações Prioritárias

### Crítico (impedem release)
1. [ ] Implementar spec SSO (abertura de sistema)
2. [ ] Corrigir comando de testes no AGENTS.md

### Alto (impactam qualidade)
1. [ ] Alinhar ADR-0003 com implementação
2. [ ] Atualizar PROJECT_CONTEXT.md

### Médio (melhorias)
1. [ ] Documentar função PIX não especificada
2. [ ] Corrigir links quebrados

## Checklist de Consistência

- [ ] Todas as specs têm implementação ou estão marcadas como futuras
- [ ] Todo código significativo tem spec correspondente
- [ ] Todas as ADRs estão refletidas no código
- [ ] Nenhuma decisão deprecated ainda está em uso
- [ ] AGENTS.md corresponde à stack real
- [ ] Comandos do AGENTS.md funcionam
- [ ] PROJECT_CONTEXT.md descreve estado atual
- [ ] Regras não negociáveis são respeitadas
- [ ] Links internos funcionam
- [ ] Release Evidence Packs referenciam artefatos existentes
```

## Exemplo prático

### Projeto Django com OpenSpec

```bash
# Executar verificação básica
echo "🔍 Verificando consistência de artefatos..."

# 1. Specs vs Código
echo "## 1. Specs vs Código"
SPEC_COUNT=$(find openspec/specs -name "*.md" -type f | wc -l)
echo "Total de specs: $SPEC_COUNT"

# Verificar spec de autenticação
if grep -q "SSO" openspec/specs/auth/authentication.md 2>/dev/null; then
  echo "Spec SSO encontrada"
  if grep -r "sso\|SSO" app/auth/ --include="*.py" 2>/dev/null; then
    echo "✅ Implementação SSO encontrada"
  else
    echo "❌ Nenhuma implementação SSO encontrada"
  fi
fi

# 2. ADRs
echo "## 2. ADRs vs Implementação"
if [ -f "docs/adr/ADR-0001-database-choice.md" ]; then
  if grep -q "PostgreSQL" docs/adr/ADR-0001-database-choice.md; then
    if grep -q "postgresql" docker-compose.yml 2>/dev/null || grep -q "psycopg2" requirements.txt 2>/dev/null; then
      echo "✅ ADR-0001 refletida (PostgreSQL usado)"
    else
      echo "❌ ADR-0001 não refletida (PostgreSQL não configurado)"
    fi
  fi
fi

# 3. AGENTS.md
echo "## 3. AGENTS.md vs Realidade"
if [ -f "AGENTS.md" ]; then
  if grep -q "Python: 3.12" AGENTS.md; then
    python3 --version | grep -q "3.12" && echo "✅ Versão Python correta" || echo "❌ Versão Python diferente"
  fi
fi

# 4. PROJECT_CONTEXT.md  
echo "## 4. PROJECT_CONTEXT.md vs Estado"
if [ -f "PROJECT_CONTEXT.md" ]; then
  if grep -q "Django 5.0" PROJECT_CONTEXT.md; then
    grep "django" pyproject.toml | grep -q "5.0" && echo "✅ Django 5.0 confirmado" || echo "❌ Django versão diferente"
  fi
fi

echo "📊 Verificação completa"
```

## Integração com workflow ESAA

### No processo de release

1. Desenvolver changes (OpenSpec)
2. Verificar consistência (este skill)
3. Corrigir inconsistências encontradas
4. Gerar Release Evidence Pack
5. Criar release

### Como gate de qualidade

```bash
# No CI/CD ou manualmente antes de release
./scripts/check-consistency.sh

if [ $? -eq 0 ]; then
  echo "✅ Consistência OK - pode prosseguir com release"
else
  echo "❌ Inconsistências encontradas - corrigir antes de release"
  exit 1
fi
```

### Relação com Definition of Done

No DoD do AGENTS.md:

```markdown
## 6. Definition of Done (DoD)
- [ ] Build sem erro
- [ ] Testes passam
- [ ] Lint/type check OK
- [ ] **Consistência verificada** (specs ⇄ código ⇄ ADRs)
- [ ] Tasks atualizadas
```

## Scripts úteis

### check-consistency.sh (básico)

```bash
#!/bin/bash
# check-consistency.sh

set -e

echo "🔍 Verificação de Consistência de Artefatos"
echo "=========================================="

ERRORS=0
WARNINGS=0

# Funções de verificação
check_specs_vs_code() {
  echo "## 1. Specs vs Código"
  # Implementação básica
  if [ -d "openspec/specs" ]; then
    echo "✅ Diretório specs existe"
  else
    echo "⚠️  Diretório specs não encontrado"
    WARNINGS=$((WARNINGS+1))
  fi
}

check_adrs() {
  echo "## 2. ADRs"
  if [ -d "docs/adr" ]; then
    ADR_COUNT=$(ls docs/adr/ADR-*.md 2>/dev/null | wc -l)
    echo "✅ $ADR_COUNT ADRs encontradas"
  else
    echo "⚠️  Diretório docs/adr não encontrado"
    WARNINGS=$((WARNINGS+1))
  fi
}

check_agents() {
  echo "## 3. AGENTS.md"
  if [ -f "AGENTS.md" ]; then
    echo "✅ AGENTS.md encontrado"
    # Verificar comandos básicos
    if grep -q "pytest\|npm test" AGENTS.md; then
      echo "✅ Comandos de testes definidos"
    else
      echo "⚠️  Comandos de testes não definidos"
      WARNINGS=$((WARNINGS+1))
    fi
  else
    echo "❌ AGENTS.md não encontrado (obrigatório)"
    ERRORS=$((ERRORS+1))
  fi
}

check_context() {
  echo "## 4. PROJECT_CONTEXT.md"
  if [ -f "PROJECT_CONTEXT.md" ]; then
    echo "✅ PROJECT_CONTEXT.md encontrado"
  else
    echo "⚠️  PROJECT_CONTEXT.md não encontrado (recomendado)"
    WARNINGS=$((WARNINGS+1))
  fi
}

# Executar verificações
check_specs_vs_code
check_adrs
check_agents
check_context

# Resumo
echo ""
echo "📊 Resumo"
echo "--------"
echo "✅ Verificações concluídas"
echo "❌ Erros: $ERRORS"
echo "⚠️  Warnings: $WARNINGS"

if [ $ERRORS -gt 0 ]; then
  echo "❌ Consistência falhou - corrigir erros antes de prosseguir"
  exit 1
elif [ $WARNINGS -gt 0 ]; then
  echo "⚠️  Consistência com warnings - revisar recomendações"
  exit 0
else
  echo "✅ Consistência OK"
  exit 0
fi
```

### find-broken-links.sh

```bash
#!/bin/bash
# find-broken-links.sh

find . -name "*.md" -type f | while read file; do
  # Extrair links Markdown
  grep -o "\[[^]]*\]([^)]*)" "$file" 2>/dev/null | while read link; do
    url=$(echo "$link" | sed -n 's/.*](\(.*\))/\1/p')
    
    # Ignorar links externos
    if [[ "$url" =~ ^https?:// ]]; then
      continue
    fi
    
    # Verificar se arquivo existe
    if [ ! -f "$url" ] && [ ! -d "$url" ]; then
      # Tentar com caminho relativo ao diretório do arquivo
      dir=$(dirname "$file")
      if [ ! -f "$dir/$url" ] && [ ! -d "$dir/$url" ]; then
        echo "❌ Link quebrado: $file -> $url"
      fi
    fi
  done
done
```

## Dicas para projetos do setor público

### 1. Ênfase em rastreabilidade

- Todo requisito legal deve ter spec correspondente
- Toda decisão de compliance deve ter ADR
- Toda implementação deve ser rastreável a um requisito

### 2. Exemplo de verificação de compliance

```bash
# Verificar se requisitos LGPD estão documentados e implementados
echo "## Verificação LGPD"

# Specs relacionadas a privacidade
find openspec/specs -name "*.md" -type f -exec grep -l "LGPD\|privacidade\|dados pessoais" {} \;

# ADRs sobre segurança de dados
find docs/adr -name "*.md" -type f -exec grep -l "criptografia\|backup\|auditoria" {} \;

# Implementação de criptografia
grep -r "pgcrypto\|Fernet\|AES" app/ --include="*.py" 2>/dev/null
```

### 3. Relatório para auditores

```markdown
# Relatório de Consistência para Auditoria

## Requisitos Regulatórios Mapeados
| Requisito | Spec | ADR | Implementação | Status |
|-----------|------|-----|---------------|--------|
| LGPD Art. 5º | specs/compliance/lgpd.md | ADR-0002 | app/services/encryption.py | ✅ |
| Portaria 123/2025 | specs/accessibility/a11y.md | ADR-0003 | templates/base.html | ✅ |

## Lacunas Identificadas
1. **Requisito X**: Sem spec correspondente
2. **Decisão Y**: Sem ADR documentada

## Recomendações
1. Criar spec para requisito X até DD/MM/AAAA
2. Documentar decisão Y em ADR até DD/MM/AAAA
```

## Checklist de qualidade

### Pré-verificação

- [ ] Repositório clonado e atualizado
- [ ] Dependências instaladas
- [ ] Ambiente configurado

### Verificações mínimas

- [ ] AGENTS.md existe e é válido
- [ ] Specs existem (se usando OpenSpec)
- [ ] ADRs existem (para decisões importantes)
- [ ] PROJECT_CONTEXT.md existe (recomendado)
- [ ] Links internos funcionam

### Pós-verificação

- [ ] Relatório gerado
- [ ] Inconsistências documentadas
- [ ] Plano de correção definido
- [ ] Issues criados (se necessário)

## Integração com CI/CD

### Pipeline exemplo (.github/workflows/consistency.yml)

```yaml
name: Artifacts Consistency Check

on:
  push:
    branches: [ main, release/* ]
  pull_request:
    branches: [ main ]

jobs:
  check:
    runs-on: ubuntu-latest
    
    steps:
    - uses: actions/checkout@v4
    
    - name: Run Consistency Check
      run: |
        chmod +x scripts/check-consistency.sh
        ./scripts/check-consistency.sh
    
    - name: Upload Report
      if: always()
      uses: actions/upload-artifact@v3
      with:
        name: consistency-report
        path: consistency-report.md
```

### Saída do CI

- ✅ Sucesso: Todos os artefatos consistentes
- ⚠️ Warning: Inconsistências não críticas
- ❌ Falha: Inconsistências críticas (bloqueia merge/release)
