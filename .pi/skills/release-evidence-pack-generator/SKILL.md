---
name: release-evidence-pack-generator
description: Gera Release Evidence Packs para entregas públicas, coletando changes arquivados, specs, ADRs e evidências de validação.
---

# Skill: Release Evidence Pack Generator

Este skill ajuda a criar Release Evidence Packs - documentos completos que registram tudo o que foi entregue em uma release, essencial para repositórios públicos do setor público que precisam de rastreabilidade completa.

## Quando usar

- Preparando uma entrega para cliente do setor público
- Publicando uma release pública do projeto
- Criando documentação para fork por outros departamentos
- Cumprindo requisitos de auditoria/compliance
- Documentando mudanças entre versões

## Método recomendado (script)

Use o script incluído para gerar draft do pack com artefatos detectados:

```bash
python3 generate_release_pack.py --project-root . --version v1.2.0
python3 generate_release_pack.py --project-root . --version v1.2.0 --dry-run
python3 generate_release_pack.py --project-root . --version v1.2.0 --changes change-a,change-b
python3 generate_release_pack.py --project-root . --version v1.2.0 --format json
python3 generate_release_pack.py --project-root . --version v1.2.0 --dry-run --fail-on missing-any
```

Exit codes: `0` ok, `1` erro de execução, `2` policy fail (`--fail-on`).

## O que é um Release Evidence Pack

Documento que contém evidência completa de uma release:

- **Changes incluídos**: Todas as mudanças arquivadas desde última release
- **Specs atualizadas**: Especificações que mudaram
- **ADRs criadas/afetadas**: Decisões arquiteturais
- **Validação**: Resultados de testes, lint, type check
- **Checklist de rollout**: Plano de deploy e rollback
- **Observações**: Notas para quem for fazer fork/maintain

## Localização padrão

```
docs/releases/
├── 2026-03-01_v1.0.0.md    # Release anterior
├── 2026-03-15_v1.1.0.md    # Release atual
└── template.md             # Template para novas releases
```

## Template de Release Evidence Pack

```markdown
# Release Evidence Pack - vX.Y.Z

**Data da release:** YYYY-MM-DD  
**Versão anterior:** vA.B.C  
**Responsável:** [Nome/Departamento]

## Resumo Executivo
[Breve descrição do que esta release entrega, problemas resolvidos, valor gerado]

## Changes Incluídos
| Change ID | Descrição | Tipo (QUICK/FEATURE/HIGH) | Link |
|-----------|-----------|---------------------------|------|
| change-abc123 | [Descrição breve] | FEATURE | [openspec/changes/archive/...](openspec/changes/archive/...) |
| change-def456 | [Descrição breve] | QUICK | [openspec/changes/archive/...](openspec/changes/archive/...) |

## Specs Atualizadas
[Lista de especificações que foram modificadas/adicionadas]

### specs/auth/login.md
- **Adicionado**: Requisito para autenticação via SSO governamental
- **Modificado**: Validação de senha mais rigorosa
- **Link**: [openspec/specs/auth/login.md](openspec/specs/auth/login.md)

### specs/payments/process.md  
- **Adicionado**: Fluxo para pagamentos com PIX
- **Link**: [openspec/specs/payments/process.md](openspec/specs/payments/process.md)

## ADRs Criadas/Afetadas
[Lista de Architecture Decision Records relacionadas]

### ADR-0005: Implementação de Autenticação SSO
- **Status**: Accepted
- **Impacto nesta release**: Nova integração com SSO governo
- **Link**: [docs/adr/ADR-0005-sso-authentication.md](docs/adr/ADR-0005-sso-authentication.md)

### ADR-0006: Migração para PostgreSQL 15
- **Status**: Proposed (para próxima release)
- **Impacto**: Planejamento apenas
- **Link**: [docs/adr/ADR-0006-postgres-migration.md](docs/adr/ADR-0006-postgres-migration.md)

## Validação

### Testes
```

[Output resumido dos testes - sucesso/falha, cobertura]

```

### Lint/Type Check
```

[Output resumido do lint/type check]

```

### Build/Deploy
```

[Output resumido do build/deploy se aplicável]

```

### Segurança
```

[Resultados de scans de segurança se aplicável]

```

## Checklist de Rollout

### Pré-deploy
- [ ] Backup completo do banco de dados
- [ ] Rollback plan documentado e testado
- [ ] Notificação aos usuários (se necessário)
- [ ] Validação em ambiente de staging

### Deploy
- [ ] Monitoramento ativo durante deploy
- [ ] Validação pós-deploy (smoke tests)
- [ ] Verificação de logs/erros

### Pós-deploy (24h)
- [ ] Monitoramento de performance
- [ ] Verificação de erros em produção
- [ ] Validação de funcionalidades críticas

## Rollback Plan

### Cenários para rollback
1. [Cenário 1]: [Condição] → [Ação]
2. [Cenário 2]: [Condição] → [Ação]

### Passos para rollback
1. [Passo 1]
2. [Passo 2]
3. [Passo 3]

**Tempo estimado para rollback:** [X] minutos

## Observações
[Notas importantes para quem for fazer fork/maintain, conhecidos issues, workarounds]

## Próximos Passos
[O que vem na próxima release, dependências, etc.]
```

## Processo de geração

### 1. Identificar changes desde última release

```bash
# Listar changes arquivados desde data específica
find openspec/changes/archive -type d -name "*" | sort | tail -10

# Ou comparar com última tag do Git
git describe --tags --abbrev=0  # última tag
git log --oneline v1.0.0..HEAD  # commits desde última tag
```

### 2. Coletar specs atualizadas

```bash
# Verificar specs modificadas (simplificado)
git diff v1.0.0..HEAD --name-only | grep "openspec/specs" | head -20
```

### 3. Identificar ADRs relacionadas

```bash
# ADRs criadas/modificadas
find docs/adr -name "*.md" -type f -newer "docs/releases/ultima-release.md" 2>/dev/null
```

### 4. Coletar evidência de validação

```bash
# Rodar testes e capturar output
pytest --cov=. --cov-report=term-missing 2>&1 | tail -30

# Rodar lint
ruff check . 2>&1 | tail -20

# Type check (se aplicável)
mypy . 2>&1 | tail -20
```

### 5. Gerar checklist de rollout

Baseado em:

- Complexidade das mudanças
- Dependências externas
- Horário de deploy
- Impacto nos usuários

## Exemplo para projeto Django

```markdown
# Release Evidence Pack - v1.2.0

**Data da release:** 2026-03-15  
**Versão anterior:** v1.1.0  
**Responsável:** Secretaria de Tecnologia - Departamento de Desenvolvimento

## Resumo Executivo
Esta release implementa autenticação via SSO do governo estadual, melhora a performance de consultas de processos e corrige bugs críticos de segurança. Permite integração futura com outros sistemas governamentais.

## Changes Incluídos
| Change ID | Descrição | Tipo | Link |
|-----------|-----------|------|------|
| change-sso-auth | Implementação SSO governo | HIGH | [archive/2026-03-10-sso-auth](openspec/changes/archive/2026-03-10-sso-auth) |
| change-perf-query | Otimização consultas processos | FEATURE | [archive/2026-03-12-perf-query](openspec/changes/archive/2026-03-12-perf-query) |
| change-fix-xss | Correção vulnerabilidade XSS | HIGH | [archive/2026-03-14-fix-xss](openspec/changes/archive/2026-03-14-fix-xss) |

## Specs Atualizadas

### specs/auth/authentication.md
- **Adicionado**: Requisitos para integração SSO governo
- **Modificado**: Fluxo de autenticação completo
- **Link**: [openspec/specs/auth/authentication.md](openspec/specs/auth/authentication.md)

### specs/performance/queries.md
- **Adicionado**: Requisitos de performance para consultas
- **Link**: [openspec/specs/performance/queries.md](openspec/specs/performance/queries.md)

## ADRs Criadas/Afetadas

### ADR-0004: Implementação de SSO Governamental
- **Status**: Accepted
- **Impacto**: Nova dependência externa (API SSO)
- **Link**: [docs/adr/ADR-0004-sso-governamental.md](docs/adr/ADR-0004-sso-governamental.md)

### ADR-0005: Estratégia de Indexação PostgreSQL
- **Status**: Accepted  
- **Impacto**: Novos índices no banco
- **Link**: [docs/adr/ADR-0005-indexing-strategy.md](docs/adr/ADR-0005-indexing-strategy.md)

## Validação

### Testes
```

============================= test session starts ==============================
collected 245 tests

test_auth_sso.py ...................... [ 85%]
test_performance_queries.py ........... [ 92%]
test_security_xss.py .................. [100%]

245 passed, 0 failed
Coverage: 87% (aumento de 2% desde v1.1.0)

```

### Lint/Type Check
```

ruff check .: 0 errors, 0 warnings ✓
mypy .: 0 errors, 3 notes (não críticos) ✓

```

### Build/Deploy
```

python3 manage.py check: System check identified no issues ✓
docker build: Successfully built imagem:v1.2.0 ✓

```

### Segurança
```

safety check: 0 vulnerabilities found ✓
bandit -r .: 0 issues found ✓

```

## Checklist de Rollout

### Pré-deploy (15/03 - Manhã)
- [x] Backup banco de dados (15/03 08:00)
- [x] Rollback plan documentado
- [x] Notificação aos 50 usuários ativos
- [x] Validação em staging (14/03)

### Deploy (15/03 - 18:00)
- [ ] Monitoramento ativo durante deploy
- [ ] Smoke tests pós-deploy
- [ ] Verificação logs/erros

### Pós-deploy (16/03 - 18:00)
- [ ] Monitoramento performance 24h
- [ ] Verificação erros produção
- [ ] Validação funcionalidades críticas

## Rollback Plan

### Cenários para rollback
1. **SSO não funciona**: Usuários não conseguem logar → Rollback para autenticação local
2. **Performance piora**: Consultas mais lentas → Rollback para índices anteriores
3. **Erros críticos**: Sistema instável → Rollback completo

### Passos para rollback
1. Restaurar backup do banco (10 minutos)
2. Redeploy da versão v1.1.0 (5 minutos)
3. Reconfigurar autenticação local (5 minutos)
4. Notificar usuários (imediato)

**Tempo estimado:** 20 minutos

## Observações
- A integração SSO requer whitelist do IP do servidor no sistema do governo
- Os novos índices aumentaram ligeiramente o tamanho do banco (15%)
- Há um workaround conhecido para IE11 (2% dos usuários)

## Próximos Passos
- v1.3.0: Integração com sistema SEI (estimativa: 30 dias)
- v1.4.0: Relatórios analíticos avançados (estimativa: 45 dias)
```

## Integração com workflow ESAA

### Para releases públicas

1. **Obrigatório**: Release Evidence Pack para cada release pública
2. **Armazenamento**: Em `docs/releases/` com data e versão no nome
3. **Referência**: Linkar no CHANGELOG.md e README.md

### Para projetos do setor público

1. **Transparência**: Pack completo disponível publicamente
2. **Auditoria**: Todas as decisões e validações documentadas
3. **Fork-friendly**: Outros departamentos entendem exatamente o que foi entregue

## Dicas para qualidade

### Boas práticas

1. **Objetividade**: Fatos, não opiniões
2. **Rastreabilidade**: Links para todos os artefatos
3. **Clareza**: Linguagem acessível para não-técnicos
4. **Completude**: Nada importante faltando

### Evitar

1. Informação sensível (credenciais, IPs internos)
2. Jargão técnico excessivo
3. Opiniões subjetivas sem evidência
4. Promessas não comprovadas

## Checklist de qualidade

- [ ] Nome do arquivo no formato `YYYY-MM-DD_vX.Y.Z.md`
- [ ] Todos os changes arquivados listados e linkados
- [ ] Specs atualizadas documentadas
- [ ] ADRs relacionadas identificadas
- [ ] Evidência de validação incluída (testes, lint, etc.)
- [ ] Checklist de rollout completo e realista
- [ ] Plano de rollback específico e testável
- [ ] Observações úteis para futuros maintainers
- [ ] Próximos passos definidos
- [ ] Sem informação sensível exposta
