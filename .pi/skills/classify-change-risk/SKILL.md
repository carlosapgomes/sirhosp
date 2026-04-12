---
name: classify-change-risk
description: Analisa a descrição de uma proposta de change e classifica o risco (ESSENCIAL/PROFISSIONAL/CRÍTICO) baseado em critérios do workflow ESAA. Inclui script Python autônomo para análise determinística.
---

# Skill: Classify Change Risk

Este skill analisa a descrição de uma proposta de mudança (change) e classifica o nível de risco seguindo os critérios do workflow ESAA Solopreneur: ESSENCIAL (QUICK), PROFISSIONAL (FEATURE), ou CRÍTICO (HIGH/ARCH). Ajuda a determinar o modo de operação apropriado antes de criar artefatos OpenSpec.

**Novo:** Inclui script Python autônomo (`classify_risk.py`) para análise determinística com NLP básico e consideração de contexto do projeto.

## Quando usar

- Antes de criar um novo change com OpenSpec
- Ao escrever o `proposal.md` inicial
- Para validar classificação de risco existente
- Como parte da revisão de changes propostos
- Para treinar consistência na classificação de risco

## 🐍 Método Recomendado: Script Python

### Instalação rápida

```bash
# Copiar script para seu projeto
cp classify_risk.py /caminho/do/seu/projeto/

# Ou usar diretamente do diretório do skill
python3 ./classify_risk.py "Descrição da mudança"
```

### Uso básico

```bash
# Classificar descrição direta
python3 classify_risk.py "Correção de typo na documentação"

# Com fatores específicos
python3 classify_risk.py "Implementar autenticação JWT" --impact-users many --complexity high

# Ler de arquivo
python3 classify_risk.py --file change_description.txt

# Formato JSON (para scripts/CI)
python3 classify_risk.py "Migração do banco de dados" --format json

# Formato Markdown (para documentação)
python3 classify_risk.py "Nova funcionalidade" --format markdown

# Modo verboso (análise detalhada)
python3 classify_risk.py "Descrição" --verbose

# Modo legado de código de saída (PROFESSIONAL retorna 1)
python3 classify_risk.py "Descrição" --strict-exit-codes
```

### Integração com Pi.dev

```bash
# Executar via skill
/skill:classify-change-risk "Descrição da mudança"

# Ou executar script diretamente
!python3 classify_risk.py "Descrição" --format json
```

## 📋 Método Manual (Instruções Textuais)

Use este método se não quiser/puder usar o script Python.

### Critérios de classificação (ESAA v4.2)

Marque 1 ponto para cada critério que se aplica:

1. **Autenticação/Autorização**: Afeta login, permissões, segurança de acesso
2. **Dados persistidos**: Envolve banco de dados, migrações, armazenamento
3. **API pública/Contrato externo**: Impacta APIs públicas, integrações, contratos
4. **Segurança**: Tem implicações de segurança, proteção de dados
5. **Performance crítica**: Afeta performance de sistema, tempo de resposta
6. **Refatoração ampla**: Muda > 5 arquivos, estrutura significativa
7. **Rollback caro**: Reversão é complexa/custosa (dados, deploys)
8. **Impacto regulatório**: Afeta compliance, auditoria, normas

### Classificação

- **0-1 ponto**: ESSENCIAL (QUICK) 🟢
- **2-3 pontos**: PROFISSIONAL (FEATURE) 🟡
- **4+ pontos**: CRÍTICO (HIGH/ARCH) 🔴

## Processo de análise manual

### 1. Extrair palavras-chave da descrição

Analisar texto procurando por:

#### Categoria: Autenticação/Segurança

```regex
(login|logout|auth|authentication|password|permission|role|access|security|encrypt|ssl|tls|jwt|token|oauth|sso)
```

#### Categoria: Dados/Persistência

```regex
(database|db|postgresql|mysql|sqlite|mongodb|redis|migration|schema|table|column|index|backup|restore|import|export)
```

#### Categoria: API/Integração

```regex
(api|endpoint|rest|graphql|webhook|integration|third.party|external|service|microservice|contract|interface)
```

#### Categoria: Performance/Escalabilidade

```regex
(performance|speed|latency|response.time|throughput|scaling|load|concurrent|optimization|cache|memory|cpu)
```

#### Categoria: Refatoração/Estrutura

```regex
(refactor|restructure|architecture|design|pattern|module|component|abstraction|interface|decoupling)
```

#### Categoria: Compliance/Regulatório

```regex
(compliance|gdpr|lgpd|hipaa|regulation|audit|legal|privacy|pii|sensitive.data|government|public.sector)
```

### 2. Contar pontos por categoria

Para cada categoria com palavras-chave encontradas, adicionar 1 ponto.

### 3. Ajustar por contexto do projeto

Considerar fatores adicionais:

#### Projetos do setor público (LGPD/GDPR)

- Dados sensíveis: +1 ponto
- Sistema crítico (saúde, educação): +1 ponto
- Alto número de usuários (>10k): +1 ponto

#### Complexidade técnica

- Múltiplas dependências afetadas: +1 ponto
- Mudança em código legado/complexo: +1 ponto
- Requer conhecimento especializado: +1 ponto

### 4. Determinar nível final

Aplicar tabela de classificação com pontos ajustados.

## Exemplos completos

### Exemplo 1: ESSENCIAL (🟢)

**Descrição:** "Corrigir typo na mensagem de erro do formulário de contato"

**Análise:**

- Palavras-chave: "typo" (nenhuma categoria)
- Pontos: 0
- Contexto: Nenhum ajuste
- **Nível:** ESSENCIAL (QUICK)

**Recomendações:**

- Modo: QUICK
- Revisão: Auto-revisão rápida
- Testes: Testes existentes suficientes
- Documentação: Atualizar changelog apenas

### Exemplo 2: PROFISSIONAL (🟡)

**Descrição:** "Adicionar validação de CPF/CNPJ no cadastro de usuários"

**Análise:**

- Palavras-chave: "validação", "cadastro", "usuários"
- Categorias: Dados (usuários) = 1 ponto
- Pontos: 1
- Contexto: Validação de dados pessoais (LGPD) = +1 ponto
- **Total:** 2 pontos
- **Nível:** PROFISSIONAL (FEATURE)

**Recomendações:**

- Modo: FEATURE
- Revisão: Auto-revisão estruturada
- Testes: Testes unitários para validação
- Documentação: Comentar código, atualizar README se necessário
- LGPD: Considerar tratamento de dados pessoais

### Exemplo 3: CRÍTICO (🔴)

**Descrição:** "Implementar autenticação two-factor (2FA) com tokens TOTP"

**Análise:**

- Palavras-chave: "autenticação", "two-factor", "2FA", "tokens", "TOTP"
- Categorias:
  - Autenticação/Segurança = 1 ponto
  - Segurança (2FA) = 1 ponto
- Pontos: 2
- Contexto:
  - Segurança crítica = +1 ponto
  - Impacto todos usuários = +1 ponto
  - Dados sensíveis (autenticação) = +1 ponto
- **Total:** 5 pontos
- **Nível:** CRÍTICO (HIGH/ARCH)

**Recomendações:**

- Modo: HIGH/ARCH
- Revisão: Revisão detalhada (se disponível, pares)
- Testes: Testes extensivos (unitários, integração, segurança)
- Documentação: ADR obrigatório, atualizar AGENTS.md
- Segurança: Análise de segurança específica
- Rollback: Plano de reversão definido

## Template para análise manual

```markdown
# Análise de Risco: [TÍTULO DA MUDANÇA]

## Descrição
[Inserir descrição completa]

## Palavras-chave identificadas
- [Listar palavras-chave por categoria]

## Pontuação
### Critérios ESAA (1 ponto cada):
- [ ] Autenticação/Autorização
- [ ] Dados persistidos
- [ ] API pública/Contrato externo
- [ ] Segurança
- [ ] Performance crítica
- [ ] Refatoração ampla
- [ ] Rollback caro
- [ ] Impacto regulatório

**Total ESAA:** [X] pontos

### Ajustes de contexto:
- [ ] Setor público/LGPD: +[X]
- [ ] Sistema crítico: +[X]
- [ ] Complexidade técnica: +[X]
- [ ] Dependências: +[X]

**Total ajustado:** [Y] pontos

## Classificação
- [ ] 🟢 ESSENCIAL (0-1 pontos)
- [ ] 🟡 PROFISSIONAL (2-3 pontos)
- [ ] 🔴 CRÍTICO (4+ pontos)

**Nível final:** [NÍVEL]

## Recomendações
### Para o nível [NÍVEL]:
- [Recomendação 1]
- [Recomendação 2]
- [Recomendação 3]

### Próximos passos:
1. [Passo 1]
2. [Passo 2]
3. [Passo 3]
```

## Script bash para análise rápida

### classify-risk.sh

```bash
#!/bin/bash
# classify-risk.sh - Análise rápida de risco

DESCRIPTION="$1"

echo "🔍 Analisando: $DESCRIPTION"
echo ""

# Contar ocorrências de palavras-chave
CRITICAL_WORDS=("security" "auth" "password" "database" "migration" "api" "gdpr" "lgpd")
PRO_WORDS=("feature" "test" "refactor" "performance" "ui" "ux")
ESSENTIAL_WORDS=("typo" "fix" "comment" "documentation" "style")

count_critical=0
count_pro=0
count_essential=0

for word in "${CRITICAL_WORDS[@]}"; do
    if echo "$DESCRIPTION" | grep -qi "$word"; then
        ((count_critical++))
    fi
done

for word in "${PRO_WORDS[@]}"; do
    if echo "$DESCRIPTION" | grep -qi "$word"; then
        ((count_pro++))
    fi
done

for word in "${ESSENTIAL_WORDS[@]}"; do
    if echo "$DESCRIPTION" | grep -qi "$word"; then
        ((count_essential++))
    fi
done

# Classificar
total_score=$((count_critical*3 + count_pro*2 + count_essential*1))

echo "📊 Contagem:"
echo "  🔴 Críticas: $count_critical"
echo "  🟡 Profissionais: $count_pro"
echo "  🟢 Essenciais: $count_essential"
echo "  📈 Score: $total_score"
echo ""

if [ $total_score -ge 8 ]; then
    echo "🎯 NÍVEL: 🔴 CRÍTICO"
    echo "📋 Recomendações:"
    echo "  - Revisão obrigatória"
    echo "  - Testes extensivos"
    echo "  - ADR necessário"
    echo "  - Plano de rollback"
elif [ $total_score -ge 4 ]; then
    echo "🎯 NÍVEL: 🟡 PROFISSIONAL"
    echo "📋 Recomendações:"
    echo "  - Auto-revisão estruturada"
    echo "  - Testes unitários"
    echo "  - Documentação relevante"
else
    echo "🎯 NÍVEL: 🟢 ESSENCIAL"
    echo "📋 Recomendações:"
    echo "  - Revisão rápida"
    echo "  - Testes básicos"
    echo "  - Atualizar changelog"
fi
```

### Uso

```bash
chmod +x classify-risk.sh
./classify-risk.sh "Implementar autenticação two-factor"
```

## Integração com workflow OpenSpec

### Antes de criar change

```bash
# Analisar proposta
DESCRIPTION="Implementar criptografia para dados sensíveis"
./classify-risk.sh "$DESCRIPTION"

# Ou usar script Python
python3 classify_risk.py "$DESCRIPTION" --format json > risk.json

# Extrair nível
LEVEL=$(jq -r '.risk_assessment.level' risk.json)
echo "Criando change com nível: $LEVEL"

# Criar change no OpenSpec com nível apropriado
# /opsx:propose --level $LEVEL "$DESCRIPTION"
```

### No proposal.md

```markdown
# Proposal: [Título]

## Risk Assessment
**Level:** CRITICAL (🔴)
**Score:** 12.4
**Confidence:** 82.7%

### Analysis
- Security terms detected: encryption, sensitive data
- Data protection impact: High (LGPD applicable)
- User impact: All users

### Recommendations
1. Security review required
2. Extensive testing mandatory
3. Rollback plan needed
4. Deploy during low-traffic hours
```

### No AGENTS.md (seção de validação)

```markdown
## Validation Commands
# Para changes CRITICAL:
- Security scan: `bandit -r . -q`
- LGPD compliance check: `python3 check_lgpd.py`
- Load testing: `locust --headless -u 100 -r 10`

# Para changes PROFESSIONAL:
- Unit tests: `pytest tests/ -xvs`
- Integration tests: `pytest tests/integration/`

# Para changes ESSENTIAL:
- Quick tests: `pytest -q`
- Lint check: `ruff check .`
```

## Checklist para classificação consistente

### Antes de classificar

- [ ] Ler descrição completa da mudança
- [ ] Considerar contexto do projeto (PROJECT_CONTEXT.md)
- [ ] Verificar histórico similar (changes anteriores)
- [ ] Consultar AGENTS.md para padrões

### Durante análise

- [ ] Extrair palavras-chave objetivamente
- [ ] Aplicar critérios ESAA consistentemente
- [ ] Considerar fatores de contexto
- [ ] Documentar justificativa

### Após classificação

- [ ] Registrar nível no proposal.md
- [ ] Seguir recomendações do nível
- [ ] Ajustar estimativas de tempo
- [ ] Comunicar nível para stakeholders (se necessário)

## Para projetos do setor público

### Considerações especiais

1. **LGPD/GDPR**: Dados pessoais sempre aumentam risco
2. **Transparência**: Classificação deve ser justificável publicamente
3. **Auditoria**: Registro de classificação deve ser claro
4. **Continuidade**: Changes devem ser forkable/resumable

### Template para setor público

```markdown
# Classificação de Risco - [Órgão Público]

## Mudança
[Descrição completa]

## Impacto em Dados Pessoais (LGPD)
- [ ] Não aplicável
- [ ] Dados não-pessoais
- [ ] Dados pessoais não sensíveis
- [ ] Dados pessoais sensíveis

## Justificativa Pública
[Explicação acessível para cidadãos]

## Nível de Risco
- [ ] 🟢 BAIXO (ESSENCIAL)
- [ ] 🟡 MÉDIO (PROFISSIONAL)
- [ ] 🔴 ALTO (CRÍTICO)

## Medidas de Mitigação
[Para riscos médio/alto]
```

## 📁 Arquivos do Skill

```
classify-change-risk/
├── SKILL.md                    # Esta documentação
├── classify_risk.py            # Script Python autônomo (recomendado)
├── README.md                   # Documentação do script Python
├── requirements.txt            # Dependências opcionais
├── LICENSE                     # Licença MIT
└── (scripts/ directory)        # Scripts bash de exemplo
```

## 🐍 Vantagens do Script Python

### Comparação

| Aspecto | Script Python | Análise Manual |
|---------|---------------|----------------|
| **Consistência** | ✅ Mesmos critérios sempre | ❌ Varia com interpretação |
| **Velocidade** | ✅ Análise em milissegundos | ❌ Minutos para análise detalhada |
| **Contexto** | ✅ Lê PROJECT_CONTEXT.md automaticamente | ❌ Manual, pode esquecer |
| **Recomendações** | ✅ Específicas por nível e contexto | ❌ Genéricas, podem faltar detalhes |
| **Integração** | ✅ JSON parseável, APIs | ❌ Apenas texto humano |
| **Aprendizado** | ✅ Pode melhorar com uso (futuro) | ❌ Estático |

### Use o script Python para

- Classificação rápida e consistente
- Integração com CI/CD/OpenSpec
- Projetos com muitos changes
- Setor público (LGPD, transparência)
- Treinamento de novos colaboradores

### Use análise manual para

- Changes muito complexos/únicos
