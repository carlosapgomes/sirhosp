---
name: agents-md-generator
description: Analisa o projeto atual e gera ou atualiza o AGENTS.md com stack, comandos de validação, arquitetura e regras específicas do projeto.
---

# Skill: AGENTS.md Generator

Este skill ajuda a criar ou atualizar o arquivo `AGENTS.md` - o contrato de execução com IAs - baseado na análise do projeto atual. Gera conteúdo personalizado para a stack, ferramentas e padrões encontrados.

## Quando usar

- Iniciando um novo projeto e precisa do AGENTS.md inicial
- A stack do projeto mudou (novas versões, ferramentas)
- Adicionando novas regras ou constraints arquiteturais
- Validando se o AGENTS.md atual está completo/atualizado

## 🐍 Método Recomendado: Script Python

Este skill inclui `generate_agents_md.py` para gerar/atualizar `AGENTS.md` de forma determinística.

```bash
# gerar/atualizar na raiz do projeto
python3 generate_agents_md.py --project-root .

# validar se AGENTS.md está atualizado (exit 0=ok, 2=desatualizado)
python3 generate_agents_md.py --project-root . --check

# inspecionar sinais detectados em JSON
python3 generate_agents_md.py --project-root . --format json
```

## Análise do projeto

Antes de gerar o AGENTS.md, analise o projeto para detectar:

### 1. Stack tecnológica

```bash
# Verificar linguagem principal
find . -name "*.py" -type f | head -5
find . -name "*.js" -type f | head -5
find . -name "*.ts" -type f | head -5
find . -name "*.go" -type f | head -5
find . -name "*.java" -type f | head -5

# Verificar gerenciador de pacotes
ls -la package.json pyproject.toml requirements.txt go.mod pom.xml build.gradle

# Verificar framework
find . -name "manage.py" -type f  # Django
find . -name "next.config.js" -type f  # Next.js
find . -name "vue.config.js" -type f  # Vue
find . -name "angular.json" -type f  # Angular
```

### 2. Ferramentas de qualidade

```bash
# Testes
find . -name "pytest.ini" -o -name "jest.config.js" -o -name "vitest.config.*"

# Lint
find . -name ".eslintrc*" -o -name ".prettierrc*" -o -name "ruff.toml"

# Type checking
find . -name "tsconfig.json" -o -name "mypy.ini"

# Build
find . -name "Makefile" -o -name "docker-compose.yml"
```

### 3. Estrutura de diretórios

```bash
# Padrões arquiteturais
find . -type d -name "models" -o -name "views" -o -name "controllers" -o -name "services" -o -name "components"
```

## Template adaptativo de AGENTS.md

Use este template como base, preenchendo as seções conforme a análise:

```markdown
# AGENTS.md

## 1. Stack e Versoes
{{stack_section}}

## 2. Comandos de Validacao (Quality Gate)
{{validation_commands}}

## 3. Comandos Essenciais (Operacao Local)
{{essential_commands}}

## 4. Arquitetura e Constraints
{{architecture_constraints}}

## 5. Politica de Testes
{{testing_policy}}

## 6. Stop Rule (CRUCIAL)
{{stop_rule}}

## 7. Definition of Done (DoD)
{{definition_of_done}}

## 8. Anti-patterns Proibidos
{{anti_patterns}}

## 9. Prompt de Reentrada
{{reentry_prompt}}
```

## Seções a preencher

### 1. Stack e Versões

Baseado na análise, liste a stack com versões específicas:

**Exemplo Python/Django:**

```markdown
## 1. Stack e Versões
- Python: 3.12 (usar `python3 --version` para confirmar)
- Django: 5.0 (verificar em `pyproject.toml` ou `requirements.txt`)
- Banco: PostgreSQL 15 (ou SQLite para desenvolvimento)
- Frontend: JavaScript (ES2022), HTMX, Bootstrap 5
- Ferramentas: OpenSpec para workflow, Docker para containers
```

**Exemplo JavaScript/Node.js:**

```markdown
## 1. Stack e Versões
- Node.js: 20.x (usar `.nvmrc` ou `package.json` engines)
- Framework: Express 4.x
- Banco: MongoDB 7.x / PostgreSQL 15
- Frontend: React 18, TypeScript 5.x
- Build: Vite 5.x
```

### 2. Comandos de Validação

Comandos que a IA DEVE rodar para validar mudanças:

**Exemplo Python:**

```markdown
## 2. Comandos de Validação
- Testes: `pytest -q` (ou `python3 -m pytest`)
- Lint: `ruff check .` (ou `flake8`, `pylint`)
- Type check: `mypy .` (se usando type hints)
- Formatação: `black .` (opcional para verificação)
- Build: `python3 manage.py check` (Django) ou `python3 -m build`
- Segurança: `bandit -r .` (opcional)
```

**Exemplo JavaScript:**

```markdown
## 2. Comandos de Validação
- Testes: `npm test` ou `jest`
- Lint: `npm run lint` ou `eslint .`
- Type check: `npm run type-check` ou `tsc --noEmit`
- Build: `npm run build`
- Audit: `npm audit` (opcional)
```

### 3. Arquitetura e Constraints

Diretrizes arquiteturais específicas do projeto:

**Exemplo Django (MTV):**

```markdown
## 3. Arquitetura e Constraints
- Direção: templates → views → services → models
- Models: apenas dados, validações simples
- Views: orquestração apenas, lógica em services
- Services: lógica de negócio complexa
- Templates: apenas apresentação, lógica mínima
- Não acople views diretamente a models complexos
```

**Exemplo Clean Architecture/Hexagonal:**

```markdown
## 3. Arquitetura e Constraints
- Direção: externo → aplicação → domínio
- Domínio: entidades e regras de negócio puras
- Aplicação: casos de uso, orquestração
- Externo: adaptadores para DB, APIs, UI
- Dependências apontam para dentro
```

### 4. Política de Testes

Regras para escrita de testes:

```markdown
## 4. Política de Testes
- TDD obrigatório para novas funcionalidades
- Distribuição: 70% unit, 25% integration, 5% E2E
- Nomeação: `test_<cenário>_<resultado_esperado>`
- Isolamento: testes não devem depender de estado externo
- Edge cases: testar entradas inválidas, limites, erros
```

### 5. Stop Rule (CRUCIAL)

Regra para evitar loops descontrolados:

```markdown
## 5. Stop Rule (CRUCIAL)
- Implemente UMA task slice do `tasks.md` por vez
- Após green (testes passam), faça commit
- Atualize `tasks.md` marcando [x] na task concluída
- **PARE e peça confirmação explícita para próxima task**
- Não continue sem confirmação do usuário
```

### 6. Definition of Done (DoD)

Critérios para considerar uma mudança pronta:

```markdown
## 6. Definition of Done (DoD)
- [ ] Build sem erros
- [ ] Todos os testes passam (nova cobertura se aplicável)
- [ ] Lint/type check sem warnings
- [ ] Tasks atualizadas no `tasks.md`
- [ ] Commit feito com mensagem descritiva
- [ ] Push realizado para branch remota
- [ ] Specs atualizadas (se usando OpenSpec)
```

### 7. Anti-patterns Proibidos

Problemas comuns a evitar no projeto:

```markdown
## 7. Anti-patterns Proibidos
- Não crie God classes/services (muitas responsabilidades)
- Não acople templates com lógica complexa
- Não ignore logs/telemetria em operações críticas
- Não use variáveis globais para estado compartilhado
- Não faça chamadas síncronas bloqueantes em loops
```

## Processo de geração/atualização

### Para novo AGENTS.md

1. Analisar projeto (stack, ferramentas, estrutura)
2. Preencher template com informações específicas
3. Salvar como `AGENTS.md` na raiz
4. Validar comandos (testar se existem)

### Para atualização

1. Ler `AGENTS.md` existente
2. Identificar seções desatualizadas
3. Comparar com análise atual do projeto
4. Atualizar seções necessárias
5. Manter regras específicas do projeto

## Comandos de exemplo para validação

Depois de gerar o AGENTS.md, valide os comandos:

```bash
# Testar se comandos existem/funcionam
cd /caminho/do/projeto

# Verificar se pytest está disponível
python3 -m pytest --version 2>/dev/null || echo "pytest não instalado"

# Verificar se ruff está disponível
ruff --version 2>/dev/null || echo "ruff não instalado"

# Verificar se mypy está disponível
mypy --version 2>/dev/null || echo "mypy não instalado"
```

## Integração com OpenSpec

Se o projeto usa OpenSpec, adicione:

```markdown
## 8. Integração OpenSpec (opcional)
- Use `/opsx:propose` para criar novos changes
- Use `/opsx:apply` para implementar tasks
- Use `/opsx:verify` para validar implementação
- Use `/opsx:archive` para finalizar changes
- Siga classificação de risco (ESSENCIAL/PROFISSIONAL/CRÍTICO)
```

## Dicas para projetos específicos

### Projetos Python/Django

- Incluir `python3 manage.py migrate` no DoD se mudar models
- Adicionar constraint: "Não coloque queries complexas em views"

### Projetos JavaScript/React

- Incluir `npm run build` no DoD
- Adicionar constraint: "Não use prop drilling excessivo"

### Projetos do setor público

- Incluir requisitos de compliance específicos
- Adicionar regras de auditoria/logging
- Especificar constraints de segurança de dados

## Checklist de validação final

- [ ] Stack corretamente identificada
- [ ] Comandos de validação testáveis/existentes
- [ ] Constraints arquiteturais alinhadas com código atual
- [ ] Stop Rule clara e obrigatória
- [ ] DoD abrangente mas realizável
- [ ] Anti-patterns relevantes ao projeto
- [ ] Formatação Markdown correta
