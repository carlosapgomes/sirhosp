---
name: suggest-adr
description: Detecta quando uma ADR é recomendada e orienta criação com template.
---

# Skill: suggest-adr

**Propósito:** Detectar quando um Architecture Decision Record (ADR) é necessário e sugerir sua criação com template pré-preenchido.

**Quando usar:**

- Após classificar um change como HIGH/ARCH
- Quando detecta mudança em arquivos críticos (models core, auth, settings)
- Ao finalizar design.md de change arquitetural
- Quando o usuário esquece de criar ADR para decisão importante

**Comando:**

```bash
/suggest-adr [change-id] [--auto-create]
```

Opções:

- `change-id`: ID do change a analisar (se omitido, usa change ativo mais recente)
- `--auto-create`: Cria o arquivo ADR automaticamente (sem pedir confirmação)

## Método recomendado (script)

Use o script incluído para recomendação determinística:

```bash
python3 suggest_adr.py --project-root .
python3 suggest_adr.py --project-root . meu-change-id --format json
python3 suggest_adr.py --project-root . meu-change-id --auto-create
python3 suggest_adr.py --project-root . --fail-on recommendation
```

Exit codes: `0` ok, `1` erro de execução, `2` policy fail (`--fail-on`).

---

## O que a Skill Faz

1. **Analisa o change** — Lê proposal.md e design.md
2. **Avalia necessidade** — Verifica se atende critérios para ADR
3. **Sugere ou cria** — Gera template pré-preenchido
4. **Nomeia adequadamente** — Segue convenção ADR-XXXX-nome-curto.md

---

## Critérios para Criar ADR

Segundo o SOP ESAA v4.1, criar ADR quando:

| Critério | Indicadores no Change |
|----------|----------------------|
| **Mudança arquitetural** | Refatoração estrutural, novo padrão, mudança de camadas |
| **Dependência relevante** | Nova biblioteca core, troca de framework, upgrade major |
| **Modelo de dados significativo** | Migração de banco, novo modelo core, alteração de constraints |
| **Contrato externo** | Nova API, webhook, integração, mudança de provider |
| **Política de segurança** | Auth, autorização, criptografia, validação |
| **Change HIGH/ARCH** | Score 4+ na classificação de risco |

---

## Exemplos de Saída

### Exemplo 1: Detecta Necessidade (Change HIGH)

```
$ /suggest-adr migrate-to-postgres

🔍 Analisando change: migrate-to-postgres

📄 Arquivos analisados:
   ✓ proposal.md (encontrado)
   ✓ design.md (encontrado)
   ⚠️  specs/ (não encontrado)

📊 Análise de Risco:
   • Classificação: HIGH/ARCH (score: 5)
   • Critérios atendidos:
     ✓ Mudança de modelo de dados
     ✓ Migração de banco (SQLite → PostgreSQL)
     ✓ Alto custo de rollback
     ✓ Impacto em todos os ambientes
     ✓ Performance crítica

⚠️  RECOMENDAÇÃO FORTE: Criar ADR

Esta é uma decisão arquitetural significativa que afeta:
• Estrutura de deploy
• Configuração de desenvolvimento
• Backup e disaster recovery
• Custo de infraestrutura

📝 Template Gerado:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ADR-0004: Migration from SQLite to PostgreSQL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Status
Proposed

## Context
O sistema atualmente utiliza SQLite em todos os ambientes 
(desenvolvimento, staging e produção). Com o crescimento da base 
de usuários e necessidade de concorrência, identificamos limitações:

• SQLite não suporta múltiplas conexões simultâneas eficientemente
• Dificuldade em fazer backup online
• Limitações de tipos de dados para features futuras
• Impossibilidade de usar replicas para leitura

## Decision
Migrar para PostgreSQL 15 como banco de dados principal.

Estratégia de migração:
1. Configurar PostgreSQL em paralelo
2. Criar scripts de migração de dados
3. Testar em staging por 1 semana
4. Backup completo antes do deploy
5. Deploy com janela de manutenção
6. Monitoramento intensivo por 48h

## Alternatives Considered

1. **Manter SQLite + otimizações**
   - Prós: Nenhuma mudança necessária
   - Contras: Não resolve problemas de concorrência
   - Decisão: Rejeitado - limitação arquitetural fundamental

2. **MySQL/MariaDB**
   - Prós: Amplamente suportado, bom desempenho
   - Contras: Menos tipos de dados avançados, licenciamento
   - Decisão: Rejeitado - PostgreSQL melhor ecossistema Django

3. **PostgreSQL (escolhido)**
   - Prós: Ótimo suporte Django, features avançadas, open source
   - Contras: Custo de migração, necessita DBA para tuning
   - Decisão: Aceito - melhor longo prazo

## Consequences

**Positivas:**
• Suporte a múltiplas conexões simultâneas
• Backup online (pg_dump)
• Tipos de dados avançados (JSONB, arrays)
• Possibilidade de replicas futuras
• Melhor performance para queries complexas

**Negativas / Trade-offs:**
• Custo de infraestrutura adicional
• Complexidade de setup para novos devs
• Necessidade de manutenção (vacuum, tuning)
• Migração de dados arriscada

**Riscos:**
• Data loss durante migração
   Mitigação: Backup completo, testes em staging, rollback script
• Downtime prolongado
   Mitigação: Janela de manutenção, comunicação prévia

## Notes
• ADR criado a partir do change: migrate-to-postgres
• Data da decisão: 2026-03-02
• Decisores: [nome do solopreneur]

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💾 Ações Disponíveis:

1. Criar ADR automaticamente:
   /suggest-adr migrate-to-postgres --auto-create

2. Criar manualmente (copiar template acima):
   docs/adr/ADR-0004-migration-from-sqlite-to-postgresql.md

3. Adiar (não recomendado):
   Lembrete será mostrado novamente ao arquivar change.

⚠️  NOTA: Este ADR deve ser criado ANTES de /opsx:archive
```

### Exemplo 2: Não Detecta Necessidade (Change QUICK)

```
$ /suggest-adr fix-typo-navbar

🔍 Analisando change: fix-typo-navbar

📄 Arquivos analisados:
   ✓ proposal.md (encontrado)

📊 Análise de Risco:
   • Classificação: QUICK (score: 0)
   • Critérios de ADR: Nenhum atendido

✅ Veredito: ADR NÃO necessário

Justificativa:
• Change de baixo risco (correção de typo)
• Não afeta arquitetura
• Não introduz dependências
• Sem impacto em dados ou contratos

💡 Recomendação:
Prossiga com workflow QUICK normal.
Não é necessário documentar esta decisão.

/esaa-classify-risk confirmou: Este é um change QUICK.
Use: /opsx:apply fix-typo-navbar
```

### Exemplo 3: Sugestão para Novo Padrão

```
$ /suggest-adr adopt-celery-tasks

🔍 Analisando change: adopt-celery-tasks

📄 Arquivos analisados:
   ✓ proposal.md
   ✓ design.md

📊 Análise de Risco:
   • Classificação: FEATURE (score: 3)
   • Critérios especiais detectados:
     ✓ Nova dependência core (Celery)
     ✓ Mudança de padrão arquitetural (async tasks)
     ✓ Impacto em deploy (Redis necessário)

⚠️  RECOMENDAÇÃO: Considerar ADR

Apesar de ser FEATURE (score 3), esta mudança introduz:
• Nova infraestrutura (Redis)
• Novo padrão de desenvolvimento (tasks assíncronas)
• Complexidade operacional adicional

📝 Sugestão: Criar ADR opcional

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
ADR-0005: Adoption of Celery for Asynchronous Task Processing
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

## Status
Proposed

## Context
Atualmente processamentos longos (emails, relatórios) 
executam síncronos na request, causando timeouts.

## Decision
Adotar Celery com Redis para processamento assíncrono.

Padrão de uso:
• Use Celery para operações >5 segundos
• Monitore filas via Flower
• Retry automático para falhas transientes

## Alternatives Considered

1. **Django Channels**
   - Contras: Overkill para tasks simples
   
2. **RQ (Redis Queue)**
   - Contras: Menos maduro, menos features
   
3. **Celery (escolhido)**
   - Prós: Padrão Django, maduro, boa documentação

## Consequences

**Positivas:**
• UX melhorada (requests rápidas)
• Escalabilidade de workers
• Retry automático

**Negativas:**
• Infraestrutura adicional (Redis)
• Complexidade de debug
• Necessidade de monitoramento

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 Este ADR é OPCIONAL (change é FEATURE, não HIGH).

Recomendação: Criar se:
• Este padrão será usado em múltiplos lugares
• Equipe pode crescer (outros devs precisam entender)
• Há risco de esquecer o padrão em 6 meses

Criar agora? [S/n]
```

### Exemplo 4: Auto-create

```
$ /suggest-adr auth-jwt-implementation --auto-create

🔍 Analisando change: auth-jwt-implementation
📊 Classificação: HIGH/ARCH (score: 6)
⚠️  ADR necessário detectado

📝 Gerando ADR-0006: Authentication with JWT Tokens
💾 Salvando em: docs/adr/ADR-0006-authentication-with-jwt-tokens.md

✅ ADR criado com sucesso!

📄 Próximos passos:
   1. Edite o ADR para adicionar detalhes específicos
   2. Atualize "Decisores" com seu nome
   3. Mude Status para "Accepted" quando confirmar
   4. Commit o ADR: git add docs/adr/ && git commit

🎯 Continue o workflow:
   /opsx:apply auth-jwt-implementation
   (implementar seguindo a decisão documentada)
```

---

## Estrutura do ADR Gerado

Segue template padrão do SOP ESAA v4.1:

```markdown
# ADR-XXXX: [Título Descritivo]

## Status
Proposed | Accepted | Deprecated | Superseded by ADR-YYYY

## Context
[Problema/situação que motivou a decisão]
[Contexto de negócio e técnico]

## Decision
[O que foi decidido fazer]
[Detalhes da implementação]

## Alternatives Considered
1. [Opção A]: [descrição] - [por que rejeitada]
2. [Opção B]: [descrição] - [por que rejeitada]
3. [Opção escolhida]: [por que aceita]

## Consequences

**Positivas:**
- [Benefício 1]
- [Benefício 2]

**Negativas / Trade-offs:**
- [Custo/limitação 1]
- [Custo/limitação 2]

**Riscos:**
- [Risco]: [mitigação]

## Notes
- ADR criado a partir do change: [change-id]
- Data: [data]
- Decisores: [nomes]
```

---

## Implementação

### Dependências

```python
# requirements.txt
pyyaml>=6.0
```

### Estrutura

```
suggest-adr/
├── SKILL.md              # Este arquivo
├── suggest.py            # Script principal
├── templates/
│   ├── database.md       # Template migração de banco
│   ├── auth.md           # Template autenticação
│   ├── api.md            # Template APIs
│   ├── dependencies.md   # Template dependências
│   └── generic.md        # Template genérico
└── utils.py              # Funções auxiliares
```

### Lógica Principal (suggest.py)

```python
#!/usr/bin/env python3
"""
Sugestor de ADR para SOP ESAA Solopreneur v4.1
"""

import os
import sys
import re
import argparse
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Critérios que exigem ADR obrigatório
MANDATORY_CRITERIA = {
    "architecture": {
        "keywords": ["refactor", "rewrite", "restructure", "migrate", "migration"],
        "score_threshold": 4,  # Se HIGH/ARCH
        "template": "architecture"
    },
    "database": {
        "keywords": ["database", "db", "postgres", "mysql", "sqlite", "mongo", "redis", 
                     "migration", "schema", "table", "column", "index"],
        "files": ["models.py"],
        "template": "database"
    },
    "auth": {
        "keywords": ["auth", "login", "password", "jwt", "oauth", "session", 
                     "permission", "security", "encrypt", "token"],
        "template": "auth"
    },
    "api": {
        "keywords": ["api", "endpoint", "webhook", "integration", "rest", "graphql",
                     "endpoint", "contract", "payload", "response"],
        "template": "api"
    },
    "dependencies": {
        "keywords": ["library", "package", "dependency", "upgrade", "version",
                     "framework", "django", "flask", "react", "vue"],
        "template": "dependencies"
    }
}

# Palavras que indicam mudança significativa
SIGNIFICANT_CHANGE_INDICATORS = [
    "migrar", "migration", "migrate",
    "trocar", "replace", "switch",
    "adotar", "adopt", "implementar", "implement",
    "remover", "remove", "delete",
    "atualizar", "upgrade", "update major",
    "novo padrão", "new pattern",
    "arquitetura", "architecture"
]


class ADRSuggester:
    """Analisa changes e sugere/cria ADRs"""
    
    def __init__(self, project_root: str = "."):
        self.root = Path(project_root).resolve()
        self.adr_dir = self.root / "docs" / "adr"
        self.changes_dir = self.root / "openspec" / "changes" / "active"
        self.next_adr_number = self._get_next_adr_number()
        
    def _get_next_adr_number(self) -> int:
        """Determina próximo número de ADR disponível"""
        if not self.adr_dir.exists():
            return 1
            
        numbers = []
        for adr_file in self.adr_dir.glob("ADR-*.md"):
            match = re.match(r'ADR-(\d+)', adr_file.name)
            if match:
                numbers.append(int(match.group(1)))
                
        return max(numbers, default=0) + 1
    
    def analyze_change(self, change_id: str) -> Dict:
        """Analisa um change e retorna avaliação"""
        change_path = self.changes_dir / change_id
        
        if not change_path.exists():
            return {"error": f"Change '{change_id}' não encontrado"}
        
        # Lê arquivos do change
        proposal = self._read_file(change_path / "proposal.md")
        design = self._read_file(change_path / "design.md")
        
        # Detecta critérios
        content = (proposal or "") + " " + (design or "")
        content_lower = content.lower()
        
        detected_criteria = []
        for criterion, config in MANDATORY_CRITERIA.items():
            if self._matches_criterion(content_lower, config):
                detected_criteria.append(criterion)
        
        # Detecta significância
        significance_score = self._calculate_significance(content_lower)
        
        # Verifica classificação de risco (se existir)
        risk_level = self._extract_risk_level(proposal or "")
        
        # Determina necessidade
        needs_adr, adr_urgency = self._determine_adr_need(
            detected_criteria, significance_score, risk_level
        )
        
        return {
            "change_id": change_id,
            "proposal_exists": proposal is not None,
            "design_exists": design is not None,
            "risk_level": risk_level,
            "detected_criteria": detected_criteria,
            "significance_score": significance_score,
            "needs_adr": needs_adr,
            "adr_urgency": adr_urgency,  # "mandatory", "recommended", "optional"
            "suggested_template": self._select_template(detected_criteria),
            "title_suggestion": self._suggest_title(change_id, content),
            "next_adr_number": self.next_adr_number
        }
    
    def _read_file(self, path: Path) -> Optional[str]:
        """Lê conteúdo de arquivo se existir"""
        if path.exists():
            return path.read_text()
        return None
    
    def _matches_criterion(self, content: str, config: Dict) -> bool:
        """Verifica se conteúdo corresponde a critério"""
        # Verifica keywords
        keywords = config.get("keywords", [])
        if any(kw in content for kw in keywords):
            return True
            
        # Verifica arquivos modificados (se houver info)
        # TODO: Implementar verificação de arquivos
        
        return False
    
    def _calculate_significance(self, content: str) -> int:
        """Calcula score de significância da mudança"""
        score = 0
        for indicator in SIGNIFICANT_CHANGE_INDICATORS:
            if indicator in content:
                score += 1
        return score
    
    def _extract_risk_level(self, proposal: str) -> Optional[str]:
        """Extrai classificação de risco do proposal"""
        if "HIGH/ARCH" in proposal or "Classe: HIGH" in proposal:
            return "HIGH"
        elif "FEATURE" in proposal or "Classe: FEATURE" in proposal:
            return "FEATURE"
        elif "QUICK" in proposal or "Classe: QUICK" in proposal:
            return "QUICK"
        return None
    
    def _determine_adr_need(self, criteria: List[str], significance: int, 
                           risk_level: Optional[str]) -> Tuple[bool, str]:
        """Determina se ADR é necessário e urgência"""
        # HIGH/ARCH sempre requer ADR
        if risk_level == "HIGH":
            return True, "mandatory"
            
        # FEATURE com critérios arquiteturais
        if risk_level == "FEATURE" and len(criteria) >= 2:
            return True, "recommended"
            
        # FEATURE com um critério forte
        if risk_level == "FEATURE" and any(c in ["database", "auth", "architecture"] for c in criteria):
            return True, "recommended"
            
        # FEATURE com alta significância
        if risk_level == "FEATURE" and significance >= 3:
            return True, "optional"
            
        # QUICK não precisa
        if risk_level == "QUICK":
            return False, "none"
            
        # Caso ambíguo: sugere se tem critérios
        if criteria:
            return True, "optional"
            
        return False, "none"
    
    def _select_template(self, criteria: List[str]) -> str:
        """Seleciona template mais apropriado"""
        priority = ["database", "auth", "architecture", "api", "dependencies"]
        for criterion in priority:
            if criterion in criteria:
                return criterion
        return "generic"
    
    def _suggest_title(self, change_id: str, content: str) -> str:
        """Sugere título para ADR baseado no change"""
        # Limpa change_id
        title = change_id.replace("-", " ").replace("_", " ").title()
        
        # Tenta extrair do conteúdo
        if "migrate" in content.lower() or "migration" in content.lower():
            if "postgres" in content.lower():
                return "Migration to PostgreSQL"
            if "mysql" in content.lower():
                return "Migration to MySQL"
                
        if "auth" in content.lower() or "jwt" in content.lower():
            return "Authentication Strategy"
            
        if "api" in content.lower() or "rest" in content.lower():
            return "API Architecture"
            
        return title
    
    def generate_adr(self, analysis: Dict, custom_content: Optional[str] = None) -> str:
        """Gera conteúdo do ADR"""
        template_name = analysis["suggested_template"]
        
        # Templates específicos
        templates = {
            "database": self._database_template,
            "auth": self._auth_template,
            "api": self._api_template,
            "architecture": self._architecture_template,
            "dependencies": self._dependencies_template,
            "generic": self._generic_template
        }
        
        template_func = templates.get(template_name, self._generic_template)
        return template_func(analysis)
    
    def _database_template(self, analysis: Dict) -> str:
        """Template para mudanças de banco de dados"""
        return f"""# ADR-{analysis['next_adr_number']:04d}: {analysis['title_suggestion']}

## Status
Proposed

## Context
[Descreva o problema atual com o banco de dados atual]
[Explique por que a mudança é necessária]
[Impacto no sistema existente]

## Decision
[Qual banco/estrutura foi escolhida]
[Estratégia de migração]
[Plano de rollback]

## Alternatives Considered

1. **[Opção A]**
   - Prós: 
   - Contras:
   - Decisão: [Aceito/Rejeitado]

2. **[Opção B]**
   - Prós:
   - Contras:
   - Decisão: [Aceito/Rejeitado]

3. **[Opção escolhida]**
   - Prós:
   - Contras:
   - Decisão: Aceito

## Consequences

**Positivas:**
- [Benefício 1]
- [Benefício 2]

**Negativas / Trade-offs:**
- [Custo 1]
- [Custo 2]

**Riscos:**
- [Risco]: [Mitigação]

## Migration Plan
1. [Passo 1]
2. [Passo 2]
3. [Passo 3]

## Rollback Plan
[Como reverter se necessário]

## Notes
- ADR criado a partir do change: {analysis['change_id']}
- Data: {datetime.now().strftime('%Y-%m-%d')}
- Decisores: [Seu nome]
- Related Changes: [{analysis['change_id']}]
"""
    
    def _auth_template(self, analysis: Dict) -> str:
        """Template para autenticação"""
        return f"""# ADR-{analysis['next_adr_number']:04d}: {analysis['title_suggestion']}

## Status
Proposed

## Context
[Descrição do cenário de autenticação atual]
[Requisitos de segurança]
[Escopo (usuários internos, clientes, API)]

## Decision
[Qual estratégia de auth foi escolhida]
[Fluxo de autenticação]
[Gerenciamento de sessões/tokens]

## Alternatives Considered

1. **Session-based Authentication**
   - Prós: Simples, nativo Django
   - Contras: Não escala bem para APIs
   - Decisão: [Aceito/Rejeitado]

2. **JWT (JSON Web Tokens)**
   - Prós: Stateless, bom para APIs
   - Contras: Complexidade de revoke
   - Decisão: [Aceito/Rejeitado]

3. **OAuth 2.0 / OpenID Connect**
   - Prós: Integração com Google/GitHub
   - Contras: Dependência externa
   - Decisão: [Aceito/Rejeitado]

## Consequences

**Positivas:**
- [Benefício de segurança]
- [Benefício de UX]

**Negativas / Trade-offs:**
- [Complexidade adicional]
- [Custo/manutenção]

**Riscos:**
- Token/Senha vazados: [Mitigação - HTTPS, expire curto]
- Lockout de usuários: [Mitigação - recuperação de senha]

## Security Considerations
- [Lista de preocupações de segurança]
- [Como serão tratadas]

## Notes
- ADR criado a partir do change: {analysis['change_id']}
- Data: {datetime.now().strftime('%Y-%m-%d')}
- Decisores: [Seu nome]
- Security Review: [Sim/Não - quando aplicável]
"""
    
    def _api_template(self, analysis: Dict) -> str:
        """Template para APIs"""
        return f"""# ADR-{analysis['next_adr_number']:04d}: {analysis['title_suggestion']}

## Status
Proposed

## Context
[Necessidade da API]
[Consumidores (web, mobile, terceiros)]
[Requisitos não-funcionais (performance, cache)]

## Decision
[Estilo arquitetural: REST/GraphQL/gRPC]
[Formato de serialização]
[Estratégia de versionamento]
[Autenticação da API]

## Alternatives Considered

1. **REST**
   - Prós: Simples, amplo suporte
   - Contras: Over/under-fetching
   - Decisão: [Aceito/Rejeitado]

2. **GraphQL**
   - Prós: Flexibilidade para clientes
   - Contras: Complexidade, caching difícil
   - Decisão: [Aceito/Rejeitado]

## Consequences

**Positivas:**
- [Benefício 1]
- [Benefício 2]

**Negativas / Trade-offs:**
- [Limitação 1]
- [Limitação 2]

**Breaking Changes:**
- [O que quebra para clientes existentes]
- [Plano de migração de clientes]

## API Contract
[Link para especificação OpenAPI/GraphQL schema]

## Notes
- ADR criado a partir do change: {analysis['change_id']}
- Data: {datetime.now().strftime('%Y-%m-%d')}
- Decisores: [Seu nome]
- Consumers Notified: [Sim/Não]
"""
    
    def _architecture_template(self, analysis: Dict) -> str:
        """Template para mudanças arquiteturais"""
        return f"""# ADR-{analysis['next_adr_number']:04d}: {analysis['title_suggestion']}

## Status
Proposed

## Context
[Problema com arquitetura atual]
[Limitações que motivam mudança]
[Contexto de crescimento/escala]

## Decision
[Nova arquitetura proposta]
[Diagrama/descricao da estrutura]
[Direção de dependências]

## Alternatives Considered

1. **[Arquitetura A]**
   - Prós:
   - Contras:
   - Decisão: [Aceito/Rejeitado]

2. **[Arquitetura B]**
   - Prós:
   - Contras:
   - Decisão: [Aceito/Rejeitado]

## Consequences

**Positivas:**
- [Benefício arquitetural]
- [Facilidade de manutenção]

**Negativas / Trade-offs:**
- [Custo de migração]
- [Complexidade adicional]

**Impact Areas:**
- [Lista de áreas afetadas]
- [O que precisa ser refatorado]

## Migration Strategy
[Faseamento da mudança]
[Como migrar gradualmente]

## Notes
- ADR criado a partir do change: {analysis['change_id']}
- Data: {datetime.now().strftime('%Y-%m-%d')}
- Decisores: [Seu nome]
- Reviewers: [Se houver]
"""
    
    def _dependencies_template(self, analysis: Dict) -> str:
        """Template para dependências"""
        return f"""# ADR-{analysis['next_adr_number']:04d}: {analysis['title_suggestion']}

## Status
Proposed

## Context
[Problema com dependência atual]
[Necessidade de nova biblioteca]
[Constraints (licença, tamanho, manutenção)]

## Decision
[Qual biblioteca foi escolhida]
[Versão específica]
[Onde/how será usada]

## Alternatives Considered

1. **[Biblioteca A]**
   - Prós:
   - Contras:
   - Licença:
   - Decisão: [Aceito/Rejeitado]

2. **[Biblioteca B]**
   - Prós:
   - Contras:
   - Licença:
   - Decisão: [Aceito/Rejeitado]

3. **Não fazer nada (status quo)**
   - Decisão: [Aceito/Rejeitado]

## Consequences

**Positivas:**
- [Benefício da lib]

**Negativas / Trade-offs:**
- [Tamanho do bundle]
- [Complexidade]
- [Vendor lock-in]

**Riscos:**
- Lib abandonada: [Mitigação - escolha madura, fork possível]
- Breaking changes: [Mitigação - pinning de versão]
- Vulnerabilidades: [Mitigação - dependabot, auditorias]

## License Check
- [ ] Licença compatível com projeto
- [ ] Atribuição necessária
- [ ] Restrições comerciais verificadas

## Notes
- ADR criado a partir do change: {analysis['change_id']}
- Data: {datetime.now().strftime('%Y-%m-%d')}
- Decisores: [Seu nome]
"""
    
    def _generic_template(self, analysis: Dict) -> str:
        """Template genérico"""
        return f"""# ADR-{analysis['next_adr_number']:04d}: {analysis['title_suggestion']}

## Status
Proposed

## Context
[Descreva a situação e problema]
[Por que esta decisão é necessária]

## Decision
[O que foi decidido]
[Detalhes da implementação]

## Alternatives Considered

1. **[Opção A]**
   - Prós:
   - Contras:
   - Decisão: [Aceito/Rejeitado]

2. **[Opção B]**
   - Prós:
   - Contras:
   - Decisão: [Aceito/Rejeitado]

## Consequences

**Positivas:**
- [Benefício 1]
- [Benefício 2]

**Negativas / Trade-offs:**
- [Trade-off 1]
- [Trade-off 2]

**Riscos:**
- [Risco]: [Mitigação]

## Notes
- ADR criado a partir do change: {analysis['change_id']}
- Data: {datetime.now().strftime('%Y-%m-%d')}
- Decisores: [Seu nome]
"""
    
    def create_adr_file(self, analysis: Dict, content: str) -> Path:
        """Cria arquivo ADR no disco"""
        # Cria diretório se não existir
        self.adr_dir.mkdir(parents=True, exist_ok=True)
        
        # Nome do arquivo
        title_slug = analysis['title_suggestion'].lower().replace(" ", "-")[:50]
        filename = f"ADR-{analysis['next_adr_number']:04d}-{title_slug}.md"
        filepath = self.adr_dir / filename
        
        # Salva arquivo
        filepath.write_text(content)
        
        return filepath


def print_analysis(analysis: Dict):
    """Imprime relatório de análise"""
    print("\n" + "━"*60)
    print("🔍 ANÁLISE DE NECESSIDADE DE ADR")
    print("━"*60 + "\n")
    
    print(f"Change: {analysis['change_id']}")
    print(f"Arquivos analisados:")
    print(f"  ✓ proposal.md: {'Sim' if analysis['proposal_exists'] else 'Não'}")
    print(f"  ✓ design.md: {'Sim' if analysis['design_exists'] else 'Não'}")
    
    if analysis['risk_level']:
        print(f"\n📊 Classificação de Risco: {analysis['risk_level']}")
    
    if analysis['detected_criteria']:
        print(f"\n🎯 Critérios Detectados:")
        for criterion in analysis['detected_criteria']:
            print(f"  • {criterion}")
    
    print(f"\n📈 Score de Significância: {analysis['significance_score']}")
    
    print(f"\n📋 Veredito:")
    if analysis['needs_adr']:
        urgency_emoji = {"mandatory": "🔴", "recommended": "🟡", "optional": "🟢"}
        urgency_text = {
            "mandatory": "OBRIGATÓRIO (HIGH/ARCH)",
            "recommended": "RECOMENDADO (FEATURE com critérios)",
            "optional": "OPCIONAL (considere criar)"
        }
        
        emoji = urgency_emoji.get(analysis['adr_urgency'], "⚪")
        text = urgency_text.get(analysis['adr_urgency'], "Analisar")
        
        print(f"   {emoji} ADR {text}")
    else:
        print(f"   ✅ ADR NÃO necessário")
        print(f"   Este change não atinge critérios para documentação arquitetural.")


def print_adr_content(content: str):
    """Imprime template de ADR formatado"""
    print("\n" + "━"*60)
    print("📝 TEMPLATE DE ADR SUGERIDO")
    print("━"*60 + "\n")
    print(content)
    print("━"*60)


def main():
    """Função principal da skill"""
    parser = argparse.ArgumentParser(description="Sugere criação de ADR para SOP ESAA")
    parser.add_argument("change_id", nargs="?", help="ID do change (opcional)")
    parser.add_argument("--auto-create", action="store_true", 
                       help="Cria ADR automaticamente sem confirmação")
    parser.add_argument("--output", "-o", help="Nome do arquivo de saída (com --auto-create)")
    args = parser.parse_args()
    
    suggester = ADRSuggester()
    
    # Determina change_id
    if args.change_id:
        change_id = args.change_id
    else:
        # Pega change mais recente
        if suggester.changes_dir.exists():
            changes = sorted(suggester.changes_dir.iterdir(), 
                           key=lambda p: p.stat().st_mtime, 
                           reverse=True)
            if changes:
                change_id = changes[0].name
                print(f"📝 Usando change mais recente: {change_id}")
            else:
                print("❌ Nenhum change ativo encontrado")
                return 1
        else:
            print("❌ Diretório openspec/changes/active/ não encontrado")
            return 1
    
    # Analisa
    analysis = suggester.analyze_change(change_id)
    
    if "error" in analysis:
        print(f"❌ Erro: {analysis['error']}")
        return 1
    
    # Imprime análise
    print_analysis(analysis)
    
    # Se não precisa de ADR, termina
    if not analysis['needs_adr']:
        print("\n💡 Continue com o workflow normal.")
        print(f"   /opsx:apply {change_id}")
        return 0
    
    # Gera template
    adr_content = suggester.generate_adr(analysis)
    
    # Se auto-create, salva arquivo
    if args.auto_create:
        filepath = suggester.create_adr_file(analysis, adr_content)
        print(f"\n✅ ADR criado automaticamente!")
        print(f"📄 Arquivo: {filepath}")
        print(f"\n⚠️  Lembre-se de:")
        print(f"   1. Editar o arquivo para adicionar detalhes")
        print(f"   2. Atualizar 'Decisores' com seu nome")
        print(f"   3. Mudar Status para 'Accepted' quando confirmar")
        print(f"   4. Commit: git add {filepath.relative_to(Path.cwd())}")
    else:
        # Imprime template para cópia manual
        print_adr_content(adr_content)
        
        print("\n💾 Ações Disponíveis:")
        print(f"\n1. Criar ADR automaticamente:")
        print(f"   /suggest-adr {change_id} --auto-create")
        print(f"\n2. Criar manualmente:")
        
        title_slug = analysis['title_suggestion'].lower().replace(" ", "-")[:50]
        filename = f"ADR-{analysis['next_adr_number']:04d}-{title_slug}.md"
        print(f"   Copie o template acima para: docs/adr/{filename}")
        
        if analysis['adr_urgency'] == 'mandatory':
            print(f"\n⚠️  NOTA: Este ADR é OBRIGATÓRIO antes de /opsx:archive")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

---

## Integração com Workflow ESAA

### Ponto 1: Após Classificação de Risco

```
/esaa-classify-risk add-feature
# Output: Classificação HIGH/ARCH detectada

/suggest-adr add-feature
# Sugere criação de ADR antes de prosseguir
```

### Ponto 2: Durante Design

```
/opsx:continue add-feature  # Gera design.md

# Ao revisar design.md, percebe que é decisão arquitetural
/suggest-adr add-feature --auto-create
```

### Ponto 3: Checklist Pré-Archive

```
# Antes de arquivar change HIGH
/suggest-adr add-feature
# Verifica se ADR existe, alerta se não

# Se não existir, cria
/suggest-adr add-feature --auto-create

# Depois arquiva
/opsx:archive add-feature
```

---

## Convenções de Nomenclatura

### Arquivos ADR

Formato: `ADR-XXXX-titulo-descritivo.md`

- `XXXX`: Número sequencial (0001, 0002, etc.)
- `titulo-descritivo`: Kebab-case, descritivo, em inglês ou português

Exemplos:

- `ADR-0001-database-choice.md`
- `ADR-0002-authentication-strategy.md`
- `ADR-0003-migration-to-postgresql.md`

### Títulos no ADR

Devem ser descritivos e claros:

✅ **Bons:**

- "Migration from SQLite to PostgreSQL"
- "Authentication with JWT Tokens"
- "Adoption of Celery for Background Tasks"

❌ **Evitar:**

- "Database stuff"
- "Auth decision"
- "New library"

---

## Status de ADR

O template usa status padronizados:

| Status | Quando Usar |
|--------|-------------|
| **Proposed** | ADR recém-criado, ainda em discussão |
| **Accepted** | Decisão confirmada e sendo implementada |
| **Deprecated** | Decisão não é mais válida, mas mantida para histórico |
| **Superseded by ADR-XXXX** | Decisão substituída por nova ADR |

---

## Exemplos Reais de Uso

### Exemplo 1: Projeto Django Novo

```bash
# Setup inicial
/esaa-generate-agents
openspec init

# Primeira decisão arquitetural: banco de dados
/opsx:new choose-database
# Cria proposal: "Escolher entre SQLite e PostgreSQL"

/esaa-classify-risk choose-database
# Score: 4 (HIGH) - decisão afeta toda a arquitetura

/suggest-adr choose-database --auto-create
# Cria ADR-0001-database-choice.md

# Edita ADR para adicionar detalhes da decisão
vim docs/adr/ADR-0001-database-choice.md

# Implementa a decisão
/opsx:apply choose-database
/opsx:archive choose-database
```

### Exemplo 2: Mudança de Autenticação

```bash
# Change de auth
/opsx:new implement-jwt-auth
/esaa-classify-risk implement-jwt-auth
# Score: 6 (HIGH/ARCH)

/suggest-adr implement-jwt-auth
# Mostra template completo de auth

# Revisa template, decide criar
/suggest-adr implement-jwt-auth --auto-create

# Implementa seguindo a ADR
/opsx:apply implement-jwt-auth
/opsx:archive implement-jwt-auth
```

---

## Instalação

```bash
# 1. Copiar para skills do Pi
cp -r suggest-adr ~/.pi/skills/

# 2. Dependências
pip install pyyaml

# 3. Disponível como /suggest-adr
```

---

## Dicas de Uso

### 1. Não seja Perfeccionista

ADR não precisa ser um documento acadêmico. Foque em:

- Contexto (por que fizemos isso?)
- Decisão (o que fizemos?)
- Consequências (o que ganhamos/perdemos?)

### 2. Atualize Status

```markdown
## Status
Proposed    # Quando cria
Accepted    # Quando decide implementar
Deprecated  # Quando muda de ideia
```

### 3. Link com Changes

Sempre mantenha rastreabilidade:

```markdown
## Notes
- ADR criado a partir do change: migrate-to-postgres
- Related Changes: [migrate-to-postgres, update-db-config]
```

### 4. Revise Periodicamente

```bash
# Listar ADRs antigas
ls -lt docs/adr/

# Marcar como Deprecated se necessário
vim docs/adr/ADR-0003-old-decision.md
# Mudar Status para "Superseded by ADR-0008"
```

---

## Relação com Outras Skills

| Skill | Quando Usar | Relação com suggest-adr |
|-------|-------------|------------------------------|
| `esaa-classify-risk` | Antes | Detecta se é HIGH/ARCH |
| `suggest-adr` | Durante | Cria documentação da decisão |
| `esaa-generate-agents` | Setup | Define onde salvar ADRs |
| `esaa-apply-slice` | Implementação | Segue decisão documentada |

---

## Checklist: Quando Criar ADR

- [ ] Change classificado como HIGH/ARCH?
- [ ] Afeta autenticação/autorização?
- [ ] Migração de dados ou mudança de banco?
- [ ] Nova API pública ou contrato externo?
- [ ] Troca de biblioteca/framework core?
- [ ] Mudança de padrão arquitetural?
- [ ] Impacto em deploy/infraestrutura?
- [ ] Decisão difícil de reverter?

**Se marcou 2+ itens:** Crie ADR.

---

*Skill criada para SOP ESAA Solopreneur v4.1 — Documente decisões, não as esqueça*
