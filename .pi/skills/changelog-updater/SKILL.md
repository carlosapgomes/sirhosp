---
name: changelog-updater
description: Analisa commits desde a última release/tag e atualiza o CHANGELOG.md seguindo Conventional Commits ou padrão do projeto.
---

# Skill: Changelog Updater

Este skill ajuda a manter o CHANGELOG.md atualizado automaticamente, analisando commits desde a última tag/release e gerando entries no formato apropriado. Suporta Conventional Commits e pode ser adaptado para projetos do setor público.

## Quando usar

- Após completar uma série de changes e antes de criar uma nova release
- Para manter histórico automático de mudanças em repositórios públicos
- Como parte do processo de geração de Release Evidence Pack
- Para garantir que todas as mudanças sejam documentadas para auditores/futuros contribuidores

## Método recomendado (script)

Use o script incluído para geração determinística de changelog:

```bash
python3 update_changelog.py --project-root .
python3 update_changelog.py --project-root . --dry-run
python3 update_changelog.py --project-root . --release v1.2.0 --format json
python3 update_changelog.py --project-root . --from-ref v1.1.0 --to-ref HEAD
python3 update_changelog.py --project-root . --dry-run --fail-on empty
```

Exit codes: `0` ok, `1` erro de execução, `2` policy fail (`--fail-on`).

## Formatos suportados

### 1. Conventional Commits (Recomendado)

```
<type>(<scope>): <description>

[body]

[footer]
```

### 2. Keep a Changelog (Padrão comum)

```markdown
# Changelog

## [Unreleased]
### Added
- Nova funcionalidade X

### Changed
- Melhoria em Y

### Fixed
- Correção de bug Z

## [1.1.0] - 2026-03-15
### Added
- Autenticação SSO
```

### 3. Simples (Para projetos pequenos)

```markdown
## v1.2.0 (2026-03-15)
- **Added**: Nova funcionalidade de exportação
- **Changed**: Melhor performance em consultas
- **Fixed**: Correção de vulnerabilidade XSS
```

## Análise de commits

### 1. Identificar última tag

```bash
# Última tag no repositório
git describe --tags --abbrev=0 2>/dev/null || echo "Nenhuma tag encontrada"

# Ou data da última release do CHANGELOG.md
grep -n "## \[" CHANGELOG.md | head -2
```

### 2. Coletar commits desde última tag

```bash
# Se houver tag
git log --oneline --no-merges v1.0.0..HEAD

# Se não houver tag, todos os commits
git log --oneline --no-merges

# Com mais detalhes (para parsing)
git log --pretty=format:"%h|%s|%an|%ad" --date=short v1.0.0..HEAD
```

### 3. Classificar commits por tipo

Para Conventional Commits:

```bash
# Padrões comuns
git log --oneline v1.0.0..HEAD | grep -E "^(feat|fix|docs|style|refactor|test|chore|perf|build|ci)" || true

# Contar por tipo
git log --oneline v1.0.0..HEAD | sed -n 's/^[a-f0-9]* //p' | awk -F'[(:]' '{print $1}' | sort | uniq -c
```

## Template de CHANGELOG.md

### Estrutura recomendada (Keep a Changelog)

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]
### Added
- 

### Changed
- 

### Fixed
- 

### Deprecated
- 

### Removed
- 

### Security
- 

## [1.1.0] - 2026-03-15
### Added
- Autenticação via SSO governamental

### Changed
- Melhor performance em consultas de processos

### Fixed
- Vulnerabilidade XSS em templates
```

### Para projetos do setor público (mais detalhado)

```markdown
# Registro de Mudanças

Este documento registra todas as mudanças significativas no sistema [Nome do Sistema] mantido pela [Secretaria/Departamento].

## [Não Liberado]
### Novas Funcionalidades
- 

### Melhorias
- 

### Correções
- 

### Mudanças Arquiteturais
- 

### Conformidade/Segurança
- 

## [v1.2.0] - 2026-03-15
### Novas Funcionalidades
- **Integração com SSO Governo**: Autenticação única via sistema estadual
- **Exportação em PDF**: Geração de relatórios em formato PDF

### Melhorias  
- **Performance consultas**: Redução de 70% no tempo de consulta de processos
- **Acessibilidade**: Melhorias para leitores de tela

### Correções
- **Segurança**: Correção de vulnerabilidade XSS em campo de busca
- **Estabilidade**: Correção de memory leak em relatórios grandes

### Conformidade
- **LGPD**: Implementação de criptografia para dados sensíveis
- **Auditoria**: Logs completos de todas as operações administrativas
```

## Processo de atualização

### Para novo CHANGELOG.md

1. Criar arquivo com template apropriado
2. Adicionar seção [Unreleased] no topo
3. Preencher com commits desde início do projeto
4. Criar primeira versão (v1.0.0) com baseline

### Para atualização periódica

1. Ler CHANGELOG.md existente
2. Extrair commits desde última versão
3. Classificar por tipo (Added/Changed/Fixed/etc.)
4. Adicionar à seção [Unreleased]
5. Preparar para nova release

### Para criação de nova release

1. Mover conteúdo de [Unreleased] para nova versão
2. Adicionar data da release
3. Atualizar links de comparação (se usando GitHub/GitLab)
4. Limpar seção [Unreleased] para próximas mudanças

## Exemplo prático

### 1. Coletar commits

```bash
# Supondo última tag v1.1.0
git log --oneline --no-merges v1.1.0..HEAD

# Output exemplo:
# abc123 feat(auth): add SSO integration
# def456 perf(queries): optimize process search
# ghi789 fix(security): patch XSS vulnerability
# jkl012 docs: update API documentation
```

### 2. Classificar

```bash
# Manualmente ou com script
# feat → Added
# perf → Changed  
# fix → Fixed
# docs → Changed (documentação)
```

### 3. Gerar entrada

```markdown
## [Unreleased]
### Added
- **Autenticação SSO**: Integração com sistema de autenticação único do governo

### Changed
- **Performance**: Otimização de consultas de processos (70% mais rápido)
- **Documentação**: Atualização da documentação da API

### Fixed
- **Segurança**: Correção de vulnerabilidade XSS em campo de busca
```

### 4. Para release v1.2.0

```markdown
## [1.2.0] - 2026-03-15
### Added
- **Autenticação SSO**: Integração com sistema de autenticação único do governo

### Changed  
- **Performance**: Otimização de consultas de processos (70% mais rápido)
- **Documentação**: Atualização da documentação da API

### Fixed
- **Segurança**: Correção de vulnerabilidade XSS em campo de busca

## [Unreleased]
### Added
- 
### Changed
- 
### Fixed
- 
```

## Integração com workflow ESAA

### Relação com Release Evidence Pack

- **CHANGELOG.md**: Lista concisa de mudanças por versão
- **Release Evidence Pack**: Documento detalhado com specs, ADRs, validação
- **Ambos necessários** para rastreabilidade completa

### Processo recomendado

1. Desenvolver features (changes OpenSpec)
2. Atualizar CHANGELOG.md periodicamente (commits → [Unreleased])
3. Ao preparar release:
   - Atualizar CHANGELOG.md ([Unreleased] → nova versão)
   - Gerar Release Evidence Pack
   - Criar tag Git
   - Atualizar PROJECT_CONTEXT.md se necessário

## Scripts úteis (exemplos)

### 1. Gerar CHANGELOG inicial

```bash
#!/bin/bash
# generate-changelog.sh

cat > CHANGELOG.md << 'EOF'
# Changelog

All notable changes to this project will be documented in this file.

## [Unreleased]
### Added
- 

### Changed
- 

### Fixed
- 

## [1.0.0] - $(date +%Y-%m-%d)
### Initial Release
- Baseline do sistema conforme especificações iniciais
EOF

echo "CHANGELOG.md criado com template inicial"
```

### 2. Extrair commits para [Unreleased]

```bash
#!/bin/bash
# update-unreleased.sh

LAST_TAG=$(git describe --tags --abbrev=0 2>/dev/null || echo "")
if [ -z "$LAST_TAG" ]; then
  COMMITS=$(git log --oneline --no-merges)
else
  COMMITS=$(git log --oneline --no-merges ${LAST_TAG}..HEAD)
fi

echo "## [Unreleased]"
echo "### Added"
echo "$COMMITS" | grep -i "feat:" | sed 's/^[a-f0-9]* //' | sed 's/^feat:/  - /' || true
echo ""
echo "### Changed"
echo "$COMMITS" | grep -E "^(perf:|refactor:|docs:)" | sed 's/^[a-f0-9]* //' | sed 's/^[a-z]*:/  - /' || true
echo ""
echo "### Fixed"
echo "$COMMITS" | grep -i "fix:" | sed 's/^[a-f0-9]* //' | sed 's/^fix:/  - /' || true
```

### 3. Preparar nova versão

```bash
#!/bin/bash
# prepare-release.sh VERSION

VERSION=$1
DATE=$(date +%Y-%m-%d)

# Backup atual
cp CHANGELOG.md CHANGELOG.md.bak

# Criar nova versão
awk -v version="$VERSION" -v date="$DATE" '
/^## \[Unreleased\]/ {
  print "## [" version "] - " date
  next
}
/^## \[/ && !printed {
  print "## [Unreleased]"
  print ""
  print "### Added"
  print "- "
  print ""
  print "### Changed"
  print "- "
  print ""
  print "### Fixed"
  print "- "
  print ""
  printed=1
}
{ print }
' CHANGELOG.md > CHANGELOG.md.new

mv CHANGELOG.md.new CHANGELOG.md
echo "CHANGELOG.md atualizado para versão $VERSION"
```

## Dicas para projetos do setor público

### 1. Detalhamento adequado

- **Evitar** termos técnicos excessivos
- **Incluir** impacto para o usuário final
- **Documentar** mudanças em conformidade/regulatórias
- **Referenciar** documentos oficiais quando aplicável

### 2. Exemplo de entrada

```markdown
### Conformidade
- **LGPD Art. 5º**: Implementação de criptografia para dados pessoais sensíveis
- **Portaria 123/2025**: Adequação aos padrões de acessibilidade digital
- **Auditoria**: Logs completos mantidos por 10 anos conforme exigência legal
```

### 3. Links úteis

- Referenciar ADRs relacionadas (`docs/adr/ADR-XXXX.md`)
- Link para Release Evidence Pack (`docs/releases/YYYY-MM-DD_vX.Y.Z.md`)
- Referência a normativos aplicáveis

## Checklist de qualidade

- [ ] Formato consistente em todas as versões
- [ ] Todas as mudanças significativas documentadas
- [ ] Commits classificados corretamente (Added/Changed/Fixed)
- [ ] Datas de release corretas
- [ ] Links funcionais para documentos relacionados
- [ ] Linguagem clara para não-especialistas técnicos
- [ ] Sem informação sensível (credenciais, IPs internos)
- [ ] Versão atualizada após cada release
- [ ] Seção [Unreleased] vazia/pronta para próximas mudanças

## Integração com ferramentas

### Conventional Commits

- Configurar commitizen para padronização
- Usar commitlint para validação
- Automatizar com hooks de Git

### CI/CD

- Atualização automática do CHANGELOG em pipelines
- Geração de release notes a partir do CHANGELOG
- Validação de formato antes de merge

### OpenSpec (opcional)

- Relacionar changes do OpenSpec com entries no CHANGELOG
- Usar proposal.md como base para descrições mais detalhadas
- Incluir change IDs como referência
