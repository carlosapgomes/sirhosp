---
name: project-context-maintainer
description: Analisa o projeto atual e gera/atualiza o PROJECT_CONTEXT.md com resumo executivo, arquitetura, regras não negociáveis e estado do sistema.
---

# Skill: Project Context Maintainer

Este skill ajuda a criar e manter o arquivo `PROJECT_CONTEXT.md` - o resumo executivo do projeto para retomada fácil após pausas longas. Extrai informações do código, documentação e configurações para manter o contexto atualizado.

## Quando usar

- Iniciando um novo projeto e precisa do resumo executivo
- Retomando trabalho após pausa longa (semanas/meses)
- O sistema evoluiu significativamente e o contexto está desatualizado
- Preparando o projeto para ser forkado por outros departamentos
- Antes de uma entrega/release importante

## 🐍 Método Recomendado: Script Python

Este skill inclui `maintain_project_context.py` para gerar/atualizar `PROJECT_CONTEXT.md`.

```bash
# gerar/atualizar arquivo na raiz do projeto
python3 maintain_project_context.py --project-root .

# verificar drift (exit 0=ok, 2=desatualizado)
python3 maintain_project_context.py --project-root . --check

# visualizar sinais detectados em JSON
python3 maintain_project_context.py --project-root . --format json
```

## O que é PROJECT_CONTEXT.md

Arquivo de resumo executivo que contém:

- **Propósito**: Por que o sistema existe, para quem, valor principal
- **Fontes autoritativas**: Onde encontrar informações detalhadas
- **Objetivo do sistema**: O que faz em alto nível
- **Arquitetura de alto nível**: Componentes principais e fluxos
- **Regras não negociáveis**: Constraints imutáveis
- **Quality bar**: Padrões mínimos de qualidade

## Análise automática do projeto

Para gerar/atualizar o PROJECT_CONTEXT.md, analise:

### 1. Propósito e objetivo

```bash
# Ler README.md para entender propósito
head -50 README.md 2>/dev/null

# Verificar descrição em package.json/pyproject.toml
grep -i "description" package.json pyproject.toml 2>/dev/null

# Verificar tags/tópicos
find . -name "*.md" -type f | xargs grep -l "## Purpose\|## Objective" 2>/dev/null
```

### 2. Stack tecnológica atual

```bash
# Linguagens principais
find . -type f \( -name "*.py" -o -name "*.js" -o -name "*.ts" -o -name "*.go" -o -name "*.java" \) | head -20

# Dependências principais
cat requirements.txt pyproject.toml package.json go.mod 2>/dev/null | head -30

# Framework identificação
find . -name "manage.py" -o -name "next.config.*" -o -name "vue.config.*" -o -name "angular.json" 2>/dev/null
```

### 3. Arquitetura de alto nível

```bash
# Estrutura de diretórios principais
ls -la | head -20
find . -maxdepth 2 -type d | sort

# Componentes principais
find . -type d \( -name "controllers" -o -name "services" -o -name "models" -o -name "components" -o -name "api" \) 2>/dev/null

# Configurações de arquitetura
find . -name "docker-compose*.yml" -o -name "Dockerfile" -o -name "k8s" -type d 2>/dev/null
```

### 4. Regras de negócio importantes

```bash
# Procurar por comentários/chaves de regras de negócio
grep -r "TODO\|FIXME\|HACK\|business rule\|regra.*negócio" . --include="*.py" --include="*.js" --include="*.ts" --include="*.md" 2>/dev/null | head -10

# Verificar configurações de validação
find . -name "*config*.py" -o -name "*settings*.py" -o -name ".env*" 2>/dev/null | head -5
```

## Template adaptativo

```markdown
# PROJECT_CONTEXT.md

## Propósito
{{purpose_section}}

## Fontes Autoritativas
{{authoritative_sources}}

## Objetivo do Sistema
{{system_objective}}

## Arquitetura de Alto Nível
{{high_level_architecture}}

## Regras Não Negociáveis
{{non_negotiable_rules}}

## Quality Bar
{{quality_bar}}
```

## Seções detalhadas

### 1. Propósito

Explicar POR QUE o projeto existe:

```markdown
## Propósito
Resumo executivo para retomar trabalho após pausas longas ou para novos contribuidores. 
Documenta o estado atual do sistema, decisões importantes e constraints.

**Público-alvo:**
- Desenvolvedor retomando trabalho após semanas/meses
- Novo contribuidor entendendo o sistema
- Outro departamento considerando fork do repositório
- Auditor verificando decisões arquiteturais
```

### 2. Fontes Autoritativas

Onde encontrar a verdade sobre o sistema:

```markdown
## Fontes Autoritativas
- **Handoff completo**: `prompts/handoff.md` (se existir)
- **Especificações**: `openspec/specs/` (source of truth)
- **Decisões arquiteturais**: `docs/adr/`
- **Código-fonte**: Diretório principal do projeto
- **Em caso de conflito**: Seguir specs > código > documentação

**Nota:** O `prompts/handoff.md` pode conter informações sensíveis e deve estar no `.gitignore` se for o caso.
```

### 3. Objetivo do Sistema

O QUE o sistema faz em alto nível:

```markdown
## Objetivo do Sistema
[Sistema] permite [usuários] realizar [ação principal] para [valor gerado].

**Funcionalidades principais:**
1. [Funcionalidade 1]: [breve descrição]
2. [Funcionalidade 2]: [breve descrição]
3. [Funcionalidade 3]: [breve descrição]

**Valor gerado:**
- [Benefício 1]
- [Benefício 2]
- [Benefício 3]
```

### 4. Arquitetura de Alto Nível

Componentes e fluxos principais:

```markdown
## Arquitetura de Alto Nível

### Componentes Principais
1. **[Componente A]**: Responsabilidade principal
   - Tecnologia: [tecnologia]
   - Localização: `caminho/para/componente`
   - Interface: [como se comunica]

2. **[Componente B]**: Responsabilidade principal
   - Tecnologia: [tecnologia]
   - Localização: `caminho/para/componente`
   - Interface: [como se comunica]

### Fluxos de Dados
1. **Fluxo principal**: [descrição do fluxo]
   ```

   Usuário → [Componente A] → [Componente B] → Persistência

   ```

2. **Fluxo secundário**: [descrição do fluxo]
   ```

   Evento → [Componente C] → [Componente A] → Resposta

   ```

### Infraestrutura
- **Banco de dados**: [tipo, localização]
- **Cache**: [solução, se aplicável]
- **Fila/mensageria**: [solução, se aplicável]
- **Containerização**: Docker, docker-compose, Kubernetes
```

### 5. Regras Não Negociáveis

Constraints que NÃO podem ser violadas:

```markdown
## Regras Não Negociáveis

### Regras de Negócio
1. **[Regra 1]**: [descrição] (ex: "Usuários devem autenticar via SSO do governo")
2. **[Regra 2]**: [descrição] (ex: "Dados sensíveis devem ser criptografados em repouso")

### Constraints Técnicas
1. **[Constraint 1]**: [descrição] (ex: "Compatibilidade com Python 3.12+")
2. **[Constraint 2]**: [descrição] (ex: "API deve seguir padrão RESTful")

### Conformidade/Regulatório
1. **[Requisito 1]**: [descrição] (ex: "Conformidade com LGPD")
2. **[Requisito 2]**: [descrição] (ex: "Logs devem ser mantidos por 5 anos")
```

### 6. Quality Bar

Padrões mínimos de qualidade:

```markdown
## Quality Bar

### Testes
- **Cobertura mínima**: 80% (linhas de código)
- **Tempo de execução**: < 2 minutos para suite completa
- **Tipos**: 70% unitários, 25% integração, 5% E2E
- **Automáticos**: Todos os testes rodam em CI

### Código
- **Lint**: Zero warnings no CI
- **Complexidade ciclomática**: < 15 por função/método
- **Dívida técnica**: < 5% do código marcado como TODO/FIXME

### Segurança
- **Dependências**: Escaneamento regular por vulnerabilidades
- **Segredos**: Zero segredos no código-fonte
- **Auditoria**: Logs de todas as operações críticas

### Performance
- **Tempo de resposta**: < 200ms para 95% das requisições
- **Uso de memória**: < 512MB por instância
- **Escalabilidade**: Suporte a pelo menos 100 usuários concorrentes
```

## Processo de geração/atualização

### Para novo PROJECT_CONTEXT.md

1. Analisar projeto (propósito, stack, arquitetura)
2. Identificar regras importantes (business, technical, compliance)
3. Definir quality bar baseado em padrões do projeto
4. Escrever em linguagem clara para retomada futura
5. Salvar como `PROJECT_CONTEXT.md` na raiz

### Para atualização

1. Ler `PROJECT_CONTEXT.md` existente
2. Comparar com estado atual do projeto
3. Identinar lacunas/desatualizações
4. Atualizar seções necessárias mantendo estrutura
5. Preservar informações históricas importantes

## Exemplo para projeto Django

```markdown
# PROJECT_CONTEXT.md

## Propósito
Sistema de gestão de processos administrativos para secretaria municipal.

## Fontes Autoritativas
- Handoff: `prompts/handoff.md` (contém regras de negócio detalhadas)
- Specs: `openspec/specs/` (requisitos funcionais)
- ADRs: `docs/adr/` (decisões arquiteturais)
- Código: Diretório `app/` (implementação)

## Objetivo do Sistema
Sistema de Gestão de Processos (SGP) permite servidores públicos gerenciar processos administrativos digitalmente, reduzindo tempo de tramitação e aumentando transparência.

**Funcionalidades principais:**
1. **Cadastro de processos**: Criar, editar, arquivar processos
2. **Tramitação digital**: Fluxo de aprovações com assinatura digital
3. **Pesquisa e relatórios**: Busca avançada e geração de relatórios
4. **Integração com sistemas governamentais**: SIAPE, SEI, outros

**Valor:**
- Redução de 70% no tempo de tramitação
- Eliminação de papel
- Transparência completa do andamento

## Arquitetura de Alto Nível

### Componentes Principais
1. **Backend Django**: Lógica de negócio e API REST
   - Tecnologia: Python 3.12, Django 5.0, Django REST Framework
   - Localização: `backend/`
   - Interface: API REST em `api/v1/`

2. **Frontend HTMX**: Interface web responsiva
   - Tecnologia: HTML, HTMX, Bootstrap 5, JavaScript
   - Localização: `frontend/templates/`
   - Interface: Templates Django com HTMX

3. **Banco de Dados PostgreSQL**: Persistência
   - Tecnologia: PostgreSQL 15 com pgcrypto
   - Localização: Container separado
   - Interface: Django ORM

### Fluxos de Dados
1. **Fluxo de criação de processo**:
   ```

   Usuário → Template Django → View → Service → Model → PostgreSQL

   ```

2. **Fluxo de tramitação**:
   ```

   Evento HTMX → View → Workflow Service → Notificação → Status update

   ```

### Infraestrutura
- **Banco**: PostgreSQL 15 em container Docker
- **Cache**: Redis (opcional, para sessões)
- **Fila**: Celery + Redis para tarefas assíncronas
- **Containerização**: Docker Compose para desenvolvimento

## Regras Não Negociáveis

### Regras de Negócio
1. **Autenticação via SSO Governo**: Todos os usuários devem autenticar via SSO do governo estadual
2. **Assinatura digital obrigatória**: Todas as aprovações requerem assinatura digital válida
3. **Imutabilidade de processos finalizados**: Processos arquivados não podem ser modificados

### Constraints Técnicas
1. **Compatibilidade Python 3.12+**: Deve rodar na versão suportada pelo governo
2. **PostgreSQL com pgcrypto**: Para criptografia de dados sensíveis
3. **API RESTful**: Para futura integração com outros sistemas

### Conformidade
1. **LGPD**: Todos os dados pessoais protegidos
2. **Auditoria completa**: Logs de todas as alterações mantidos por 10 anos
3. **Backup diário**: Backup completo do banco com retenção de 30 dias

## Quality Bar

### Testes
- **Cobertura**: 85% mínimo (crítico para sistema governamental)
- **Tempo**: < 3 minutos para suite completa
- **Tipos**: 60% unit, 30% integration, 10% E2E (fluxos críticos)

### Código
- **Lint**: `ruff check .` com zero warnings
- **Type check**: `mypy .` para código tipado
- **Complexidade**: Funções < 20 linhas, métodos < 15

### Segurança
- **OWASP Top 10**: Proteções implementadas
- **Dependências**: `safety check` sem vulnerabilidades críticas
- **Segredos**: Variáveis de ambiente, nunca no código

### Performance
- **Tempo resposta**: < 300ms para 99% das requisições
- **Concorrência**: 50 usuários simultâneos mínimo
- **Disponibilidade**: 99.5% em produção
```

## Integração com workflow ESAA

### Para retomada de trabalho

1. Sempre ler `PROJECT_CONTEXT.md` antes de começar
2. Atualizar se necessário se encontrar desalinhamentos
3. Usar como base para prompts de reentrada com IA

### Para novos contribuidores

1. `PROJECT_CONTEXT.md` é o ponto de entrada principal
2. Seguir para `AGENTS.md` para detalhes de implementação
3. Consultar `docs/adr/` para entender decisões

## Dicas para projetos do setor público

1. **Clareza acima de brevidade**: Escreva para não-especialistas técnicos
2. **Rastreabilidade**: Link para documentos oficiais, normativos
3. **Conformidade explícita**: Liste leis, regulamentos aplicáveis
4. **Histórico de decisões**: Inclua razões para escolhas importantes
5. **Fork-friendly**: Imagine outro departamento usando este documento para continuar o projeto

## Checklist de validação

- [ ] Propósito claro e completo
- [ ] Fontes autoritativas atualizadas e acessíveis
- [ ] Objetivo do sistema descrito em linguagem de negócio
- [ ] Arquitetura reflete estado atual do código
- [ ] Regras não negociáveis identificadas e justificadas
- [ ] Quality bar realista e mensurável
- [ ] Linguagem apropriada para retomada após meses
- [ ] Links funcionais para documentos referenciados
