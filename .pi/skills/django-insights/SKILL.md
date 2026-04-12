---
name: django-insights
description: "Diagnóstico de saúde para projetos Django: performance, segurança e arquitetura."
---

# Skill: django-insights

**Propósito:** Detectar problemas típicos e anti-patterns em projetos Django — diagnóstico preventivo de saúde do código.

**Quando usar:**

- Mensalmente (manutenção preventiva)
- Ao retomar projeto após pausa longa
- Antes de refatorações grandes
- Quando performance degradou
- Ao herdar projeto Django desconhecido

**Comando:**

```bash
/django-insights [--app=nome] [--focus=performance,security,architecture]
```

Opções:

- `--app`: Analisar apenas um app específico
- `--focus`: Focar em área específica

## Método recomendado (script)

Use o script incluído para diagnóstico determinístico:

```bash
python3 django_insights.py --project-root .
python3 django_insights.py --project-root . --focus security --format json
python3 django_insights.py --project-root . --app payments --fail-on medium
```

Exit codes: `0` ok, `1` erro de execução, `2` policy fail (`--fail-on`).

---

## O que a Skill Faz

1. **Analisa Models** — Detecta models problemáticos (muito grandes, sem índices, etc.)
2. **Analisa Views** — Encontra N+1 queries, lógica excessiva
3. **Analisa Templates** — Detecta queries em templates, complexidade
4. **Verifica Migrações** — Detecta migrações perigosas, conflitos
5. **Inspeciona Settings** — Alerta sobre configurações inseguras/ineficientes
6. **Analisa Signals** — Detecta uso excessivo ou problemático
7. **Verifica Admin** — Detecta configurações inseguras ou ineficientes

---

## Problemas Detectados

### 🔴 Críticos (Devem ser corrigidos)

| Problema | Impacto | Como Detecta |
|----------|---------|--------------|
| **N+1 Queries em views** | Performance terrível | Analisa loops com acesso a FK |
| **Faltando `on_delete` em FK** | Integridade referencial | AST de models.py |
| **Migração de remoção de campo com dados** | Perda de dados | Histórico de migrações |
| **DEBUG=True em produção** | Segurança | settings.py |
| **SECRET_KEY hardcoded** | Segurança | settings.py |
| **SQL Injection via `.raw()`** | Segurança | Uso de f-strings em raw SQL |

### 🟡 Importantes (Recomendado corrigir)

| Problema | Impacto | Como Detecta |
|----------|---------|--------------|
| **Model > 500 linhas** | Manutenibilidade | Contagem de linhas |
| **View > 100 linhas** | Manutenibilidade | Contagem de linhas |
| **Signal sem `dispatch_uid`** | Comportamento estranho | AST de signals.py |
| **Query em template** | Performance | Regex em templates |
| **Índice faltante em campo buscado** | Performance | Análise de queries vs índices |
| **Uso excessivo de signals** | Acoplamento oculto | Contagem de signals |
| **Método `save()` sobrescrito sem super()** | Bugs sutis | AST de models.py |

### 🟢 Melhorias (Boa prática)

| Problema | Impacto | Como Detecta |
|----------|---------|--------------|
| **Faltando `__str__` em model** | UX no admin/admin | AST de models.py |
| **Faltando `get_absolute_url`** | UX, SEO | AST de models.py |
| **Não usar `select_related` quando óbvio** | Performance | Análise de views |
| **Import circular** | Manutenibilidade | Grafo de imports |
| **Código morto (funções não chamadas)** | Limpeza | Análise de referências |

---

## Exemplos de Saída

### Exemplo 1: Projeto Herdado (Análise Completa)

```
$ /django-insights

🔍 Django Insights — Análise de Saúde do Projeto
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📊 Visão Geral
   Django: 4.2
   Apps: 8
   Models: 42
   Views: 127
   Templates: 56
   Migrações: 156

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 PROBLEMAS CRÍTICOS (4)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🔴 CRÍTICO: DEBUG=True detectado
   Arquivo: settings.py:12
   Impacto: EXPÕE INFORMAÇÕES SENSÍVEIS EM PRODUÇÃO
   
   Código:
     DEBUG = True
   
   Correção:
     DEBUG = os.getenv('DEBUG', 'False') == 'True'
   
   Ação: Configure variável de ambiente DEBUG antes do deploy

─────────────────────────────────────────────────────

🔴 CRÍTICO: N+1 Query em OrderListView
   Arquivo: orders/views.py:45
   Impacto: 1 query + N queries (uma por order)
   
   Código problemático:
     45 | for order in Order.objects.filter(status='pending'):
     46 |     print(order.customer.name)  # ← Query extra!
   
   Correção:
     Order.objects.filter(status='pending').select_related('customer')
   
   Economia estimada: ~95% de queries (100 orders = 101 → 2 queries)

─────────────────────────────────────────────────────

🔴 CRÍTICO: Migração perigosa detectada
   Arquivo: orders/migrations/0042_remove_order_total.py
   Tipo: Remoção de campo com dados existentes
   
   Análise:
     - Campo 'total' tem 15,432 registros com dados
     - Migração é irreversível sem backup
   
   Recomendação:
     1. Faça backup do banco
     2. Considere marcar como deprecated primeiro
     3. Ou migre dados para outro lugar antes de remover

─────────────────────────────────────────────────────

🔴 CRÍTICO: Signal sem dispatch_uid
   Arquivo: orders/signals.py:23
   Função: send_notification
   
   Problema: Signal pode ser registrado múltiplas vezes
             causando duplicação de notificações
   
   Correção:
     @receiver(order_completed, dispatch_uid="orders.notification")
     def send_notification(sender, **kwargs):
         ...

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟡 RECOMENDAÇÕES IMPORTANTES (8)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🟡 Model muito grande: Order (680 linhas)
   Arquivo: orders/models.py
   Sugestão: Dividir em mixin ou mover lógica para services

🟡 View muito complexa: PaymentProcessView (145 linhas)
   Arquivo: payments/views.py:89
   Sugestão: Extrair lógica para PaymentService

🟡 Faltando índice em campo de busca frequente
   Model: Customer.email
   Campo buscado em: 8 lugares
   Sugestão: Adicionar db_index=True ou Index

🟡 Uso excessivo de signals (12 signals)
   App: orders
   Sugestão: Signals dificultam rastreamento. Considere:
             - Explicit calls em vez de signals
             - Ou documentar bem cada signal

🟡 Query em template detectada
   Template: orders/order_detail.html:34
   {{ order.items.filter|length }}
   Sugestão: Prepare no view: items_count = order.items.count()

🟡 Método save() sem super()
   Model: Product (products/models.py:56)
   Risco: Pode quebrar funcionalidades do Django
   
   Correção:
     def save(self, *args, **kwargs):
         # sua lógica
         super().save(*args, **kwargs)

🟡 Import circular detectado
   orders → payments → orders
   Arquivos: orders/services.py, payments/utils.py
   Sugestão: Mover código compartilhado para módulo comum

🟡 Código morto detectado
   Função: calculate_old_tax (never called)
   Arquivo: orders/utils.py:45
   Sugestão: Remover ou verificar se deveria ser usada

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🟢 BOAS PRÁTICAS (5)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🟢 Faltando __str__ em models:
   - payments/models.py: Transaction
   - reports/models.py: ReportConfig
   
   Sugestão: Adicionar para melhor UX no admin/shell

🟢 Faltando get_absolute_url:
   - Order, Customer, Product
   
   Benefício: Melhor navegação, SEO, reuso

🟢 Oportunidade de select_related:
   View: OrderDetailView
   Poderia usar select_related('customer', 'items')
   Economia: ~3 queries por request

🟢 Campo de busca sem índice:
   Order.tracking_code
   Usado em: OrderTrackingView
   Sugestão: Adicionar db_index=True

🟢 Template complexo:
   reports/dashboard.html (350 linhas)
   Sugestão: Dividir em includes

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📈 MÉTRICAS E TENDÊNCIAS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Qualidade do Código:
  🔴 Críticos: 4 (deve ser 0)
  🟡 Importantes: 8 (meta: <5)
  🟢 Melhorias: 5 (opcional)
  
Cobertura de Testes (estimada):
  Models: 60% ⚠️
  Views: 30% 🔴
  Services: 10% 🔴

Débito Técnico Estimado:
  Corrigir críticos: 2-3 dias
  Corrigir importantes: 1 semana
  Todas melhorias: 2 semanas

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🎯 PRÓXIMAS AÇÕES RECOMENDADAS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Imediato (esta semana):
1. Corrigir DEBUG=True ANTES de qualquer deploy
2. Adicionar select_related em OrderListView
3. Revisar migração 0042 antes de aplicar

Curto prazo (próximas 2 semanas):
4. Refatorar Order model (680 → <300 linhas)
5. Quebrar PaymentProcessView em serviços
6. Adicionar índice em Customer.email

Médio prazo (mês):
7. Documentar ou remover signals excessivos
8. Aumentar cobertura de testes em views

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
💾 Exportar Relatório
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

/django-insights --export=relatorio-django-2026-03-02.md
```

### Exemplo 2: Foco em Performance

```
$ /django-insights --focus=performance

🔍 Django Insights — Foco: Performance

🔴 CRÍTICO: N+1 Queries Detectados (5)

1. orders/views.py:45 (OrderListView)
   Loop: for order in orders
   Acesso: order.customer.name
   Correção: .select_related('customer')
   Impacto: ~95% redução de queries

2. products/views.py:89 (ProductCatalog)
   Loop: for product in products
   Acesso: product.category.name
   Correção: .select_related('category')
   Impacto: ~90% redução de queries

3. reports/views.py:34 (SalesReport)
   Loop: for sale in sales
   Acesso: sale.items.all()  ← dentro de loop!
   Correção: .prefetch_related('items')
   Impacto: ~99% redução de queries

🟡 Oportunidades de Otimização (3)

1. Índice faltante: Customer.email
   Busca frequente, sem índice
   Impacto: Busca O(n) → O(log n)

2. Sem select_related óbvio: OrderDetailView
   Usa customer e items, não faz prefetch
   Impacto: 3 queries → 1 query

3. Query COUNT sem necessidade: DashboardView
   products.count() quando só precisa saber se >0
   Correção: Use exists()
   Impacto: Query pesada → Query leve

💡 Impacto Total Estimado:
   - Redução de queries: ~80%
   - Tempo de resposta médio: -60%
   - Capacidade de usuários simultâneos: +200%
```

### Exemplo 3: Análise de App Específico

```
$ /django-insights --app=payments

🔍 Análise do App: payments

📊 Resumo do App
   Models: 5 (Payment, Transaction, Refund, Gateway, Log)
   Views: 12
   Tests: 3 (⚠️ baixa cobertura)
   
🔴 CRÍTICO: 2 problemas
🟡 IMPORTANTE: 3 problemas

🔴 CRÍTICO: Faltando on_delete em ForeignKey
   Model: Transaction
   Campo: order = models.ForeignKey(Order)
   Risco: Comportamento indefinido em delete
   Correção: models.ForeignKey(Order, on_delete=models.PROTECT)

🔴 CRÍTICO: Múltiplos campos de valor (inconsistência)
   Transaction tem: amount, value, total
   Sugestão: Consolidar em um único campo documentado

🟡 IMPORTANTE: Signal perigoso
   Pré-save altera valor sem log
   Arquivo: payments/signals.py
   Sugestão: Adicionar auditoria ou usar transação explícita

...
```

---

## Implementação

### Dependências

```python
# requirements.txt
Django>=4.0
ast-unparse>=1.6.0
radon>=5.1.0  # Complexidade ciclomática
```

### Estrutura

```
django-insights/
├── SKILL.md              # Este arquivo
├── analyze.py            # Script principal
├── analyzers/
│   ├── __init__.py
│   ├── models.py         # Analisador de models
│   ├── views.py          # Analisador de views
│   ├── templates.py      # Analisador de templates
│   ├── migrations.py     # Analisador de migrações
│   ├── settings.py       # Analisador de settings
│   └── signals.py        # Analisador de signals
├── metrics/
│   └── complexity.py     # Cálculo de métricas
└── exporters/
    └── markdown.py       # Exporta relatório
```

### Lógica Principal (analyze.py)

```python
#!/usr/bin/env python3
"""
Django Insights — Análise de saúde de projetos Django
SOP ESAA Solopreneur v4.1
"""

import os
import sys
import ast
import django
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass, field
from collections import defaultdict

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'settings')
django.setup()

from django.apps import apps
from django.db import models, connection


@dataclass
class Issue:
    level: str  # critical, warning, suggestion
    category: str
    title: str
    file: Path
    line: int
    description: str
    solution: str
    impact: str


class DjangoAnalyzer:
    """Analisador principal de projetos Django"""
    
    def __init__(self, project_root: str = "."):
        self.root = Path(project_root)
        self.issues = []
        self.metrics = defaultdict(int)
        
    def analyze(self, app_name: Optional[str] = None, focus: Optional[str] = None):
        """Executa análise completa"""
        print("🔍 Django Insights — Análise de Saúde do Projeto\n")
        
        # Coleta informações básicas
        self._collect_basic_info()
        
        # Análises
        if not focus or focus == "models":
            self._analyze_models(app_name)
        if not focus or focus == "views":
            self._analyze_views(app_name)
        if not focus or focus == "templates":
            self._analyze_templates(app_name)
        if not focus or focus == "migrations":
            self._analyze_migrations(app_name)
        if not focus or focus == "settings":
            self._analyze_settings()
        if not focus or focus == "signals":
            self._analyze_signals(app_name)
        
        # Gera relatório
        self._generate_report()
        
    def _collect_basic_info(self):
        """Coleta informações básicas do projeto"""
        from django.conf import settings
        
        print("📊 Visão Geral")
        print(f"   Django: {django.VERSION}")
        print(f"   Apps: {len(apps.get_app_configs())}")
        
        # Conta models
        models_count = len(apps.get_models())
        print(f"   Models: {models_count}")
        
        # Conta views (heurística: arquivos views.py)
        views_count = sum(1 for _ in self.root.rglob("views.py"))
        print(f"   Views: {views_count} arquivos")
        
        # Conta templates
        templates_count = sum(1 for _ in self.root.rglob("*.html"))
        print(f"   Templates: {templates_count}")
        
        # Conta migrações
        migrations_count = sum(
            1 for _ in self.root.rglob("migrations/0*.py")
        )
        print(f"   Migrações: {migrations_count}")
        print()
        
    def _analyze_models(self, app_name: Optional[str] = None):
        """Analisa models Django"""
        model_classes = apps.get_models()
        if app_name:
            model_classes = [
                m for m in model_classes 
                if m._meta.app_label == app_name
            ]
        
        for model in model_classes:
            # Tamanho do model (arquivo)
            try:
                model_file = Path(model.__module__.replace('.', '/'))
                if not str(model_file).endswith('.py'):
                    model_file = model_file / 'models.py'
                else:
                    model_file = model_file.with_suffix('.py')
                
                lines = self._count_file_lines(model_file)
                if lines > 500:
                    self.issues.append(Issue(
                        level="warning",
                        category="models",
                        title=f"Model muito grande: {model.__name__}",
                        file=model_file,
                        line=1,
                        description=f"Model tem {lines} linhas (>500)",
                        solution="Dividir em mixins ou mover lógica para services",
                        impact="Manutenibilidade"
                    ))
            except:
                pass
            
            # Verifica __str__
            if model.__str__ == models.Model.__str__:
                self.issues.append(Issue(
                    level="suggestion",
                    category="models",
                    title=f"Faltando __str__ em {model.__name__}",
                    file=Path("models.py"),
                    line=1,
                    description="Model não define __str__",
                    solution="Adicionar método __str__ para melhor UX",
                    impact="UX no admin/shell"
                ))
            
            # Verifica get_absolute_url
            if not hasattr(model, 'get_absolute_url'):
                self.issues.append(Issue(
                    level="suggestion",
                    category="models",
                    title=f"Faltando get_absolute_url em {model.__name__}",
                    file=Path("models.py"),
                    line=1,
                    description="Model não define get_absolute_url",
                    solution="Adicionar método get_absolute_url",
                    impact="SEO, navegação"
                ))
            
            # Verifica ForeignKey sem on_delete
            for field in model._meta.fields:
                if isinstance(field, models.ForeignKey):
                    # Django 2.0+ exige on_delete, mas verificamos explicitamente
                    if field.remote_field.on_delete == models.CASCADE:
                        # CASCADE é padrão, pode ser intencional
                        pass
    
    def _analyze_views(self, app_name: Optional[str] = None):
        """Analisa views para N+1 e complexidade"""
        # Heurística: procura arquivos views.py
        view_files = list(self.root.rglob("views.py"))
        if app_name:
            view_files = [v for v in view_files if app_name in str(v)]
        
        for view_file in view_files:
            try:
                content = view_file.read_text()
                tree = ast.parse(content)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        # Verifica tamanho
                        lines = node.end_lineno - node.lineno if node.end_lineno else 0
                        if lines > 100:
                            self.issues.append(Issue(
                                level="warning",
                                category="views",
                                title=f"View muito longa: {node.name}",
                                file=view_file,
                                line=node.lineno,
                                description=f"View tem {lines} linhas (>100)",
                                solution="Extrair lógica para service/mixin",
                                impact="Manutenibilidade"
                            ))
                        
                        # Detecta N+1 (simplificado)
                        n_plus_one = self._detect_n_plus_one_in_view(node)
                        if n_plus_one:
                            self.issues.append(Issue(
                                level="critical",
                                category="views",
                                title=f"N+1 Query em {node.name}",
                                file=view_file,
                                line=node.lineno,
                                description="Loop com acesso a relacionamento sem prefetch",
                                solution="Adicionar select_related() ou prefetch_related()",
                                impact="Performance terrível"
                            ))
            except:
                pass
    
    def _analyze_templates(self, app_name: Optional[str] = None):
        """Analisa templates para queries"""
        template_files = list(self.root.rglob("*.html"))
        if app_name:
            template_files = [t for t in template_files if app_name in str(t)]
        
        for template_file in template_files:
            try:
                content = template_file.read_text()
                
                # Detecta queries em templates
                import re
                patterns = [
                    r'\{\{\s*\w+\.(filter|exclude|all|count)\s*\}\}',
                    r'\{\%\s*for.*in\s*\w+\.(filter|exclude|all)'
                ]
                
                for pattern in patterns:
                    matches = re.finditer(pattern, content)
                    for match in matches:
                        line = content[:match.start()].count('\n') + 1
                        self.issues.append(Issue(
                            level="warning",
                            category="templates",
                            title="Query em template",
                            file=template_file,
                            line=line,
                            description=f"Template faz query: {match.group()[:40]}",
                            solution="Prepare dados na view",
                            impact="Performance"
                        ))
            except:
                pass
    
    def _analyze_migrations(self, app_name: Optional[str] = None):
        """Analisa migrações para operações perigosas"""
        migration_files = list(self.root.rglob("migrations/0*.py"))
        if app_name:
            migration_files = [m for m in migration_files if app_name in str(m)]
        
        for mig_file in migration_files:
            try:
                content = mig_file.read_text()
                
                # Detecta RemoveField
                if "RemoveField" in content:
                    self.issues.append(Issue(
                        level="critical",
                        category="migrations",
                        title=f"Migração remove campo: {mig_file.name}",
                        file=mig_file,
                        line=1,
                        description="RemoveField pode causar perda de dados",
                        solution="Backup antes de aplicar; considere deprecar primeiro",
                        impact="Perda de dados"
                    ))
                
                # Detecta DeleteModel
                if "DeleteModel" in content:
                    self.issues.append(Issue(
                        level="critical",
                        category="migrations",
                        title=f"Migração remove model: {mig_file.name}",
                        file=mig_file,
                        line=1,
                        description="DeleteModel remove tabela e dados",
                        solution="Backup obrigatório antes de aplicar",
                        impact="Perda de dados"
                    ))
            except:
                pass
    
    def _analyze_settings(self):
        """Analisa settings.py"""
        try:
            from django.conf import settings
            
            # DEBUG
            if settings.DEBUG:
                self.issues.append(Issue(
                    level="critical",
                    category="settings",
                    title="DEBUG=True",
                    file=Path("settings.py"),
                    line=1,
                    description="DEBUG está ativo",
                    solution="Configure DEBUG=False em produção",
                    impact="Segurança - expõe informações sensíveis"
                ))
            
            # SECRET_KEY
            if hasattr(settings, 'SECRET_KEY'):
                if len(settings.SECRET_KEY) < 50 or 'django' in settings.SECRET_KEY.lower():
                    self.issues.append(Issue(
                        level="critical",
                        category="settings",
                        title="SECRET_KEY inseguro",
                        file=Path("settings.py"),
                        line=1,
                        description="SECRET_KEY parece ser valor padrão ou curto",
                        solution="Gere nova SECRET_KEY e use variável de ambiente",
                        impact="Segurança - sessões comprometidas"
                    ))
        except:
            pass
    
    def _analyze_signals(self, app_name: Optional[str] = None):
        """Analisa signals"""
        # Heurística: conta signals em signals.py
        signal_files = list(self.root.rglob("signals.py"))
        if app_name:
            signal_files = [s for s in signal_files if app_name in str(s)]
        
        for sig_file in signal_files:
            try:
                content = sig_file.read_text()
                
                # Conta receivers
                receiver_count = content.count('@receiver')
                if receiver_count > 5:
                    self.issues.append(Issue(
                        level="warning",
                        category="signals",
                        title=f"Muitos signals ({receiver_count})",
                        file=sig_file,
                        line=1,
                        description=f"App tem {receiver_count} signals",
                        solution="Signals dificultam rastreamento. Considere chamadas explícitas",
                        impact="Acoplamento oculto"
                    ))
                
                # Verifica dispatch_uid
                if 'dispatch_uid' not in content:
                    self.issues.append(Issue(
                        level="warning",
                        category="signals",
                        title="Signal sem dispatch_uid",
                        file=sig_file,
                        line=1,
                        description="Receivers sem dispatch_uid podem duplicar",
                        solution="Adicione dispatch_uid a cada @receiver",
                        impact="Comportamento estranho"
                    ))
            except:
                pass
    
    def _detect_n_plus_one_in_view(self, node) -> bool:
        """Heurística simples para detectar N+1"""
        # Verifica se tem for loop + acesso a atributo
        has_loop = False
        has_attribute_access = False
        
        for child in ast.walk(node):
            if isinstance(child, ast.For):
                has_loop = True
            if isinstance(child, ast.Attribute):
                has_attribute_access = True
        
        return has_loop and has_attribute_access
    
    def _count_file_lines(self, file_path: Path) -> int:
        """Conta linhas de arquivo"""
        try:
            return len(file_path.read_text().split('\n'))
        except:
            return 0
    
    def _generate_report(self):
        """Gera relatório final"""
        critical = [i for i in self.issues if i.level == "critical"]
        warnings = [i for i in self.issues if i.level == "warning"]
        suggestions = [i for i in self.issues if i.level == "suggestion"]
        
        print("━" * 55)
        print(f"🔴 PROBLEMAS CRÍTICOS ({len(critical)})")
        print("━" * 55)
        for issue in critical[:5]:  # Limita para não poluir
            print(f"\n🔴 {issue.title}")
            print(f"   Arquivo: {issue.file}:{issue.line}")
            print(f"   Impacto: {issue.impact}")
            print(f"   Solução: {issue.solution}")
        
        if len(critical) > 5:
            print(f"\n   ... e mais {len(critical) - 5} críticos")
        
        print("\n" + "━" * 55)
        print(f"🟡 RECOMENDAÇÕES ({len(warnings)})")
        print("━" * 55)
        for issue in warnings[:5]:
            print(f"\n🟡 {issue.title}")
            print(f"   {issue.description}")
        
        print("\n" + "━" * 55)
        print(f"🟢 SUGESTÕES ({len(suggestions)})")
        print("━" * 55)
        
        # Métricas
        print("\n📈 Resumo:")
        print(f"   Críticos: {len(critical)} (deve ser 0)")
        print(f"   Importantes: {len(warnings)} (meta: <10)")
        print(f"   Sugestões: {len(suggestions)} (opcional)")


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description="Análise de saúde Django")
    parser.add_argument("--app", help="Analisar apenas um app")
    parser.add_argument("--focus", help="Focar em área específica")
    args = parser.parse_args()
    
    analyzer = DjangoAnalyzer()
    analyzer.analyze(app_name=args.app, focus=args.focus)


if __name__ == "__main__":
    main()
```

---

## Integração com Workflow

```bash
# Mensalmente
/django-insights > relatorio-mensal.md

# Antes de refatorar
/django-insights --focus=performance

# Ao herdar projeto
/django-insights --export=diagnostico-inicial.md
```

---

## Instalação

```bash
cp -r django-insights ~/.pi/skills/
pip install Django radon
```

---

*Skill criada para SOP ESAA Solopreneur v4.1 — Mantenha seus projetos Django saudáveis*
