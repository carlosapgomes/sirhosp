# Classify Change Risk (Python)

Script Python autônomo para classificar risco de mudanças baseado no workflow ESAA Solopreneur v4.2. Analisa descrições de mudanças e classifica em três níveis: ESSENTIAL, PROFESSIONAL, CRITICAL.

## 🎯 Características

- **Análise de texto**: Detecta palavras-chave de risco em descrições
- **Três níveis**: ESSENTIAL (🟢), PROFESSIONAL (🟡), CRITICAL (🔴)
- **Contexto do projeto**: Considera PROJECT_CONTEXT.md para ajustes
- **Fatores de ponderação**: Impacto em usuários, dados, complexidade, dependências
- **Recomendações específicas**: Sugestões baseadas no nível de risco
- **Formatos de output**: Texto, JSON, Markdown

## 📦 Instalação

### Método 1: Script autônomo

```bash
# Copiar o script para seu projeto
cp classify_risk.py /caminho/do/seu/projeto/

# Tornar executável (opcional)
chmod +x classify_risk.py
```

### Método 2: Como módulo Python

```bash
# Instalar em virtualenv (opcional)
python3 -m venv venv
source venv/bin/activate  # Linux/Mac
# ou venv\Scripts\activate  # Windows

# Instalar dependências opcionais
pip install -r requirements.txt
```

## 🚀 Uso Básico

### Classificar uma mudança

```bash
# Descrição direta
python3 classify_risk.py "Correção de typo na documentação"

# Com fatores específicos
python3 classify_risk.py "Implementar autenticação JWT" --impact-users many --complexity high

# Ler de arquivo
python3 classify_risk.py --file change_description.txt

# Formato JSON
python3 classify_risk.py "Migração do banco de dados" --format json

# Formato Markdown
python3 classify_risk.py "Nova funcionalidade de pagamento" --format markdown

# Modo legado de código de saída
python3 classify_risk.py "Nova funcionalidade" --strict-exit-codes
```

### Códigos de saída

- Padrão: `0` para ESSENTIAL/PROFESSIONAL, `2` para CRITICAL.
- `--strict-exit-codes`: mantém legado com `1` para PROFESSIONAL.

### Exemplos de classificação

#### ESSENTIAL (🟢)

```bash
python3 classify_risk.py "Corrigir typo no README.md"
```

```
🟢 NÍVEL: ESSENTIAL
📊 Score: 1.2 (confiança: 8.0%)
```

#### PROFESSIONAL (🟡)

```bash
python3 classify_risk.py "Adicionar testes unitários para módulo de autenticação"
```

```
🟡 NÍVEL: PROFESSIONAL  
📊 Score: 5.8 (confiança: 38.7%)
```

#### CRITICAL (🔴)

```bash
python3 classify_risk.py "Implementar criptografia para dados sensíveis do usuário"
```

```
🔴 NÍVEL: CRITICAL
📊 Score: 12.4 (confiança: 82.7%)
```

## 🔧 Fatores de Ponderação

### Impacto em usuários

```bash
--impact-users none    # Nenhum usuário afetado
--impact-users few     # Poucos usuários
--impact-users some    # Alguns usuários  
--impact-users many    # Muitos usuários
--impact-users all     # Todos os usuários
```

### Impacto em dados

```bash
--impact-data none        # Nenhum dado afetado
--impact-data regular     # Dados regulares
--impact-data important   # Dados importantes
--impact-data sensitive   # Dados sensíveis (PII, LGPD, GDPR)
```

### Complexidade

```bash
--complexity very_low    # Muito baixa
--complexity low         # Baixa
--complexity medium      # Média (padrão)
--complexity high        # Alta
--complexity very_high   # Muito alta
```

### Dependências

```bash
--dependencies none    # Nenhuma dependência
--dependencies few     # Poucas dependências
--dependencies some    # Algumas dependências
--dependencies many    # Muitas dependências
```

## 📊 Palavras-chave por Nível

### CRITICAL (🔴)

- Segurança: `security`, `authentication`, `password`, `encryption`
- Dados sensíveis: `gdpr`, `lgpd`, `pii`, `personal data`
- Infraestrutura: `database`, `migration`, `production`, `deployment`
- Financeiro: `payment`, `transaction`, `billing`, `money`

### PROFESSIONAL (🟡)

- Novas funcionalidades: `new feature`, `enhancement`, `optimization`
- UI/UX: `ui`, `ux`, `design`, `accessibility`
- Testes: `test`, `coverage`, `unit test`, `integration`
- Documentação: `documentation`, `readme`, `api docs`

### ESSENTIAL (🟢)

- Correções simples: `bug fix`, `typo`, `spelling`
- Estilo: `formatting`, `linting`, `style`
- Documentação menor: `comment`, `docstring`, `changelog`
- Assets: `image`, `icon`, `css`, `color`

## 📁 Contexto do Projeto

O script lê `PROJECT_CONTEXT.md` se existir para ajustar a classificação:

### Ajustes automáticos

- **Setor público**: Aumenta peso de segurança e dados sensíveis (+20-30%)
- **Dados sensíveis**: Classificação mais rigorosa para mudanças com dados
- **Sistema crítico**: Considera impacto mais amplo

### Exemplo de PROJECT_CONTEXT.md

```markdown
# Contexto do Projeto

**Setor:** Público (governo municipal)
**Dados:** Sensíveis (LGPD aplicável)
**Usuários:** 50.000 cidadãos
**Criticidade:** Alta (sistema de saúde)
```

## 📋 Recomendações por Nível

### CRITICAL (🔴)

- 🔴 Revisão obrigatória por pares
- 🔴 Testes extensivos (unitários, integração, e2e)
- 🔴 Plano de rollback definido
- 🔴 ADR obrigatório
- 🔴 Deploy em horário de baixo impacto

### PROFESSIONAL (🟡)

- 🟡 Auto-revisão estruturada
- 🟡 Testes unitários obrigatórios
- 🟡 Atualizar documentação relevante
- 🟡 Quality gate antes do commit
- 🟡 Deploy planejado

### ESSENTIAL (🟢)

- 🟢 Revisão opcional
- 🟢 Testes básicos se aplicável
- 🟢 Atualizar comentários/changelog
- 🟢 Verificações rápidas antes do commit
- 🟢 Deploy em qualquer horário

## 🔌 Integração

### Com Pi.dev

```bash
# No Pi.dev, use o skill:
/skill:classify-change-risk "Descrição da mudança"

# Ou execute diretamente:
!python3 classify_risk.py "Descrição" --format json
```

### Com OpenSpec workflow

```bash
# Antes de criar change no OpenSpec
python3 classify_risk.py "$DESCRIPTION" --format json > risk_assessment.json

# Usar resultado para criar change apropriado
LEVEL=$(jq -r '.risk_assessment.level' risk_assessment.json)
echo "Criando change com nível: $LEVEL"
```

### Com Git hooks

```bash
# .git/hooks/prepare-commit-msg
#!/bin/bash
DESCRIPTION=$(cat "$1")
RISK=$(python3 classify_risk.py "$DESCRIPTION" --format text)
echo -e "\n\n=== RISK ASSESSMENT ===\n$RISK" >> "$1"
```

### Em scripts de CI/CD

```bash
# Classificar PR description
python3 classify_risk.py "$PR_DESCRIPTION" --format json

# Determinar se precisa revisão especial
if jq -e '.risk_assessment.level == "CRITICAL"' risk.json; then
  echo "🚨 PR CRITICAL - requer revisão especial"
  # Adicionar reviewers específicos
fi
```

## 🐍 API Python

Use como módulo em seus scripts:

```python3 from classify_risk import classify_change, analyze_text

# Classificar mudança
result = classify_change("Implementar autenticação JWT com refresh tokens")

print(f"Nível: {result['risk_assessment']['level']}")
print(f"Score: {result['risk_assessment']['score']}")

# Ver recomendações
for rec in result['recommendations'][:5]:
    print(f"- {rec}")

# Análise de texto separada
analysis = analyze_text("Correção de bug no módulo de pagamento")
print(f"Palavras críticas: {analysis['keyword_counts']['critical']}")
```

## 📄 Formatos de Output

### Texto (padrão)

```
============================================================
CLASSIFICAÇÃO DE RISCO DE MUDANÇA
============================================================
Data: 2026-03-02 21:15:30
Descrição: Implementar criptografia para dados sensíveis...

🔴 NÍVEL: CRITICAL
📊 Score: 12.4 (confiança: 82.7%)

RECOMENDAÇÕES:
  🔴 Revisão obrigatória...
  🔴 Testes extensivos...
  ...
============================================================
```

### JSON

```json
{
  "description_preview": "Implementar criptografia...",
  "analysis": {
    "keyword_counts": {"critical": 5, "professional": 2, "essential": 0},
    "keyword_matches": {"critical": ["encryption", "sensitive data"]},
    "patterns": {"has_security_terms": true, "has_data_terms": true}
  },
  "risk_assessment": {
    "score": 12.4,
    "level": "CRITICAL",
    "color": "🔴",
    "confidence": 82.7,
    "factors": {...}
  },
  "recommendations": [...]
}
```

### Markdown

```markdown
# Classificação de Risco: 🔴 CRITICAL

**Data:** 2026-03-02 21:15:30  
**Descrição:** Implementar criptografia...

## 📊 Resultado

- **Nível:** 🔴 CRITICAL
- **Score:** 12.4
- **Confiança:** 82.7%

## 🔍 Análise

### Palavras-chave por nível
- 🔴 **CRITICAL:** 5 palavras
- 🟡 **PROFESSIONAL:** 2 palavras
- 🟢 **ESSENTIAL:** 0 palavras

## 📋 Recomendações
1. 🔴 Revisão obrigatória...
2. 🔴 Testes extensivos...
...
```

## ⚙️ Opções Avançadas

### Modo verboso

```bash
python3 classify_risk.py "Descrição" --verbose
# Mostra análise detalhada, palavras-chave específicas, fatores
```

### Ajustar limiares (editar código)

```python3 # Em classify_risk.py, ajuste:
THRESHOLDS = {
    "critical": 8.0,    # Aumentar para ser mais rigoroso
    "professional": 4.0, # Ajustar conforme necessidade
    "essential": 0.0
}
```

### Adicionar palavras-chave personalizadas

```python3 # Adicione em RISK_KEYWORDS:
RISK_KEYWORDS["critical"].extend([
    "meu_termo_critico",
    "outro_termo_importante"
])
```

## 🧪 Testes

### Testar com exemplos

```bash
# Testes rápidos
python3 classify_risk.py "Correção de typo"
python3 classify_risk.py "Nova API REST"
python3 classify_risk.py "Migração de banco de dados com dados sensíveis"

# Teste com arquivo
echo "Implementar autenticação two-factor" > test.txt
python3 classify_risk.py --file test.txt --format json
```

### Validar classificação

```bash
# Script de validação
#!/bin/bash
echo "Testando classificações..."
python3 classify_risk.py "typo fix" | grep -q "ESSENTIAL" && echo "✅ ESSENTIAL OK"
python3 classify_risk.py "new feature" | grep -q "PROFESSIONAL" && echo "✅ PROFESSIONAL OK"
python3 classify_risk.py "security fix" | grep -q "CRITICAL" && echo "✅ CRITICAL OK"
```

## 📝 Licença

MIT - veja [LICENSE](LICENSE)

## 🤝 Contribuição

1. Fork o repositório
2. Crie uma branch: `git checkout -b minha-melhoria`
3. Commit: `git commit -am 'Adiciona palavras-chave para fintech'`
4. Push: `git push origin minha-melhoria`
5. Abra um Pull Request

### Áreas para melhoria

- Suporte a mais idiomas (português nativo)
- Integração com spacy/NLTK para NLP avançado
- Aprendizado de máquina para ajuste automático
- Plugins para diferentes domínios (saúde, financeiro, etc.)

## 📞 Suporte

- **Issues**: Reporte bugs ou sugestões de palavras-chave
- **Documentação**: Consulte `SKILL.md` para uso no Pi.dev
- **Customização**: Edite `RISK_KEYWORDS` e `THRESHOLDS` para seu domínio
