---
name: adr-generator
description: Cria ou atualiza Architecture Decision Records (ADRs) com numeração automática, template consistente e manutenção de índice.
---

# Skill: ADR Generator

Este skill ajuda a criar, gerenciar e manter Architecture Decision Records (ADRs) seguindo o padrão do workflow ESAA Solopreneur. Inclui numeração sequencial automática, templates padronizados e gerenciamento de índice.

## Quando usar

- Tomando uma decisão arquitetural importante no projeto
- Mudando tecnologia, contrato ou política com impacto estrutural
- Documentando trade-offs para futuros contribuidores
- Projetos do setor público que requerem rastreabilidade de decisões
- Change classificado como HIGH/ARCH no workflow ESAA

## 🐍 Método Recomendado: Script Python

Este skill inclui `adr_generator.py` para criação determinística de ADRs com
numeração automática e atualização do índice.

```bash
# criar ADR nova
python3 adr_generator.py --project-root . --title "Escolha de PostgreSQL" --status Accepted

# mostrar próximo número sem criar arquivo
python3 adr_generator.py --project-root . --list-next --format json

# apenas reconstruir índice docs/adr/README.md
python3 adr_generator.py --project-root . --reindex
```

## O que é uma ADR

Uma Architecture Decision Record (ADR) é um documento que captura:

- **Contexto**: Situação que levou à decisão
- **Decisão**: O que foi decidido, com detalhes
- **Alternativas**: Outras opções consideradas e por que foram rejeitadas
- **Consequências**: Impactos positivos e negativos da decisão

## Estrutura de diretórios

```
docs/adr/
├── README.md              # Índice de ADRs
├── template.md           # Template para novas ADRs
├── ADR-0001-example.md   # ADR existente
├── ADR-0002-another.md
└── ...
```

## Template de ADR

```markdown
# ADR-XXXX: <Título descritivo>

## Status
[Proposed | Accepted | Deprecated | Superseded]

## Contexto
[Situação que motivou a decisão. Problema a resolver, constraints, requisitos.]

## Decisão
[O que foi decidido, com detalhes suficientes para implementação.
Incluir:
- Tecnologias/ferramentas escolhidas
- Padrões arquiteturais
- Mudanças na estrutura
- Justificativa técnica]

## Alternativas Consideradas
1. **[Alternativa 1]**: [Descrição breve]
   - **Vantagens**: [lista]
   - **Desvantagens**: [lista]
   - **Por que não escolhida**: [razão principal]

2. **[Alternativa 2]**: [Descrição breve]
   - **Vantagens**: [lista]
   - **Desvantagens**: [lista]
   - **Por que não escolhida**: [razão principal]

## Consequências
### Positivas
- [Benefício 1]
- [Benefício 2]
- [Benefício 3]

### Negativas/Trade-offs
- [Custo 1]
- [Custo 2]
- [Custo 3]

### Riscos e Mitigações
- [Risco 1]: [Mitigação]
- [Risco 2]: [Mitigação]
```

## Processo de criação

### 1. Determinar próximo número

```bash
# Listar ADRs existentes para determinar próximo número
find docs/adr -name "ADR-*.md" -type f | sort | tail -5

# Ou contar quantas existem
count=$(find docs/adr -name "ADR-*.md" -type f | wc -l)
next_number=$(printf "%04d" $((count + 1)))
```

### 2. Escolher título

- Descritivo e específico
- Incluir tecnologia/área afetada
- Ex: "escolha-postgres-como-banco-principal", "migracao-autenticacao-oauth2"

### 3. Preencher template

Use as seções abaixo como guia:

#### Status

- **Proposed**: Decisão proposta, ainda não implementada
- **Accepted**: Decisão aceita e em implementação/implementada
- **Deprecated**: Decisão obsoleta, não deve ser usada
- **Superseded**: Substituída por outra ADR

#### Contexto

Responder:

- Qual problema estamos resolvendo?
- Quais constraints temos (tempo, orçamento, skills)?
- Quais requisitos não negociáveis?
- Qual o estado atual do sistema?

#### Decisão

Ser específico:

- Versões exatas de tecnologias
- Configurações importantes
- Mudanças na estrutura de código
- Convenções a seguir

#### Alternativas

Listar pelo menos 2-3 alternativas consideradas.
Para cada uma:

- Breve descrição
- Vantagens objetivas
- Desvantagens objetivas
- Razão para rejeição

#### Consequências

- Impactos imediatos no desenvolvimento
- Impactos de longo prazo na manutenção
- Custos de migração/adaptação
- Riscos e como mitigá-los

## Exemplo completo

```markdown
# ADR-0001: Escolha do PostgreSQL como Banco de Dados Principal

## Status
Accepted

## Contexto
Precisamos escolher um banco de dados relacional para o sistema de gestão de processos do setor público. Requisitos:
- Suporte a transações ACID
- Conformidade com LGPD
- Backup e recuperação robustos
- Comunidade ativa e suporte a longo prazo
- Compatibilidade com Django ORM

## Decisão
Usaremos **PostgreSQL 15** como banco de dados principal, com:
- Extensão `pgcrypto` para criptografia de dados sensíveis
- WAL (Write-Ahead Logging) ativado para durability
- Backup diário via `pg_dump` + WAL archiving
- Pool de conexões via `pgbouncer` em produção
- Migrações gerenciadas pelo Django (`python3 manage.py migrate`)

## Alternativas Consideradas
1. **SQLite**: Banco embutido, zero configuração
   - Vantagens: Simplicidade, não requer servidor separado
   - Desvantagens: Concorrência limitada, não scale para produção
   - Por que não escolhida: Não atende requisitos de produção multi-usuário

2. **MySQL 8**: Banco relacional popular
   - Vantagens: Performance boa, ampla adoção
   - Desvantagens: Licenciamento mais complexo, features avançadas limitadas
   - Por que não escolhida: PostgreSQL tem melhor suporte a JSON, full-text search e conformidade SQL

## Consequências
### Positivas
- Conformidade completa com LGPD via criptografia nativa
- Recursos avançados (JSONB, full-text search, GIS) disponíveis
- Comunidade robusta e documentação excelente
- Integração nativa com Django

### Negativas/Trade-offs
- Mais complexidade de operação vs SQLite
- Requer servidor dedicado/container
- Curva de aprendizado para features avançadas

### Riscos e Mitigações
- **Risco**: Complexidade de backup/recuperação
  - **Mitigação**: Scripts automatizados e documentação detalhada
- **Risco**: Performance em alta concorrência
  - **Mitigação**: Pool de conexões, índices adequados, monitoramento
```

## Gerenciamento de índice

### README.md do diretório ADR

```markdown
# Architecture Decision Records

Registros de decisões arquiteturais importantes do projeto.

## ADRs Ativas
| Número | Título | Status | Data |
|--------|--------|--------|------|
| [ADR-0001](ADR-0001-escolha-postgres.md) | Escolha do PostgreSQL como Banco de Dados Principal | Accepted | 2026-03-01 |
| [ADR-0002](ADR-0002-autenticacao-oauth2.md) | Implementação de Autenticação OAuth2 | Proposed | 2026-03-02 |

## ADRs Deprecated/Superseded
| Número | Título | Status | Substituída por |
|--------|--------|--------|-----------------|
| [ADR-0003](ADR-0003-auth-basica.md) | Autenticação Básica | Superseded | ADR-0002 |

## Como criar uma nova ADR
1. Use o template em [template.md](template.md)
2. Determine o próximo número sequencial
3. Preencha todas as seções cuidadosamente
4. Atualize esta tabela de índice
5. Submeta para revisão se necessário
```

### Comandos para atualizar índice

```bash
# Gerar tabela automática de ADRs (simplificado)
echo "## ADRs Ativas" > docs/adr/README.md
echo "| Número | Título | Status | Data |" >> docs/adr/README.md
echo "|--------|--------|--------|------|" >> docs/adr/README.md

for file in docs/adr/ADR-*.md; do
  number=$(basename "$file" | cut -d'-' -f2 | cut -d'.' -f1)
  title=$(grep -m1 "^# ADR-$number: " "$file" | sed "s/# ADR-$number: //")
  status=$(grep -m1 "^## Status" -A1 "$file" | tail -1 | tr -d '[]')
  date=$(stat -f "%Sm" -t "%Y-%m-%d" "$file" 2>/dev/null || date -r "$file" "+%Y-%m-%d")
  echo "| [ADR-$number]($(basename "$file")) | $title | $status | $date |" >> docs/adr/README.md
done
```

## Quando criar uma ADR

Crie uma ADR para decisões que:

- Afetam a estrutura arquitetural principal
- Introduzem nova tecnologia com impacto significativo
- Mudam contratos externos (APIs, schemas)
- Afetam segurança ou compliance
- Tem custo alto de reversão
- São necessárias para entendimento futuro do sistema

**Não crie ADR para:**

- Escolhas triviais (ex: nome de variável)
- Decisões temporárias/experimentais
- Configurações de ambiente
- Mudanças de estilo de código

## Integração com workflow ESAA

### Para changes HIGH/ARCH

1. Classificar change como HIGH/ARCH (4+ pontos de risco)
2. Criar ADR como parte do processo
3. Referenciar ADR no `design.md` do change
4. Atualizar índice de ADRs

### Referência cruzada

No `design.md` do change:

```markdown
## Decisions
Ver ADR-XXXX para decisão detalhada sobre [tópico].
```

Na ADR:

```markdown
## Contexto
Esta decisão foi tomada como parte do change [change-id] ([proposal.md](openspec/changes/[change-id]/proposal.md)).
```

## Manutenção de ADRs

### Atualizar status

Quando uma decisão muda:

1. Atualizar campo **Status** na ADR
2. Adicionar nota de mudança no final:

   ```markdown
   ## Histórico de Mudanças
   - 2026-03-10: Status mudado de Proposed para Accepted
   - 2026-03-15: Adicionada mitigação para risco X
   ```

### Deprecar/Supersed

Quando uma ADR é substituída:

1. Mudar status para **Deprecated** ou **Superseded**
2. Adicionar campo "Superseded by: ADR-YYYY"
3. Atualizar índice

## Dicas para projetos do setor público

1. **Justificativa detalhada**: Documente alternativas e trade-offs completamente
2. **Conformidade**: Relacione decisões com requisitos regulatórios (LGPD, etc.)
3. **Rastreabilidade**: Link para changes, issues, documentos oficiais
4. **Clareza**: Escreva para auditores futuros, não apenas para desenvolvedores

## Checklist para nova ADR

- [ ] Número sequencial correto (próximo disponível)
- [ ] Título descritivo e específico
- [ ] Status inicial definido (geralmente Proposed ou Accepted)
- [ ] Contexto completo e claro
- [ ] Decisão específica e implementável
- [ ] Pelo menos 2 alternativas consideradas
- [ ] Consequências (positivas e negativas) listadas
- [ ] Riscos e mitigações identificados
- [ ] Arquivo salvo como `docs/adr/ADR-XXXX-titulo.md`
- [ ] Índice atualizado em `docs/adr/README.md`
- [ ] Referências cruzadas com changes/issues quando aplicável
