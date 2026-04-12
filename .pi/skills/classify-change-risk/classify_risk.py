#!/usr/bin/env python3
"""
Classify Change Risk - Script Python para classificar risco de mudanças.

Analisa descrições de mudanças e classifica em:
- ESSENTIAL (baixo risco)
- PROFESSIONAL (médio risco)  
- CRITICAL (alto risco)

Baseado no workflow ESAA Solopreneur v4.2 com regras específicas para setor público.

Licença: MIT
"""

import json
import sys
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import argparse
import datetime

# ============================================================================
# Configurações e regras
# ============================================================================

# Palavras-chave para cada nível de risco (inglês e português)
RISK_KEYWORDS = {
    "critical": [
        # Segurança (security)
        "security", "vulnerability", "authentication", "authorization", "password",
        "encryption", "ssl", "tls", "certificate", "login", "session",
        "injection", "xss", "csrf", "sqli",
        # Português
        "segurança", "vulnerabilidade", "autenticação", "autorização", "senha",
        "criptografia", "certificado", "sessão", "login",
        
        # Dados sensíveis (sensitive data)
        "gdpr", "lgpd", "pii", "personal data", "sensitive data", "privacy",
        "compliance", "regulation", "audit", "legal", "compliance",
        # Português
        "dados pessoais", "dados sensíveis", "privacidade", "conformidade",
        "auditoria", "legal", "regulamentação", "cpf", "cnpj", "rg",
        
        # Infraestrutura crítica (critical infrastructure)
        "database", "migration", "backup", "restore", "deployment", "production",
        "server", "infrastructure", "scaling", "load balancer", "firewall",
        # Português
        "banco de dados", "migração", "backup", "restauração", "deploy", "produção",
        "servidor", "infraestrutura", "escalabilidade", "firewall",
        
        # Financeiro (financial)
        "payment", "transaction", "billing", "invoice", "money", "financial",
        "tax", "fiscal", "accounting",
        # Português
        "pagamento", "transação", "fatura", "dinheiro", "financeiro",
        "imposto", "fiscal", "contabilidade",
        
        # Funcionalidades core (core functionality)
        "core functionality", "main feature", "critical path", "business logic",
        # Português
        "funcionalidade principal", "funcionalidade core", "lógica de negócio",
        
        # Impacto alto (high impact)
        "breaking change", "api change", "data loss", "downtime", "outage",
        "performance degradation", "memory leak", "crash", "error handling",
        # Português
        "mudança quebra", "perda de dados", "queda", "indisponibilidade",
        "degradação de performance", "vazamento de memória", "crash", "erro",
    ],
    
    "professional": [
        # Novas funcionalidades (new features)
        "new feature", "enhancement", "improvement", "optimization",
        "refactor", "restructure", "code quality", "technical debt",
        # Português
        "nova funcionalidade", "melhoria", "otimização", "refatoração",
        "reestruturação", "qualidade de código", "dívida técnica",
        
        # Integrações (integrations)
        "integration", "api", "webhook", "third-party", "external service",
        # Português
        "integração", "api", "webhook", "terceiros", "serviço externo",
        
        # UI/UX
        "ui", "ux", "user interface", "user experience", "design", "layout",
        "responsive", "mobile", "accessibility", "a11y",
        # Português
        "interface", "experiência do usuário", "design", "layout",
        "responsivo", "mobile", "acessibilidade",
        
        # Testes (tests)
        "test", "testing", "coverage", "unit test", "integration test",
        "e2e", "end to end",
        # Português
        "teste", "testes", "cobertura", "teste unitário", "teste de integração",
        "end to end", "e2e",
        
        # Documentação (documentation)
        "documentation", "readme", "api docs", "tutorial", "guide",
        # Português
        "documentação", "readme", "docs", "tutorial", "guia",
        
        # Configuração (configuration)
        "configuration", "settings", "environment", "deploy", "ci/cd",
        # Português
        "configuração", "settings", "ambiente", "deploy", "ci/cd",
        
        # Dependências (dependencies)
        "dependency", "library", "package", "update version", "upgrade",
        # Português
        "dependência", "biblioteca", "pacote", "atualizar versão", "upgrade",
    ],
    
    "essential": [
        # Correções simples (simple fixes)
        "bug fix", "typo", "spelling", "grammar", "text", "label",
        "minor fix", "small fix", "quick fix",
        # Português
        "correção de bug", "typo", "ortografia", "gramática", "texto", "rótulo",
        "correção menor", "correção pequena", "correção rápida",
        
        # Estilo/formação (style/formatting)
        "formatting", "linting", "style", "whitespace", "indentation",
        "code style", "pep8", "eslint",
        # Português
        "formatação", "lint", "estilo", "espaço em branco", "indentação",
        "estilo de código",
        
        # Documentação menor (minor documentation)
        "comment", "docstring", "inline comment", "changelog", "log",
        # Português
        "comentário", "docstring", "comentário inline", "changelog", "log",
        
        # Configurações menores (minor configurations)
        "config", "setting", "parameter", "option",
        # Português
        "config", "configuração", "parâmetro", "opção",
        
        # Assets
        "image", "icon", "font", "css", "stylesheet", "color",
        # Português
        "imagem", "ícone", "fonte", "css", "stylesheet", "cor",
        
        # Testes simples (simple tests)
        "test update", "mock", "fixture",
        # Português
        "atualização de teste", "mock", "fixture",
    ]
}

# Fatores de ponderação
WEIGHT_FACTORS = {
    "impact_users": {
        "all": 3.0,
        "many": 2.0,
        "some": 1.5,
        "few": 1.0,
        "none": 0.5
    },
    "impact_data": {
        "sensitive": 3.0,
        "important": 2.0,
        "regular": 1.0,
        "none": 0.5
    },
    "complexity": {
        "very_high": 2.5,
        "high": 2.0,
        "medium": 1.5,
        "low": 1.0,
        "very_low": 0.8
    },
    "dependencies": {
        "many": 2.0,
        "some": 1.5,
        "few": 1.2,
        "none": 1.0
    }
}

# Limiares para classificação
THRESHOLDS = {
    "critical": 8.0,
    "professional": 4.0,
    "essential": 0.0
}

# ============================================================================
# Funções principais
# ============================================================================

def analyze_text(text: str) -> Dict[str, Any]:
    """Analisa texto para extrair características de risco."""
    text_lower = text.lower()
    
    # Contar ocorrências de palavras-chave
    keyword_counts = {"critical": 0, "professional": 0, "essential": 0}
    keyword_matches = {"critical": [], "professional": [], "essential": []}
    
    for level, keywords in RISK_KEYWORDS.items():
        for keyword in keywords:
            # Buscar palavra inteira (com boundaries)
            pattern = r'\b' + re.escape(keyword) + r'\b'
            matches = re.findall(pattern, text_lower)
            if matches:
                keyword_counts[level] += len(matches)
                keyword_matches[level].append(keyword)
    
    # Análise de sentenças
    sentences = re.split(r'[.!?]+', text)
    sentence_count = len([s for s in sentences if s.strip()])
    
    # Palavras por sentença (complexidade aproximada)
    words = re.findall(r'\b\w+\b', text)
    word_count = len(words)
    avg_words_per_sentence = word_count / max(sentence_count, 1)
    
    # Detectar padrões específicos
    patterns = {
        "has_security_terms": bool(re.search(r'\b(security|auth|password|encrypt)\b', text_lower)),
        "has_data_terms": bool(re.search(r'\b(data|database|gdpr|lgpd|pii)\b', text_lower)),
        "has_financial_terms": bool(re.search(r'\b(payment|money|financial|tax)\b', text_lower)),
        "has_infrastructure_terms": bool(re.search(r'\b(server|deploy|production|infra)\b', text_lower)),
        "has_test_terms": bool(re.search(r'\b(test|coverage|unit|integration)\b', text_lower)),
        "has_documentation_terms": bool(re.search(r'\b(doc|readme|comment|guide)\b', text_lower)),
        "has_ui_terms": bool(re.search(r'\b(ui|ux|design|layout|css)\b', text_lower)),
    }
    
    return {
        "keyword_counts": keyword_counts,
        "keyword_matches": keyword_matches,
        "sentence_count": sentence_count,
        "word_count": word_count,
        "avg_words_per_sentence": avg_words_per_sentence,
        "patterns": patterns,
        "text_preview": text[:200] + ("..." if len(text) > 200 else "")
    }


def calculate_risk_score(analysis: Dict[str, Any], factors: Dict[str, str]) -> Dict[str, Any]:
    """Calcula score de risco baseado na análise e fatores."""
    # Score base das palavras-chave
    keyword_score = (
        analysis["keyword_counts"]["critical"] * 3.0 +
        analysis["keyword_counts"]["professional"] * 1.5 +
        analysis["keyword_counts"]["essential"] * 0.5
    )
    
    # Ajustar por complexidade do texto
    complexity_factor = min(analysis["avg_words_per_sentence"] / 15, 2.0)
    
    # Aplicar fatores de ponderação
    impact_users = WEIGHT_FACTORS["impact_users"].get(factors.get("impact_users", "some"), 1.0)
    impact_data = WEIGHT_FACTORS["impact_data"].get(factors.get("impact_data", "regular"), 1.0)
    complexity = WEIGHT_FACTORS["complexity"].get(factors.get("complexity", "medium"), 1.0)
    dependencies = WEIGHT_FACTORS["dependencies"].get(factors.get("dependencies", "few"), 1.0)
    
    # Calcular score final
    base_score = keyword_score * complexity_factor
    weighted_score = base_score * impact_users * impact_data * complexity * dependencies
    
    # Determinar nível
    if weighted_score >= THRESHOLDS["critical"]:
        level = "CRITICAL"
        color = "🔴"
    elif weighted_score >= THRESHOLDS["professional"]:
        level = "PROFESSIONAL"
        color = "🟡"
    else:
        level = "ESSENTIAL"
        color = "🟢"
    
    # Confiança (0-100%)
    confidence = min(weighted_score / 15 * 100, 100)  # Normalizado
    
    return {
        "score": round(weighted_score, 2),
        "level": level,
        "color": color,
        "confidence": round(confidence, 1),
        "factors": {
            "keyword_score": round(keyword_score, 2),
            "complexity_factor": round(complexity_factor, 2),
            "impact_users": impact_users,
            "impact_data": impact_data,
            "complexity": complexity,
            "dependencies": dependencies,
        },
        "base_score": round(base_score, 2),
        "weighted_score": round(weighted_score, 2),
    }


def get_recommendations(level: str, analysis: Dict[str, Any]) -> List[str]:
    """Gera recomendações baseadas no nível de risco."""
    recommendations = []
    
    if level == "CRITICAL":
        recommendations.extend([
            "🔴 **Revisão obrigatória**: Requer revisão detalhada por pares (se disponível) ou auto-revisão estruturada",
            "🔴 **Testes extensivos**: Testes unitários, de integração e e2e obrigatórios",
            "🔴 **Plano de rollback**: Definir plano claro de reversão em caso de problemas",
            "🔴 **Documentação completa**: ADR obrigatório, atualizar AGENTS.md e PROJECT_CONTEXT.md",
            "🔴 **Validação extra**: Executar quality gate completo, análise de segurança",
            "🔴 **Comunicação**: Notificar stakeholders sobre mudanças críticas",
            "🔴 **Horário de deploy**: Considerar horário de menor impacto (finais de semana, madrugada)",
        ])
        
        # Recomendações específicas baseadas na análise
        if analysis["patterns"]["has_security_terms"]:
            recommendations.append("🔒 **Segurança**: Realizar análise de segurança específica (bandit, safety check)")
        if analysis["patterns"]["has_data_terms"]:
            recommendations.append("💾 **Dados**: Backup obrigatório antes da mudança, validação de integridade")
        if analysis["patterns"]["has_financial_terms"]:
            recommendations.append("💰 **Financeiro**: Testes com dados de teste, validação com contabilidade")
            
    elif level == "PROFESSIONAL":
        recommendations.extend([
            "🟡 **Revisão recomendada**: Auto-revisão estruturada ou revisão rápida por pares",
            "🟡 **Testes adequados**: Testes unitários obrigatórios, considerar testes de integração",
            "🟡 **Documentação**: Atualizar documentação relevante (comentários, README se necessário)",
            "🟡 **Validação**: Executar quality gate básico antes do commit",
            "🟡 **Comunicação**: Notificar equipe sobre mudanças significativas",
            "🟡 **Deploy planejado**: Agendar deploy em horário comercial com monitoramento",
        ])
        
        if analysis["patterns"]["has_test_terms"]:
            recommendations.append("🧪 **Testes**: Garantir cobertura adequada para novas funcionalidades")
        if analysis["patterns"]["has_ui_terms"]:
            recommendations.append("🎨 **UI/UX**: Testar em diferentes dispositivos e navegadores")
            
    else:  # ESSENTIAL
        recommendations.extend([
            "🟢 **Revisão opcional**: Revisão rápida se houver tempo",
            "🟢 **Testes básicos**: Testes unitários se aplicável, pelo menos smoke test",
            "🟢 **Documentação mínima**: Atualizar comentários/changelog se necessário",
            "🟢 **Validação**: Executar verificações rápidas antes do commit",
            "🟢 **Deploy**: Pode ser feito em qualquer horário, com monitoramento básico",
            "🟢 **Comunicação**: Notificação opcional para a equipe",
        ])
    
    # Recomendações gerais
    recommendations.extend([
        f"📝 **Registro**: Criar change no OpenSpec com nível '{level}'",
        f"⏱️  **Estimativa**: Ajustar estimativa de tempo baseado no nível de risco",
        f"🔍 **Monitoramento**: Monitorar após deploy conforme nível de risco",
    ])
    
    return recommendations


def read_project_context() -> Optional[Dict[str, Any]]:
    """Lê contexto do projeto para ajustar classificação."""
    context_path = Path("PROJECT_CONTEXT.md")
    if not context_path.exists():
        return None
    
    try:
        with open(context_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        context = {
            "has_sensitive_data": "dados sensíveis" in content.lower() or "lgpd" in content.lower() or "gdpr" in content.lower(),
            "has_financial": "financeiro" in content.lower() or "pagamento" in content.lower() or "payment" in content.lower(),
            "has_infrastructure": "infraestrutura" in content.lower() or "production" in content.lower(),
            "is_public_sector": "público" in content.lower() or "governo" in content.lower() or "government" in content.lower(),
        }
        
        return context
    except:
        return None


def adjust_for_project_context(
    score_result: Dict[str, Any],
    context: Optional[Dict[str, Any]],
    analysis: Dict[str, Any],
) -> Dict[str, Any]:
    """Ajusta score baseado no contexto do projeto."""
    if not context:
        return score_result
    
    adjustment_factors = []
    
    # Ajustes para setor público
    if context.get("is_public_sector", False):
        # Aumentar peso de segurança e dados no setor público
        if analysis.get("patterns", {}).get("has_security_terms", False):
            score_result["score"] *= 1.2
            adjustment_factors.append("+20% (setor público + segurança)")
        
        if context.get("has_sensitive_data", False):
            score_result["score"] *= 1.3
            adjustment_factors.append("+30% (dados sensíveis no setor público)")
    
    # Ajustar nível se necessário
    old_level = score_result["level"]
    if score_result["score"] >= THRESHOLDS["critical"] and old_level != "CRITICAL":
        score_result["level"] = "CRITICAL"
        score_result["color"] = "🔴"
    elif score_result["score"] >= THRESHOLDS["professional"] and old_level == "ESSENTIAL":
        score_result["level"] = "PROFESSIONAL"
        score_result["color"] = "🟡"
    
    if adjustment_factors:
        score_result["adjustment_factors"] = adjustment_factors
        score_result["adjusted_score"] = round(score_result["score"], 2)
    
    return score_result


def classify_change(description: str, factors: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Classifica uma mudança baseado na descrição."""
    if factors is None:
        factors = {}
    
    # Análise do texto
    analysis = analyze_text(description)
    
    # Calcular score
    score_result = calculate_risk_score(analysis, factors)
    
    # Ler contexto do projeto
    context = read_project_context()
    
    # Ajustar para contexto
    score_result = adjust_for_project_context(score_result, context, analysis)
    
    # Gerar recomendações
    recommendations = get_recommendations(score_result["level"], analysis)
    
    # Resultado completo
    return {
        "description_preview": analysis["text_preview"],
        "analysis": {
            "keyword_counts": analysis["keyword_counts"],
            "keyword_matches": {k: v[:5] for k, v in analysis["keyword_matches"].items() if v},  # Top 5
            "patterns": analysis["patterns"],
        },
        "risk_assessment": score_result,
        "recommendations": recommendations,
        "context_used": context is not None,
        "project_context": context,
        "timestamp": datetime.datetime.now().isoformat(),
    }


# ============================================================================
# Interface de linha de comando
# ============================================================================

def parse_factors(args: argparse.Namespace) -> Dict[str, str]:
    """Parse fatores da linha de comando."""
    factors = {}
    
    if args.impact_users:
        factors["impact_users"] = args.impact_users
    if args.impact_data:
        factors["impact_data"] = args.impact_data
    if args.complexity:
        factors["complexity"] = args.complexity
    if args.dependencies:
        factors["dependencies"] = args.dependencies
    
    return factors


def main():
    """Função principal."""
    parser = argparse.ArgumentParser(
        description="Classify Change Risk - Classifica risco de mudanças baseado no workflow ESAA",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  %(prog)s "Correção de typo na documentação"
  %(prog)s "Implementar autenticação JWT com refresh tokens" --impact-users many --complexity high
  %(prog)s "Migração do banco de dados PostgreSQL 13 para 15" --format json
  %(prog)s --file change_description.txt
  
Níveis de risco:
  🟢 ESSENTIAL   - Baixo risco, mudanças simples
  🟡 PROFESSIONAL - Médio risco, novas funcionalidades
  🔴 CRITICAL    - Alto risco, segurança, dados, infraestrutura
  
Fatores de ponderação:
  impact-users: none, few, some, many, all
  impact-data: none, regular, important, sensitive
  complexity: very_low, low, medium, high, very_high
  dependencies: none, few, some, many
        """
    )
    
    parser.add_argument(
        "description",
        nargs="?",
        help="Descrição da mudança a ser classificada"
    )
    
    parser.add_argument(
        "--file",
        "-f",
        help="Arquivo contendo a descrição da mudança"
    )
    
    parser.add_argument(
        "--format",
        choices=["text", "json", "markdown"],
        default="text",
        help="Formato de saída (padrão: text)"
    )
    
    parser.add_argument(
        "--impact-users",
        choices=["none", "few", "some", "many", "all"],
        help="Impacto em usuários"
    )
    
    parser.add_argument(
        "--impact-data",
        choices=["none", "regular", "important", "sensitive"],
        help="Impacto em dados"
    )
    
    parser.add_argument(
        "--complexity",
        choices=["very_low", "low", "medium", "high", "very_high"],
        help="Complexidade técnica"
    )
    
    parser.add_argument(
        "--dependencies",
        choices=["none", "few", "some", "many"],
        help="Número de dependências afetadas"
    )
    
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Modo verboso (mostra análise detalhada)"
    )

    parser.add_argument(
        "--strict-exit-codes",
        action="store_true",
        help="Mantem comportamento legado: PROFESSIONAL retorna 1"
    )
    
    args = parser.parse_args()
    
    # Obter descrição
    description = ""
    if args.file:
        try:
            with open(args.file, 'r', encoding='utf-8') as f:
                description = f.read().strip()
        except Exception as e:
            print(f"❌ Erro ao ler arquivo: {e}", file=sys.stderr)
            return 1
    elif args.description:
        description = args.description
    else:
        # Ler da entrada padrão
        print("Digite a descrição da mudança (Ctrl+D para finalizar):", file=sys.stderr)
        try:
            description = sys.stdin.read().strip()
        except KeyboardInterrupt:
            print("\n⏹️  Interrompido", file=sys.stderr)
            return 130
    
    if not description:
        print("❌ Descrição vazia", file=sys.stderr)
        parser.print_help()
        return 1
    
    # Parse fatores
    factors = parse_factors(args)
    
    # Classificar
    try:
        result = classify_change(description, factors)
        
        # Gerar output
        if args.format == "json":
            print(json.dumps(result, indent=2, ensure_ascii=False))
        elif args.format == "markdown":
            print(generate_markdown_report(result, args.verbose))
        else:  # text
            print(generate_text_report(result, args.verbose))
        
        # Codigo de saida:
        # - default: ESSENTIAL/PROFESSIONAL => 0, CRITICAL => 2
        # - strict mode: PROFESSIONAL => 1
        if result["risk_assessment"]["level"] == "CRITICAL":
            return 2  # Código especial para critical
        elif result["risk_assessment"]["level"] == "PROFESSIONAL" and args.strict_exit_codes:
            return 1  # Código para professional
        else:
            return 0  # Sucesso para essential
            
    except Exception as e:
        print(f"💥 Erro durante classificação: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def generate_text_report(result: Dict[str, Any], verbose: bool = False) -> str:
    """Gera relatório em formato texto."""
    lines = []
    
    ra = result["risk_assessment"]
    
    lines.append("=" * 60)
    lines.append("CLASSIFICAÇÃO DE RISCO DE MUDANÇA")
    lines.append("=" * 60)
    lines.append(f"Data: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"Descrição: {result['description_preview']}")
    lines.append("")
    
    # Resultado principal
    lines.append(f"{ra['color']} NÍVEL: {ra['level']}")
    lines.append(f"📊 Score: {ra['score']} (confiança: {ra['confidence']}%)")
    lines.append("")
    
    # Fatores (se verbose)
    if verbose:
        lines.append("Fatores de ponderação:")
        for factor, value in ra["factors"].items():
            lines.append(f"  - {factor}: {value}")
        lines.append("")
    
    # Análise de palavras-chave
    if verbose:
        lines.append("Palavras-chave detectadas:")
        for level in ["critical", "professional", "essential"]:
            matches = result["analysis"]["keyword_matches"].get(level, [])
            if matches:
                lines.append(f"  {level.upper()}: {', '.join(matches[:5])}")
                if len(matches) > 5:
                    lines.append(f"    ... e mais {len(matches) - 5}")
        lines.append("")
    
    # Padrões detectados
    patterns = result["analysis"]["patterns"]
    active_patterns = [k for k, v in patterns.items() if v]
    if active_patterns:
        lines.append("Padrões detectados:")
        for pattern in active_patterns:
            lines.append(f"  - {pattern}")
        lines.append("")
    
    # Contexto do projeto
    if result["context_used"] and verbose:
        lines.append("Contexto do projeto considerado:")
        if result.get("project_context"):
            for key, value in result["project_context"].items():
                lines.append(f"  - {key}: {value}")
        lines.append("")
    
    # Recomendações
    lines.append("RECOMENDAÇÕES:")
    for rec in result["recommendations"][:10]:  # Limitar a 10
        lines.append(f"  {rec}")
    
    if len(result["recommendations"]) > 10:
        lines.append(f"  ... e mais {len(result['recommendations']) - 10} recomendações")
    
    lines.append("")
    lines.append("=" * 60)
    
    return "\n".join(lines)


def generate_markdown_report(result: Dict[str, Any], verbose: bool = False) -> str:
    """Gera relatório em formato Markdown."""
    lines = []
    
    ra = result["risk_assessment"]
    
    lines.append(f"# Classificação de Risco: {ra['color']} {ra['level']}")
    lines.append("")
    lines.append(f"**Data:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Descrição:** {result['description_preview']}")
    lines.append("")
    
    lines.append(f"## 📊 Resultado")
    lines.append("")
    lines.append(f"- **Nível:** {ra['color']} {ra['level']}")
    lines.append(f"- **Score:** {ra['score']}")
    lines.append(f"- **Confiança:** {ra['confidence']}%")
    lines.append("")
    
    if verbose:
        lines.append("### Fatores de Ponderação")
        lines.append("")
        for factor, value in ra["factors"].items():
            lines.append(f"- **{factor}:** {value}")
        lines.append("")
    
    # Análise
    lines.append("## 🔍 Análise")
    lines.append("")
    
    keyword_counts = result["analysis"]["keyword_counts"]
    lines.append("### Palavras-chave por nível")
    lines.append("")
    lines.append(f"- 🔴 **CRITICAL:** {keyword_counts['critical']} palavras")
    lines.append(f"- 🟡 **PROFESSIONAL:** {keyword_counts['professional']} palavras")
    lines.append(f"- 🟢 **ESSENTIAL:** {keyword_counts['essential']} palavras")
    lines.append("")
    
    if verbose:
        for level in ["critical", "professional", "essential"]:
            matches = result["analysis"]["keyword_matches"].get(level, [])
            if matches:
                lines.append(f"**{level.upper()} detectadas:**")
                lines.append("")
                # Agrupar em linhas
                for i in range(0, len(matches), 5):
                    lines.append(f"`{'`, `'.join(matches[i:i+5])}`")
                lines.append("")
    
    # Padrões
    patterns = result["analysis"]["patterns"]
    active_patterns = [k.replace('_', ' ') for k, v in patterns.items() if v]
    if active_patterns:
        lines.append("### Padrões Detectados")
        lines.append("")
        for pattern in active_patterns:
            lines.append(f"- ✅ {pattern}")
        lines.append("")
    
    # Recomendações
    lines.append("## 📋 Recomendações")
    lines.append("")
    
    for i, rec in enumerate(result["recommendations"], 1):
        lines.append(f"{i}. {rec}")
    
    lines.append("")
    lines.append("## 🔗 Próximos Passos")
    lines.append("")
    
    if ra["level"] == "CRITICAL":
        lines.append("1. **Criar ADR** para documentar decisão")
        lines.append("2. **Revisão detalhada** antes de implementar")
        lines.append("3. **Plano de rollback** definido")
        lines.append("4. **Testes extensivos** obrigatórios")
        lines.append("5. **Deploy em horário de baixo impacto**")
    elif ra["level"] == "PROFESSIONAL":
        lines.append("1. **Auto-revisão estruturada**")
        lines.append("2. **Testes unitários** obrigatórios")
        lines.append("3. **Atualizar documentação** relevante")
        lines.append("4. **Quality gate** antes do commit")
    else:
        lines.append("1. **Revisão rápida** se possível")
        lines.append("2. **Testes básicos** recomendados")
        lines.append("3. **Commit com verificação**")
    
    lines.append("")
    lines.append("---")
    lines.append(f"*Classificado por ESAA Risk Classifier v1.0*")
    
    return "\n".join(lines)


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⏹️  Interrompido pelo usuário", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"💥 Erro não tratado: {e}", file=sys.stderr)
        sys.exit(1)
