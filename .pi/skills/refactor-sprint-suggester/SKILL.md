---
name: refactor-sprint-suggester
description: Analisa o código e sugere refactorings prioritários baseados em métricas de complexidade, duplicação, dívida técnica e padrões do projeto.
---

# Skill: Refactor Sprint Suggester

Este skill analisa o código do projeto e sugere refactorings prioritários para sprints periódicos de melhoria. Baseado em métricas como complexidade ciclomática, duplicação, tamanho de funções e padrões de código identificados no AGENTS.md.

## Quando usar

- A cada 8 changes ou mensalmente (como sugerido no workflow ESAA)
- Quando a dívida técnica está afetando a produtividade
- Antes de adicionar novas funcionalidades complexas
- Para preparar o código para novos contribuidores
- Como parte de rotina de manutenção preventiva

## Método recomendado (script)

Use o script incluído para gerar priorização objetiva:

```bash
python3 suggest_refactor_sprint.py --project-root .
python3 suggest_refactor_sprint.py --project-root . --format json
python3 suggest_refactor_sprint.py --project-root . --output docs/refactor-sprint-report.md
python3 suggest_refactor_sprint.py --project-root . --fail-on high
```

Exit codes: `0` ok, `1` erro de execução, `2` policy fail (`--fail-on`).

## Métricas a analisar

### 1. Complexidade Ciclomática

- Funções/métodos com CC > 15 (padrão)
- Muitos níveis de aninhamento (if/for/try)
- Alta densidade de caminhos de execução

### 2. Tamanho de Funções/Métodos
>
- > 50 linhas (Python/JavaScript)
- > 100 linhas (Java/C#)
- Muitos parâmetros (> 5)

### 3. Duplicação de Código

- Blocos idênticos ou similares
- Copy-paste com pequenas variações
- Oportunidades para extração

### 4. Code Smells

- God classes/métodos
- Feature envy
- Long parameter lists
- Primitive obsession
- Data clumps

### 5. Dívida Técnica Explícita

- TODO, FIXME, HACK, XXX comentários
- @deprecated annotations
- Funções/métodos marcados como obsoletos

### 6. Violações de Arquitetura

- Violações das constraints do AGENTS.md
- Acoplamento entre módulos que deveriam ser independentes
- Dependências cíclicas

## Processo de análise

### 1. Coletar métricas básicas

```bash
# Python: radon, pylint, flake8
python3 -m radon cc app/ -a -s 2>/dev/null || echo "Radon não instalado"

# JavaScript: eslint, complexity-report
npx eslint --rule "complexity: ['error', 15]" . 2>/dev/null || true

# Contar linhas de arquivos
find app/ -name "*.py" -type f -exec wc -l {} + | sort -nr | head -10

# Buscar TODO/FIXME
grep -r "TODO\|FIXME\|HACK\|XXX" app/ --include="*.py" --include="*.js" --include="*.ts" 2>/dev/null | head -20
```

### 2. Analisar violações arquiteturais

```bash
# Verificar constraints do AGENTS.md (se existir)
if [ -f "AGENTS.md" ]; then
  grep -i "não\|não deve\|proibido\|evitar" AGENTS.md | head -10
  
  # Exemplo: verificar se lógica de negócio está em views
  grep -r "import models" app/views/ --include="*.py" 2>/dev/null | head -5
  grep -r "business logic\|regra.*negócio" app/views/ --include="*.py" 2>/dev/null | head -5
fi
```

### 3. Identificar hotspots

```bash
# Arquivos modificados recentemente (maior chance de dívida)
git log --oneline --name-only --since="30 days ago" | grep -E "\.(py|js|ts)$" | sort | uniq -c | sort -nr | head -10

# Arquivos com muitos bugs/issues
git log --oneline --grep="fix\|bug\|correction" --since="90 days ago" --name-only | grep -E "\.(py|js|ts)$" | sort | uniq -c | sort -nr | head -10
```

## Template de relatório de refactoring

```markdown
# Refactor Sprint Suggestions

**Data:** $(date)
**Projeto:** $(basename $(pwd))
**Período analisado:** Últimos 30 dias

## Resumo Executivo
- **Complexidade alta:** X funções com CC > 15
- **Duplicação:** Y blocos duplicados identificados
- **Dívida técnica:** Z TODOs/FIXMEs pendentes
- **Violações:** W violações de constraints arquiteturais

**Recomendação:** Sprint de refactoring de [1-3] dias focado em [áreas prioritárias].

## Áreas Prioritárias

### 🔴 Crítico (impedem evolução)
1. **[Módulo: auth/services.py]**
   - **Problema:** Função `validate_user_credentials` com CC=28
   - **Impacto:** Dificuldade de teste, alta probabilidade de bugs
   - **Sugestão:** Dividir em funções menores (`validate_format`, `check_password`, `verify_2fa`)
   - **Esforço:** 2-4 horas
   - **Benefício:** Testabilidade, manutenibilidade

2. **[Módulo: payments/processors.py]**
   - **Problema:** Duplicação de lógica de validação em 3 lugares
   - **Impacto:** Inconsistências, triplo trabalho para mudanças
   - **Sugestão:** Extrair para `validators/payment_validator.py`
   - **Esforço:** 3-5 horas
   - **Benefício:** Consistência, reuso

### 🟡 Alto (impactam qualidade)
1. **[Módulo: reports/generators.py]**
   - **Problema:** Classe `ReportGenerator` com 1200+ linhas (God class)
   - **Impacto:** Dificuldade de entendimento, alto acoplamento
   - **Sugestão:** Dividir por tipo de relatório (`FinancialReportGenerator`, `OperationalReportGenerator`)
   - **Esforço:** 6-8 horas
   - **Benefício:** Separação de responsabilidades, testabilidade

2. **[Módulo: utils/helpers.py]**
   - **Problema:** 15+ funções utilitárias não relacionadas
   - **Impacto:** Baixa coesão, difícil de encontrar funcionalidades
   - **Sugestão:** Reorganizar em módulos específicos (`date_utils.py`, `string_utils.py`, `file_utils.py`)
   - **Esforço:** 4-6 horas
   - **Benefício:** Organização, descobribilidade

### 🟢 Médio (melhorias incrementais)
1. **[Módulo: models/]**
   - **Problema:** Métodos `__str__` inconsistentes
   - **Impacto:** Debugging difícil, logs inconsistentes
   - **Sugestão:** Padronizar formato: `f"{self.id}: {self.name}"`
   - **Esforço:** 2-3 horas
   - **Benefício:** Consistência, debugging mais fácil

2. **[Projeto todo]**
   - **Problema:** 47 TODOs/FIXMEs pendentes
   - **Impacto:** Dívida técnica acumulada
   - **Sugestão:** Sprint de limpeza (1 dia)
   - **Esforço:** 8 horas
   - **Benefício:** Código mais limpo, menos surpresas

## Violações de Constraints (AGENTS.md)

### ❌ Violações críticas
1. **Constraint:** "Não coloque lógica de negócio em views"
   - **Violação:** `views/process_approval.py` contém regras complexas de aprovação
   - **Correção:** Mover para `services/approval_service.py`

2. **Constraint:** "Models apenas para dados, não regras"
   - **Violação:** `models/User.py` tem método `calculate_permissions()`
   - **Correção:** Mover para `services/permission_service.py`

## Oportunidades de Arquitetura

### 🏗️ Melhorias estruturais
1. **Introdução de Repository Pattern**
   - **Onde:** Módulos com acesso direto a ORM em múltiplos lugares
   - **Benefício:** Isolamento de persistência, facilita testing
   - **Esforço:** 8-12 horas

2. **Implementação de Event Bus**
   - **Onde:** Módulos com callbacks diretos entre si
   - **Benefício:** Baixo acoplamento, extensibilidade
   - **Esforço:** 10-15 horas

## Plano de Sprint Sugerido

### Sprint de 3 dias (Exemplo)
**Objetivo:** Reduzir complexidade crítica e eliminar duplicação principal

**Dia 1: Complexidade Crítica**
- [ ] Refatorar `auth/services.py` (CC alto)
- [ ] Extrair validações duplicadas de pagamentos
- [ ] Criar testes para novas funções

**Dia 2: God Classes**
- [ ] Dividir `reports/generators.py`
- [ ] Reorganizar `utils/helpers.py`
- [ ] Atualizar pontos de uso

**Dia 3: Limpeza e Padronização**
- [ ] Resolver TODOs/FIXMEs prioritários
- [ ] Padronizar métodos `__str__`
- [ ] Documentar mudanças

## Métricas de Sucesso

### Antes vs Depois
| Métrica | Antes | Meta | Pós-sprint |
|---------|-------|------|------------|
| CC médio | 18.5 | < 12 | [medir] |
| Funções > 50 linhas | 24 | < 10 | [medir] |
| Blocos duplicados | 15 | < 5 | [medir] |
| TODOs pendentes | 47 | < 10 | [medir] |

### Benefícios Esperados
- **Produtividade:** +20% velocidade de desenvolvimento
- **Qualidade:** -30% bugs em módulos refatorados
- **Manutenibilidade:** +40% facilidade de entendimento
- **Testabilidade:** +50% cobertura viável

## Scripts de análise

### analyze-complexity.sh (Python com radon)
```bash
#!/bin/bash
# analyze-complexity.sh

echo "📊 Análise de Complexidade"
echo "========================"

if command -v radon &> /dev/null; then
  echo "## Complexidade Ciclomática"
  python3 -m radon cc app/ -a -s | head -30
  
  echo ""
  echo "## Funções/Métodos com CC > 15"
  python3 -m radon cc app/ -a -s | grep -A2 "F" | grep "CC:" | awk -F'CC: ' '{if ($2 > 15) print $0}'
else
  echo "⚠️ Radon não instalado. Instalar com: pip install radon"
fi

echo ""
echo "## Arquivos Mais Complexos"
find app/ -name "*.py" -type f -exec wc -l {} + | sort -nr | head -10 | awk '{printf "%8d linhas: %s\n", $1, $2}'
```

### find-duplicates.sh (simplificado)

```bash
#!/bin/bash
# find-duplicates.sh

echo "🔍 Buscando Código Duplicado"
echo "=========================="

# Padrões comuns de duplicação
PATTERNS=(
  "def validate_.*"
  "class.*Serializer"
  "async def fetch_.*"
  "TODO:.*"
  "# FIXME:.*"
)

for pattern in "${PATTERNS[@]}"; do
  echo ""
  echo "## Padrão: $pattern"
  grep -r "$pattern" app/ --include="*.py" | head -5
done

echo ""
echo "## Blocos similares (análise simplificada)"
# Procurar por funções com nomes similares
find app/ -name "*.py" -type f -exec grep -h "^def " {} \; | sed 's/def //' | sed 's/(.*//' | sort | uniq -c | sort -nr | head -10
```

### tech-debt-report.sh

```bash
#!/bin/bash
# tech-debt-report.sh

echo "💰 Relatório de Dívida Técnica"
echo "============================"

echo "## TODO/FIXME/HACK/XXX"
echo "```"
grep -r "TODO\|FIXME\|HACK\|XXX" app/ --include="*.py" --include="*.js" --include="*.ts" 2>/dev/null | head -20
echo "```"

echo ""
echo "## @deprecated"
grep -r "@deprecated" app/ --include="*.py" --include="*.js" --include="*.ts" 2>/dev/null

echo ""
echo "## Importações de módulos obsoletos"
grep -r "from.*deprecated\|import.*deprecated" app/ --include="*.py" 2>/dev/null
```

## Integração com workflow ESAA

### No ciclo mensal

1. Executar análise de refactoring (este skill)
2. Priorizar sugestões baseado em impacto/esforço
3. Agendar sprint de refactoring (1-3 dias)
4. Executar changes OpenSpec para cada refactoring
5. Validar melhorias com métricas

### Changes de refactoring

```bash
# Para cada refactoring, criar change específico
/opsx:propose refactor-auth-complexity
# proposal.md: "Reduzir complexidade de auth/services.py de CC=28 para CC<12"
# design.md: Abordagem técnica (dividir funções, extrair helpers)
# tasks.md: Checklist específico de refactoring
/opsx:apply
```

### Relação com Definition of Done

Após refactoring:

- [ ] Complexidade reduzida (CC < 15)
- [ ] Testes passam (100% dos novos)
- [ ] Funcionalidade mantida (regressão zero)
- [ ] Documentação atualizada

## Dicas para projetos do setor público

### 1. Foco em manutenibilidade longa

- Código deve ser entendível por novos desenvolvedores após anos
- Documentação de decisões de refactoring em ADRs
- Priorizar claridade sobre otimização prematura

### 2. Compliance via refactoring

```markdown
## Refactoring para Conformidade

### LGPD - Separação de Dados Sensíveis
**Problema:** Dados pessoais espalhados em múltiplos modelos
**Refactoring:** Criar módulo `data_protection/` com:
- `encrypted_fields.py` (mixins para criptografia)
- `audit_logging.py` (registro de acesso)
- `data_retention.py` (políticas de retenção)

**Benefício:** Facilita auditoria, centraliza controles de compliance
```

### 3. Exemplo para sistema governamental

```markdown
# Refactor Sprint - Sistema de Processos Administrativos

## Prioridade 1: Isolamento de Regras de Negócio
**Módulo:** `process/tramitation.py`
**Problema:** 850 linhas, mistura UI, regras, persistência
**Sugestão:** 
- `process/services/tramitation_service.py` (regras)
- `process/api/tramitation_api.py` (endpoints)
- `process/models/tramitation_state.py` (dados)

**Justificativa:** Facilita compliance com normas de tramitação
```

## Checklist de preparação

### Antes do sprint

- [ ] Backup completo do código
- [ ] Ambiente de testes configurado
- [ ] Métricas baseline coletadas
- [ ] Time alinhado (se não for solo)
- [ ] Plano de rollback definido

### Durante o sprint

- [ ] Testes rodando continuamente
- [ ] Validação funcional após cada refactoring
- [ ] Documentação atualizada em paralelo
- [ ] Commits pequenos e descritivos

### Após o sprint

- [ ] Métricas pós-refactoring coletadas
- [ ] Release Evidence Pack gerado (se release)
- [ ] ADR criada para decisões arquiteturais importantes
- [ ] Retrospectiva (lições aprendidas)

## Ferramentas recomendadas

### Python

- **Radon**: Análise de complexidade
- **Pylint**: Detecção de code smells
- **Vulture**: Código não utilizado
- **Black**: Formatação automática

### JavaScript/TypeScript

- **ESLint**: Análise estática
- **TypeScript compiler**: Verificação de tipos
- **SonarJS**: Análise de qualidade
- **Prettier**: Formatação

### Genéricas

- **Git**: Análise de histórico
- **CodeClimate**: Plataforma de qualidade
- **SonarQube**: Análise contínua

## Conclusão

Refactor sprints periódicos são essenciais para:

- **Sustentabilidade** do código a longo prazo
- **Prevenção** de dívida técnica acumulada
- **Adaptabilidade** a novos requisitos
- **Onboarding** eficiente de novos contribuidores

Para solopreneurs do setor público, sprints de 1-2 dias a cada 8 changes mantêm o código em estado "forkável" - pronto para outros departamentos continuarem o trabalho sem você.
