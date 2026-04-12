---
name: validate-agents
description: Checklist e protocolo para validar aderência do código ao AGENTS.md.
---

# Skill: validate-agents

**Propósito:** Validar que código gerado segue as regras definidas no `AGENTS.md` — segunda linha de defesa contra anti-patterns.

**Quando usar:**

- Após implementar um slice (antes do commit)
- Quando suspeita que IA "esqueceu" regras
- Antes de finalizar change FEATURE/HIGH
- Na revisão de código de terceiros (se aplicável)

**Comando:**

```bash
/validate-agents [arquivos...] [--fix]
```

Opções:

- `arquivos`: Arquivos específicos para validar (default: arquivos modificados)
- `--fix`: Tenta corrigir problemas automaticamente (quando seguro)

## Método recomendado (script)

Use o script incluído para validação determinística:

```bash
python3 validate_agents.py --project-root .
python3 validate_agents.py --project-root . --staged
python3 validate_agents.py --project-root . --fix --fail-on medium
python3 validate_agents.py --project-root . --format json
python3 validate_agents.py --project-root . --fail-on medium
```

Exit codes: `0` ok, `1` erro de execução, `2` policy fail (`--fail-on`).

---

## O que a Skill Faz

1. **Lê AGENTS.md** — Extrai regras da seção "Anti-Patterns Proibidos"
2. **Analisa código** — Verifica arquivos Python/JavaScript contra as regras
3. **Detecta violações** — Lista problemas encontrados com linha/coluna
4. **Sugere correções** — Mostra como deveria ser
5. **(Opcional) Corrige** — Aplica correções seguras automaticamente

---

## Regras Validadas (Django)

Baseado no template AGENTS.md para Django:

| Regra | Detecção | Severidade |
|-------|----------|------------|
| **Lógica em views** | `def view_*` com queries complexas ou business logic | 🔴 Crítica |
| **Queries em templates** | `{{ objeto.query }}` ou filtros que acessam DB | 🔴 Crítica |
| **JavaScript inline** | `<script>` em templates HTML | 🟡 Média |
| **Migrações não testadas** | Arquivo `0*.py` em `migrations/` sem test correspondente | 🟡 Média |
| **N+1 queries** | Loop `for` + acesso a related sem `select_related`/`prefetch_related` | 🔴 Crítica |
| **Raw SQL sem parametrização** | `cursor.execute(f"...")` ou `.raw()` com f-string | 🔴 Crítica |
| **Secrets hardcoded** | `API_KEY = "..."`, `PASSWORD = "..."` em código | 🔴 Crítica |
| **print() em produção** | `print()` em vez de logging | 🟡 Média |
| **Import * (wildcard)** | `from module import *` | 🟡 Média |
| **Funções muito longas** | `def` com >50 linhas | 🟢 Baixa |
| **Código duplicado** | Blocos idênticos em múltiplos lugares | 🟡 Média |
| **Except bare** | `except:` sem exceção específica | 🟡 Média |
| **TODO/FIXME sem issue** | Comentários `TODO` sem referência | 🟢 Baixa |

---

## Exemplos de Saída

### Exemplo 1: Detecta Lógica em View

```
$ /validate-agents payments/views.py

🔍 Validando contra AGENTS.md...
📄 Regras carregadas: 12 anti-patterns
🎯 Arquivos: payments/views.py

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
❌ VIOLAÇÕES ENCONTRADAS (3)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔴 CRÍTICA: Lógica de negócio em view
Arquivo: payments/views.py:45
Regra: "NUNCA lógica de negócio em views (use services.py)"

Código problemático:
  45 | def process_payment(request):
  46 |     order = Order.objects.get(id=request.POST['order_id'])
  47 |     # Cálculo complexo de desconto
  48 |     discount = 0
  49 |     if order.customer.is_vip:
  50 |         discount = order.total * 0.1
  51 |     elif order.total > 1000:
  52 |         discount = order.total * 0.05
  53 |     # ... mais 20 linhas de cálculo

Sugestão:
  Mover todo o cálculo de desconto para payments/services.py:
  
  # services.py
  def calculate_discount(order):
      if order.customer.is_vip:
          return order.total * 0.1
      elif order.total > 1000:
          return order.total * 0.05
      return 0
  
  # views.py
  from .services import calculate_discount
  
  def process_payment(request):
      order = Order.objects.get(id=request.POST['order_id'])
      discount = calculate_discount(order)

Correção automática disponível? ❌ Não (requer análise de domínio)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔴 CRÍTICA: Query N+1 detectada
Arquivo: payments/views.py:78
Regra: "NUNCA esquecer select_related/prefetch_related em queries N+1"

Código problemático:
  78 | for order in Order.objects.filter(status='pending'):
  79 |     print(order.customer.name)  # Query extra!

Sugestão:
  Order.objects.filter(status='pending').select_related('customer')

Correção automática disponível? ✅ Sim
Run with --fix to apply

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🟡 MÉDIA: JavaScript inline
Arquivo: templates/payments/checkout.html:23
Regra: "NUNCA JavaScript inline (use arquivos .js em static/)"

Código problemático:
  23 | <script>
  24 |     function processCard() { ... }
  25 | </script>

Sugestão:
  Mover para static/js/payments/checkout.js
  
  checkout.html:
  <script src="{% static 'js/payments/checkout.js' %}"></script>

Correção automática disponível? ❌ Não (requer criar arquivo)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Resumo:
  🔴 Críticas: 2 (devem ser corrigidas antes do commit)
  🟡 Médias: 1 (recomendado corrigir)
  🟢 Baixas: 0

⚠️  Corrija as violações CRÍTICAS antes de prosseguir.
```

### Exemplo 2: Correção Automática

```
$ /validate-agents --fix

🔍 Validando arquivos modificados...
🛠️  Modo correção automática ativado

🔴 CRÍTICA: Query N+1 detectada (views.py:78)
✅ Corrigido automaticamente:
   Order.objects.filter(status='pending')
   ↓
   Order.objects.filter(status='pending').select_related('customer')

🟡 MÉDIA: Import wildcard (models.py:3)
✅ Corrigido automaticamente:
   from django.db.models import *
   ↓
   from django.db.models import Q, F, Count

🔴 CRÍTICA: Lógica em view (views.py:45)
❌ Não pôde ser corrigido automaticamente (requer criação de services.py)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Correções aplicadas: 2
Correções manuais necessárias: 1

📝 Arquivos modificados:
  - payments/views.py
  - orders/models.py

Execute: git diff para revisar mudanças
```

### Exemplo 3: Sem Violações

```
$ /validate-agents

🔍 Validando contra AGENTS.md...
📄 Regras carregadas: 12 anti-patterns
🎯 Arquivos modificados: 3

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ CÓDIGO VALIDADO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Nenhuma violação de anti-patterns detectada!

📊 Estatísticas:
  - Arquivos analisados: 3
  - Linhas de código: 450
  - Funções verificadas: 12
  - Queries verificadas: 8

🎯 Pronto para commit!
```

---

## Implementação

### Dependências

```python
# requirements.txt
ast-unparse>=1.6.0  # Para análise AST de Python
pyyaml>=6.0
```

### Estrutura

```
validate-agents/
├── SKILL.md              # Este arquivo
├── validate.py           # Script principal
├── parsers/
│   ├── __init__.py
│   ├── agents.py         # Parser de AGENTS.md
│   ├── python.py         # Analisador de código Python
│   └── django.py         # Regras específicas de Django
├── fixers/
│   ├── __init__.py
│   └── auto_fix.py       # Correções automáticas
└── utils.py              # Funções auxiliares
```

### Lógica Principal (validate.py)

```python
#!/usr/bin/env python3
"""
Validador de código contra AGENTS.md
SOP ESAA Solopreneur v4.1
"""

import ast
import re
import sys
import argparse
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from enum import Enum

class Severity(Enum):
    CRITICAL = "critical"  # 🔴
    MEDIUM = "medium"      # 🟡
    LOW = "low"            # 🟢

@dataclass
class Violation:
    rule: str
    file: Path
    line: int
    column: int
    severity: Severity
    code_snippet: str
    suggestion: str
    auto_fixable: bool

class AgentsParser:
    """Extrai regras do AGENTS.md"""
    
    ANTI_PATTERN_PATTERNS = {
        "logic_in_views": {
            "keywords": ["lógica de negócio em views", "business logic in views"],
            "severity": Severity.CRITICAL,
            "check": "logic_in_views"
        },
        "queries_in_templates": {
            "keywords": ["queries em templates", "queries in templates"],
            "severity": Severity.CRITICAL,
            "check": "template_queries"
        },
        "js_inline": {
            "keywords": ["javascript inline", "js inline"],
            "severity": Severity.MEDIUM,
            "check": "inline_javascript"
        },
        "untested_migrations": {
            "keywords": ["migrações sem testar", "migrations without testing"],
            "severity": Severity.MEDIUM,
            "check": "migration_tests"
        },
        "n_plus_one": {
            "keywords": ["n+1", "select_related", "prefetch_related"],
            "severity": Severity.CRITICAL,
            "check": "n_plus_one"
        },
        "raw_sql": {
            "keywords": ["raw sql", "sql injection"],
            "severity": Severity.CRITICAL,
            "check": "unsafe_sql"
        },
        "secrets": {
            "keywords": ["secrets", "hardcoded", "api_key", "password"],
            "severity": Severity.CRITICAL,
            "check": "hardcoded_secrets"
        },
        "print_debug": {
            "keywords": ["print", "debug"],
            "severity": Severity.MEDIUM,
            "check": "print_statements"
        },
        "wildcard_imports": {
            "keywords": ["import *", "wildcard"],
            "severity": Severity.MEDIUM,
            "check": "wildcard_imports"
        },
        "long_functions": {
            "keywords": ["funções longas", "long functions"],
            "severity": Severity.LOW,
            "check": "function_length",
            "threshold": 50
        }
    }
    
    def __init__(self, project_root: str = "."):
        self.root = Path(project_root)
        self.rules = []
        
    def parse(self) -> List[Dict]:
        """Extrai regras do AGENTS.md"""
        agents_file = self.root / "AGENTS.md"
        if not agents_file.exists():
            return []
        
        content = agents_file.read_text().lower()
        rules = []
        
        # Detecta quais regras estão presentes no AGENTS.md
        for rule_id, config in self.ANTI_PATTERN_PATTERNS.items():
            for keyword in config["keywords"]:
                if keyword in content:
                    rules.append({
                        "id": rule_id,
                        "severity": config["severity"],
                        "check": config["check"],
                        "keyword": keyword
                    })
                    break
        
        return rules


class PythonAnalyzer(ast.NodeVisitor):
    """Analisador AST para código Python"""
    
    def __init__(self, file_path: Path, rules: List[Dict]):
        self.file_path = file_path
        self.rules = rules
        self.violations = []
        self.current_function = None
        self.function_lines = 0
        
    def analyze(self, code: str) -> List[Violation]:
        """Analisa código e retorna violações"""
        try:
            tree = ast.parse(code)
            self.visit(tree)
        except SyntaxError:
            # Arquivo pode ter syntax errors, ignora
            pass
        return self.violations
    
    def visit_FunctionDef(self, node):
        """Detecta funções longas e lógica em views"""
        old_function = self.current_function
        old_lines = self.function_lines
        
        self.current_function = node.name
        lines = node.end_lineno - node.lineno if node.end_lineno else 50
        self.function_lines = lines
        
        # Verifica função longa
        if self._should_check("function_length") and lines > 50:
            self.violations.append(Violation(
                rule="Função muito longa (>50 linhas)",
                file=self.file_path,
                line=node.lineno,
                column=node.col_offset,
                severity=Severity.LOW,
                code_snippet=f"def {node.name}(...): # {lines} linhas",
                suggestion="Divida em funções menores",
                auto_fixable=False
            ))
        
        # Verifica se é view e tem lógica complexa
        if self._should_check("logic_in_views") and self._is_view(node):
            complexity = self._calculate_complexity(node)
            if complexity > 10:
                self.violations.append(Violation(
                    rule="Lógica de negócio em view",
                    file=self.file_path,
                    line=node.lineno,
                    column=node.col_offset,
                    severity=Severity.CRITICAL,
                    code_snippet=f"def {node.name}(...): # complexidade {complexity}",
                    suggestion="Mover lógica para services.py",
                    auto_fixable=False
                ))
        
        self.generic_visit(node)
        
        self.current_function = old_function
        self.function_lines = old_lines
    
    def visit_For(self, node):
        """Detecta N+1 queries em loops"""
        if self._should_check("n_plus_one"):
            n_plus_one = self._detect_n_plus_one(node)
            if n_plus_one:
                self.violations.append(Violation(
                    rule="Query N+1 detectada",
                    file=self.file_path,
                    line=node.lineno,
                    column=node.col_offset,
                    severity=Severity.CRITICAL,
                    code_snippet=ast.unparse(node)[:100],
                    suggestion="Adicionar .select_related() ou .prefetch_related()",
                    auto_fixable=True
                ))
        
        self.generic_visit(node)
    
    def visit_ImportFrom(self, node):
        """Detecta wildcard imports"""
        if self._should_check("wildcard_imports"):
            for alias in node.names:
                if alias.name == "*":
                    self.violations.append(Violation(
                        rule="Import wildcard (import *)",
                        file=self.file_path,
                        line=node.lineno,
                        column=node.col_offset,
                        severity=Severity.MEDIUM,
                        code_snippet=f"from {node.module} import *",
                        suggestion=f"Especifique imports: from {node.module} import name1, name2",
                        auto_fixable=False
                    ))
        
        self.generic_visit(node)
    
    def visit_Call(self, node):
        """Detecta print(), raw SQL, etc."""
        # Detecta print()
        if self._should_check("print_statements"):
            if isinstance(node.func, ast.Name) and node.func.id == "print":
                self.violations.append(Violation(
                    rule="Uso de print() (use logging)",
                    file=self.file_path,
                    line=node.lineno,
                    column=node.col_offset,
                    severity=Severity.MEDIUM,
                    code_snippet="print(...)",
                    suggestion="Use logging.info() ou logger.debug()",
                    auto_fixable=False
                ))
        
        # Detecta raw SQL
        if self._should_check("unsafe_sql"):
            if self._is_unsafe_sql(node):
                self.violations.append(Violation(
                    rule="SQL potencialmente inseguro",
                    file=self.file_path,
                    line=node.lineno,
                    column=node.col_offset,
                    severity=Severity.CRITICAL,
                    code_snippet=ast.unparse(node)[:80],
                    suggestion="Use parametrização ou ORM",
                    auto_fixable=False
                ))
        
        self.generic_visit(node)
    
    def _should_check(self, check_name: str) -> bool:
        """Verifica se uma regra deve ser verificada"""
        return any(rule["check"] == check_name for rule in self.rules)
    
    def _is_view(self, node) -> bool:
        """Heurística para detectar se função é view Django"""
        # Verifica se tem request como parâmetro
        args = [arg.arg for arg in node.args.args]
        return "request" in args
    
    def _calculate_complexity(self, node) -> int:
        """Calcula complexidade ciclomática básica"""
        count = 1
        for child in ast.walk(node):
            if isinstance(child, (ast.If, ast.While, ast.For, ast.ExceptHandler)):
                count += 1
        return count
    
    def _detect_n_plus_one(self, node) -> bool:
        """Heurística simples para N+1"""
        # Verifica se há acesso a atributo em loop
        for child in ast.walk(node):
            if isinstance(child, ast.Attribute):
                # Acesso tipo objeto.relacionado.campo
                return True
        return False
    
    def _is_unsafe_sql(self, node) -> bool:
        """Detecta SQL sem parametrização"""
        func_name = ""
        if isinstance(node.func, ast.Attribute):
            func_name = node.func.attr
        elif isinstance(node.func, ast.Name):
            func_name = node.func.id
        
        if func_name in ["execute", "raw"]:
            # Verifica se primeiro argumento é f-string
            if node.args:
                first_arg = node.args[0]
                if isinstance(first_arg, ast.JoinedStr):  # f-string
                    return True
        return False


class TemplateAnalyzer:
    """Analisador para templates Django/HTML"""
    
    def __init__(self, rules: List[Dict]):
        self.rules = rules
        self.violations = []
    
    def analyze(self, file_path: Path) -> List[Violation]:
        """Analisa template HTML/Django"""
        content = file_path.read_text()
        
        # Detecta JavaScript inline
        if self._should_check("inline_javascript"):
            if "<script>" in content or "<script " in content:
                # Verifica se é src ou inline
                if re.search(r'<script[^>]*>(?!</script>)', content, re.DOTALL):
                    lines = content[:content.find('<script')].count('\n') + 1
                    self.violations.append(Violation(
                        rule="JavaScript inline em template",
                        file=file_path,
                        line=lines,
                        column=0,
                        severity=Severity.MEDIUM,
                        code_snippet="<script>...</script>",
                        suggestion="Mover para static/js/",
                        auto_fixable=False
                    ))
        
        # Detecta queries em templates
        if self._should_check("template_queries"):
            # Padrões como {{ objeto.query }}, {{ objeto.filter().count }}
            patterns = [
                r'\{\{\s*\w+\.(filter|exclude|get|all|count|first|last)\s*\}\}',
                r'\{\%\s*for.*in\s*\w+\.(filter|exclude|all)\s*\%\}'
            ]
            for pattern in patterns:
                matches = re.finditer(pattern, content)
                for match in matches:
                    line = content[:match.start()].count('\n') + 1
                    self.violations.append(Violation(
                        rule="Query em template",
                        file=file_path,
                        line=line,
                        column=match.start(),
                        severity=Severity.CRITICAL,
                        code_snippet=match.group()[:50],
                        suggestion="Prepare dados na view, passe via context",
                        auto_fixable=False
                    ))
        
        return self.violations
    
    def _should_check(self, check_name: str) -> bool:
        return any(rule["check"] == check_name for rule in self.rules)


class Validator:
    """Orquestrador principal"""
    
    def __init__(self, project_root: str = "."):
        self.root = Path(project_root)
        self.agents_parser = AgentsParser(project_root)
        self.all_violations = []
        
    def validate(self, files: Optional[List[Path]] = None, auto_fix: bool = False) -> bool:
        """Valida arquivos contra AGENTS.md"""
        # Carrega regras
        rules = self.agents_parser.parse()
        if not rules:
            print("⚠️  Nenhuma regra encontrada em AGENTS.md")
            print("   Validando com regras padrão...")
            rules = list(AgentsParser.ANTI_PATTERN_PATTERNS.values())
        
        print(f"🔍 Validando contra AGENTS.md...")
        print(f"📄 Regras carregadas: {len(rules)} anti-patterns\n")
        
        # Determina arquivos
        if files is None:
            files = self._get_modified_files()
        
        print(f"🎯 Arquivos: {len(files)}")
        
        # Valida cada arquivo
        for file_path in files:
            if file_path.suffix == '.py':
                violations = self._validate_python(file_path, rules)
            elif file_path.suffix in ['.html', '.htm']:
                violations = self._validate_template(file_path, rules)
            else:
                continue
            
            self.all_violations.extend(violations)
        
        # Reporta
        return self._report(auto_fix)
    
    def _get_modified_files(self) -> List[Path]:
        """Obtém arquivos modificados (git status)"""
        import subprocess
        try:
            result = subprocess.run(
                ["git", "diff", "--name-only", "--cached"],
                capture_output=True,
                text=True
            )
            files = [self.root / f for f in result.stdout.strip().split('\n') if f]
            
            # Também inclui unstaged
            result2 = subprocess.run(
                ["git", "diff", "--name-only"],
                capture_output=True,
                text=True
            )
            files.extend([self.root / f for f in result2.stdout.strip().split('\n') if f])
            
            return list(set(files))  # Remove duplicatas
        except:
            # Fallback: todos os arquivos Python
            return list(self.root.rglob("*.py"))[:10]  # Limita
    
    def _validate_python(self, file_path: Path, rules: List[Dict]) -> List[Violation]:
        """Valida arquivo Python"""
        try:
            code = file_path.read_text()
            analyzer = PythonAnalyzer(file_path, rules)
            return analyzer.analyze(code)
        except:
            return []
    
    def _validate_template(self, file_path: Path, rules: List[Dict]) -> List[Violation]:
        """Valida template"""
        analyzer = TemplateAnalyzer(rules)
        return analyzer.analyze(file_path)
    
    def _report(self, auto_fix: bool) -> bool:
        """Gera relatório e aplica correções se solicitado"""
        if not self.all_violations:
            print("\n" + "━"*50)
            print("✅ CÓDIGO VALIDADO")
            print("━"*50)
            print("\nNenhuma violação de anti-patterns detectada!")
            return True
        
        # Agrupa por severidade
        critical = [v for v in self.all_violations if v.severity == Severity.CRITICAL]
        medium = [v for v in self.all_violations if v.severity == Severity.MEDIUM]
        low = [v for v in self.all_violations if v.severity == Severity.LOW]
        
        print("\n" + "━"*50)
        print(f"❌ VIOLAÇÕES ENCONTRADAS ({len(self.all_violations)})")
        print("━"*50)
        
        # Reporta críticas
        for v in critical:
            self._print_violation(v, "🔴 CRÍTICA")
        
        for v in medium:
            self._print_violation(v, "🟡 MÉDIA")
        
        for v in low:
            self._print_violation(v, "🟢 BAIXA")
        
        # Sumário
        print("\n" + "━"*50)
        print("Resumo:")
        print(f"  🔴 Críticas: {len(critical)} (devem ser corrigidas)")
        print(f"  🟡 Médias: {len(medium)} (recomendado)")
        print(f"  🟢 Baixas: {len(low)} (opcional)")
        
        if auto_fix:
            self._apply_fixes()
        
        if critical:
            print("\n⚠️  Corrija as violações CRÍTICAS antes de prosseguir.")
            return False
        
        return True
    
    def _print_violation(self, v: Violation, label: str):
        """Imprime uma violação formatada"""
        print(f"\n{label}: {v.rule}")
        print(f"Arquivo: {v.file}:{v.line}")
        print(f"Regra: \"{v.rule}\"")
        print(f"\nCódigo problemático:")
        print(f"  {v.code_snippet}")
        print(f"\nSugestão:")
        for line in v.suggestion.split('\n'):
            print(f"  {line}")
        print(f"\nCorreção automática: {'✅ Sim' if v.auto_fixable else '❌ Não'}")
        print("━"*50)
    
    def _apply_fixes(self):
        """Aplica correções automáticas"""
        fixable = [v for v in self.all_violations if v.auto_fixable]
        print(f"\n🛠️  Aplicando {len(fixable)} correções automáticas...")
        # Implementação de correções automáticas
        # (simplificado para o exemplo)


def main():
    parser = argparse.ArgumentParser(description="Valida código contra AGENTS.md")
    parser.add_argument("files", nargs="*", help="Arquivos específicos")
    parser.add_argument("--fix", action="store_true", help="Aplica correções automáticas")
    parser.add_argument("--all", action="store_true", help="Valida todos os arquivos")
    args = parser.parse_args()
    
    validator = Validator()
    
    files = None
    if args.files:
        files = [Path(f) for f in args.files]
    elif args.all:
        files = list(Path(".").rglob("*.py"))
    
    success = validator.validate(files, args.fix)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
```

---

## Integração com Workflow

```bash
# Após implementar slice
/esaa-apply-slice change=add-feature slice=1.2

# Antes de commit, valida
/validate-agents

# Se tudo OK
 git commit -m "feat: ..."

# Se encontrar problemas
# Corrige, roda de novo
/validate-agents --fix
/validate-agents
```

---

## Instalação

```bash
cp -r validate-agents ~/.pi/skills/
pip install ast-unparse pyyaml
```

---

*Skill criada para SOP ESAA Solopreneur v4.1 — Garanta que código siga as regras*
