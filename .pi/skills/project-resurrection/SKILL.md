---
name: project-resurrection
description: Protocolo para retomada rápida de projetos após pausas longas.
---

# Skill: project-resurrection

**Propósito:** Guiar a retomada de um projeto após pausa longa, seguindo o Project Resurrection Protocol do SOP ESAA v4.1

**Quando usar:**

- Ao voltar a um projeto após 2+ semanas sem trabalhar nele
- Ao alternar entre múltiplos projetos
- Quando não se lembra exatamente onde parou
- Ao retomar um projeto "esquecido" do ano passado

**Comando:**

```bash
/project-resurrection [--warmup]
```

Opção `--warmup`: Sugere um change QUICK de aquecimento antes do trabalho real.

---

## O que a Skill Faz

1. **Reconhecimento de Território** — Coleta estado atual do projeto
2. **Avaliação de Changes** — Verifica se há trabalho em andamento
3. **Sincronização de Contexto** — Verifica saúde do projeto
4. **Preparação** — Sugere próximo passo ou warm-up

---

## Fluxo de Execução

```
Usuário: /project-resurrection

Pi:
  ├─ 1. Verifica última atividade (git log)
  ├─ 2. Lê PROJECT_CONTEXT.md (se existe)
  ├─ 3. Lista changes ativos (openspec/changes/active/)
  ├─ 4. Verifica último slice concluído (tasks.md)
  ├─ 5. Roda verificações de saúde (test, lint)
  └─ 6. Gera relatório + recomendações + prompt de reentrada
```

---

## Saída Esperada

### Exemplo 1: Projeto com Change Ativo (Retomada Simples)

```
$ /project-resurrection

🔍 PROJECT RESURRECTION PROTOCOL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📅 Informações Temporais
   Última atividade: 2026-02-15 (15 dias atrás)
   Último commit: "feat: add payment webhook handler"
   Branch atual: main

📄 PROJECT_CONTEXT.md
   ✅ Encontrado (atualizado em 2026-02-10)
   Resumo: Sistema de pagamentos com integração Stripe

📁 Changes Ativos
   🟡 1 change em andamento: add-user-dashboard
      └─ Progresso: 3 de 5 slices completos
      └─ Último slice: 3.2 (Criar template dashboard.html)
      └─ Próximo slice: 3.3 (Adicionar testes de integração)

🔍 Estado do Repositório
   ⚠️  3 arquivos não commitados:
       - static/css/dashboard.css (novo)
       - templates/dashboard.html (modificado)
       - tests/test_dashboard.py (novo)
   💡 Sugestão: Verificar se pertencem ao slice 3.2

🧪 Verificação de Saúde
   ✅ ruff check . (passando)
   ✅ python manage.py test (47/47 passando)
   ⚠️  python manage.py check (1 warning: DEBUG=True)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 RECOMENDAÇÕES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Opção A — Retomar Change Ativo (Recomendado)
─────────────────────────────────────────────────
Você tem um change em andamento (add-user-dashboard) com
2 slices pendentes. Provavelmente é aqui que deve continuar.

Próximo passo: Slice 3.3 — Adicionar testes de integração

Prompt de reentrada pronto:
```

Read AGENTS.md and PROJECT_CONTEXT.md first.
Change ID: add-user-dashboard

Contexto: Estou retomando este projeto após 15 dias.
Objetivo: Implementar slice 3.3 (testes de integração do dashboard).

Por favor:

1. Leia tasks.md para confirmar estado
2. Verifique arquivos não commitados (css, html, test)
3. Implemente APENAS o slice 3.3
4. Siga TDD: RED → GREEN → REFACTOR → VERIFY
5. Rode: ruff check . && python manage.py test
6. Commit com mensagem descritiva
7. Marque task como concluída
8. PARE e aguarde confirmação

```

Opção B — Novo Change (se abandonou o anterior)
─────────────────────────────────────────────────
Se o add-user-dashboard não é mais relevante:
/esaa-archive-change add-user-dashboard --reason="abandoned"
Depois: /opsx:new [novo-change]

Opção C — Warm-up (se projeto está "frio")
─────────────────────────────────────────────────
Se sentir necessidade de reconhecimento:
/opsx:new warmup-update-deps
# Atualizar dependências, rodar migrations, etc.
```

### Exemplo 2: Projeto Sem Changes Ativos (Reinício)

```
$ /project-resurrection

🔍 PROJECT RESURRECTION PROTOCOL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📅 Informações Temporais
   Última atividade: 2025-11-20 (102 dias atrás) ⚠️
   Último commit: "fix: correct email template"
   Branch atual: main

📄 PROJECT_CONTEXT.md
   ✅ Encontrado (atualizado em 2025-11-15)
   ⚠️  Conteúdo pode estar desatualizado (102 dias)

📁 Changes Ativos
   ✅ Nenhum change em andamento
   📊 Changes arquivados: 23 (histórico preservado)

🔍 Estado do Repositório
   ✅ Working directory limpo
   📦 requirements.txt modificado (dependências desatualizadas?)

🧪 Verificação de Saúde
   ⚠️  ruff check . (12 erros — dependências quebradas?)
   ❌  python manage.py test (falhando: ImportError)
   💡 Problema: Biblioteca 'stripe' não encontrada

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 RECOMENDAÇÕES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️  Projeto necessita de manutenção antes de retomar!

Passo 1 — Warm-up Obrigatório
─────────────────────────────────────────────────
Criar change QUICK para recuperar ambiente:

/opsx:new warmup-project-recovery

Tasks sugeridas:
- [ ] 1.1 Atualizar requirements.txt (pip install -r requirements.txt)
- [ ] 1.2 Verificar migrações pendentes
- [ ] 1.3 Corrigir erros de lint (ruff check .)
- [ ] 1.4 Garantir que tests passam
- [ ] 1.5 Atualizar PROJECT_CONTEXT.md se necessário

Passo 2 — Avaliar Próximo Trabalho
─────────────────────────────────────────────────
Após warm-up, avaliar:
1. Revisar últimos changes arquivados (qual área do sistema?)
2. Verificar se há demandas pendentes (notion/todo?)
3. Criar novo change para próxima feature

Passo 3 — Atualizar Documentação
─────────────────────────────────────────────────
Após 102 dias, considere:
- Atualizar PROJECT_CONTEXT.md
- Revisar AGENTS.md (ainda reflete o stack?)
- Verificar ADRs antigas (alguma deprecada?)
```

### Exemplo 3: Projeto sem Contexto (Primeira Vez)

```
$ /project-resurrection

🔍 PROJECT RESURRECTION PROTOCOL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

📅 Informações Temporais
   ⚠️  Não foi possível determinar última atividade
   💡 Dica: Inicializar git se ainda não foi feito

📄 PROJECT_CONTEXT.md
   ❌ Não encontrado
   💡 Sugestão: Criar para facilitar futuras retomadas

📁 Changes Ativos
   ❌ Diretório openspec/changes/ não encontrado
   💡 Sugestão: Rodar 'openspec init' para inicializar

🔍 Estado do Repositório
   📁 Estrutura detectada: Django project
   📁 Apps encontrados: core, users, payments
   📄 requirements.txt: Django 4.2, PostgreSQL, Celery

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 RECOMENDAÇÕES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Setup Inicial Necessário
─────────────────────────────────────────────────

1. Inicializar OpenSpec:
   openspec init

2. Gerar AGENTS.md:
   /esaa-generate-agents
   (ou criar manualmente seguindo template)

3. Criar PROJECT_CONTEXT.md:
   /esaa-generate-context
   (ou criar manualmente)

4. Criar primeiro change QUICK:
   /opsx:new setup-project-docs

Estimativa: 15-20 minutos
Após isso, o projeto estará pronto para workflow ESAA.
```

---

## Implementação

### Dependências

```python
# requirements.txt para a skill
GitPython>=3.1.0
python-dateutil>=2.8.0
pyyaml>=6.0
```

### Estrutura

```
project-resurrection/
├── SKILL.md
├── resurrect.py          # Script principal
├── health_check.py       # Verificações de saúde
└── utils.py              # Funções auxiliares
```

### Lógica Principal (resurrect.py)

```python
#!/usr/bin/env python3
"""
Project Resurrection Protocol
SOP ESAA Solopreneur v4.1 - Seção 10
"""

import os
import sys
from pathlib import Path
from datetime import datetime, timedelta
from dateutil import parser
import git

class ProjectResurrector:
    def __init__(self, project_root="."):
        self.root = Path(project_root)
        self.report = {}
        
    def analyze(self):
        """Executa análise completa"""
        self._temporal_info()
        self._project_context()
        self._active_changes()
        self._repository_state()
        self._health_check()
        return self.report
    
    def _temporal_info(self):
        """Passo 1: Informações temporais"""
        try:
            repo = git.Repo(self.root)
            last_commit = repo.head.commit
            last_date = datetime.fromtimestamp(last_commit.committed_date)
            days_ago = (datetime.now() - last_date).days
            
            self.report["temporal"] = {
                "last_activity": last_date.isoformat(),
                "days_ago": days_ago,
                "last_commit_msg": last_commit.message.strip(),
                "current_branch": repo.active_branch.name,
                "is_fresh": days_ago < 7,
                "is_cold": days_ago > 30,
                "is_frozen": days_ago > 90
            }
        except git.InvalidGitRepositoryError:
            self.report["temporal"] = {
                "error": "Repositório git não encontrado"
            }
    
    def _project_context(self):
        """Passo 2: Ler PROJECT_CONTEXT.md"""
        context_file = self.root / "PROJECT_CONTEXT.md"
        
        if context_file.exists():
            content = context_file.read_text()
            mtime = datetime.fromtimestamp(context_file.stat().st_mtime)
            
            # Extrair Purpose (primeiros parágrafos)
            purpose = ""
            if "## Purpose" in content:
                start = content.find("## Purpose")
                end = content.find("##", start + 1)
                purpose = content[start:end].strip()
            
            self.report["context"] = {
                "exists": True,
                "updated_at": mtime.isoformat(),
                "purpose_preview": purpose[:200] + "..." if len(purpose) > 200 else purpose,
                "may_be_stale": (datetime.now() - mtime).days > 30
            }
        else:
            self.report["context"] = {"exists": False}
    
    def _active_changes(self):
        """Passo 3: Avaliar changes ativos"""
        changes_dir = self.root / "openspec" / "changes" / "active"
        
        if not changes_dir.exists():
            self.report["active_changes"] = {
                "exists": False,
                "count": 0
            }
            return
        
        changes = []
        for change_dir in changes_dir.iterdir():
            if change_dir.is_dir():
                change_info = self._analyze_change(change_dir)
                changes.append(change_info)
        
        # Ordenar por última modificação
        changes.sort(key=lambda x: x["last_modified"], reverse=True)
        
        self.report["active_changes"] = {
            "exists": True,
            "count": len(changes),
            "changes": changes
        }
    
    def _analyze_change(self, change_dir):
        """Analisa um change específico"""
        tasks_file = change_dir / "tasks.md"
        proposal_file = change_dir / "proposal.md"
        
        info = {
            "id": change_dir.name,
            "last_modified": datetime.fromtimestamp(change_dir.stat().st_mtime),
            "has_proposal": proposal_file.exists(),
            "has_tasks": tasks_file.exists()
        }
        
        if tasks_file.exists():
            tasks_content = tasks_file.read_text()
            # Contar tasks e completados
            total = tasks_content.count("- [ ]") + tasks_content.count("- [x]")
            completed = tasks_content.count("- [x]")
            
            info["tasks"] = {
                "total": total,
                "completed": completed,
                "progress": f"{completed}/{total}"
            }
            
            # Identificar último slice concluído e próximo
            lines = tasks_content.split("\n")
            last_completed = None
            next_pending = None
            
            for i, line in enumerate(lines):
                if "- [x]" in line:
                    last_completed = line.strip()
                elif "- [ ]" in line and next_pending is None:
                    next_pending = line.strip()
            
            info["last_completed_slice"] = last_completed
            info["next_pending_slice"] = next_pending
        
        return info
    
    def _repository_state(self):
        """Passo 4: Estado do repositório"""
        try:
            repo = git.Repo(self.root)
            
            # Verificar arquivos não commitados
            changed = [item.a_path for item in repo.index.diff(None)]
            untracked = repo.untracked_files
            
            self.report["repository"] = {
                "is_clean": len(changed) == 0 and len(untracked) == 0,
                "changed_files": changed[:10],  # Limitar
                "untracked_files": untracked[:10],
                "total_uncommitted": len(changed) + len(untracked)
            }
        except:
            self.report["repository"] = {"error": "Não foi possível analisar"}
    
    def _health_check(self):
        """Passo 5: Verificações de saúde"""
        checks = {}
        
        # Verificar se é projeto Django
        is_django = (self.root / "manage.py").exists()
        checks["is_django"] = is_django
        
        # Tentar rodar ruff (se disponível)
        import subprocess
        try:
            result = subprocess.run(
                ["ruff", "check", "."],
                capture_output=True,
                text=True,
                timeout=30
            )
            checks["ruff"] = {
                "available": True,
                "passed": result.returncode == 0,
                "summary": "passing" if result.returncode == 0 else f"{result.stdout.count(chr(10))} issues"
            }
        except:
            checks["ruff"] = {"available": False}
        
        # Tentar rodar Django tests (se Django)
        if is_django:
            try:
                result = subprocess.run(
                    ["python", "manage.py", "test", "--verbosity=0"],
                    capture_output=True,
                    text=True,
                    timeout=60
                )
                checks["django_tests"] = {
                    "available": True,
                    "passed": result.returncode == 0,
                    "summary": "passing" if result.returncode == 0 else "failing"
                }
            except Exception as e:
                checks["django_tests"] = {
                    "available": True,
                    "passed": False,
                    "summary": f"error: {str(e)[:50]}"
                }
        
        self.report["health"] = checks
    
    def generate_prompt(self, change_id=None):
        """Gera prompt de reentrada"""
        if change_id is None and self.report["active_changes"]["count"] > 0:
            change_id = self.report["active_changes"]["changes"][0]["id"]
        
        days = self.report["temporal"].get("days_ago", "?")
        
        prompt = f"""Read AGENTS.md and PROJECT_CONTEXT.md first.
Change ID: {change_id}

Contexto: Estou retomando este projeto após {days} dias.
"""
        
        if change_id:
            next_slice = self.report["active_changes"]["changes"][0].get("next_pending_slice", "")
            if next_slice:
                prompt += f"Objetivo: Implementar {next_slice}\n"
            
            prompt += """
Por favor:
1. Leia tasks.md para confirmar estado
2. Verifique arquivos não commitados (se houver)
3. Implemente APENAS o próximo slice
4. Siga TDD: RED → GREEN → REFACTOR → VERIFY
5. Rode os comandos de validação do AGENTS.md
6. Commit com mensagem descritiva
7. Marque task como concluída em tasks.md
8. PARE e aguarde confirmação

Não prossiga para o próximo slice sem minha autorização.
"""
        
        return prompt

def print_report(report, warmup=False):
    """Imprime relatório formatado"""
    print("\n" + "━"*55)
    print("🔍 PROJECT RESURRECTION PROTOCOL")
    print("━"*55 + "\n")
    
    # Temporal
    temporal = report.get("temporal", {})
    print("📅 Informações Temporais")
    if "error" in temporal:
        print(f"   ⚠️  {temporal['error']}")
    else:
        days = temporal.get("days_ago", 0)
        emoji = "✅" if days < 7 else "🟡" if days < 30 else "🔴"
        print(f"   {emoji} Última atividade: {days} dias atrás")
        print(f"   📝 Último commit: {temporal.get('last_commit_msg', 'N/A')[:50]}")
        print(f"   🌿 Branch: {temporal.get('current_branch', 'N/A')}")
    print()
    
    # Context
    context = report.get("context", {})
    print("📄 PROJECT_CONTEXT.md")
    if context.get("exists"):
        stale = "⚠️  (pode estar desatualizado)" if context.get("may_be_stale") else "✅"
        print(f"   {stale} Encontrado")
        if context.get("purpose_preview"):
            print(f"   📝 {context['purpose_preview'][:100]}...")
    else:
        print("   ❌ Não encontrado")
        print("   💡 Sugestão: Criar para facilitar retomadas")
    print()
    
    # Active Changes
    active = report.get("active_changes", {})
    print("📁 Changes Ativos")
    if not active.get("exists"):
        print("   ❌ Diretório openspec/changes/ não encontrado")
        print("   💡 Sugestão: Rodar 'openspec init'")
    elif active["count"] == 0:
        print("   ✅ Nenhum change em andamento")
        print("   📊 Projeto limpo, pronto para novo change")
    else:
        print(f"   🟡 {active['count']} change(s) em andamento")
        for change in active["changes"][:3]:  # Mostrar até 3
            progress = change.get("tasks", {}).get("progress", "?/?")
            print(f"      • {change['id']}: {progress} slices")
            if change.get("next_pending_slice"):
                print(f"        └─ Próximo: {change['next_pending_slice'][:60]}...")
    print()
    
    # Repository
    repo = report.get("repository", {})
    print("🔍 Estado do Repositório")
    if repo.get("is_clean"):
        print("   ✅ Working directory limpo")
    else:
        uncommitted = repo.get("total_uncommitted", 0)
        print(f"   ⚠️  {uncommitted} arquivo(s) não commitado(s)")
        for f in repo.get("changed_files", [])[:3]:
            print(f"      • {f}")
    print()
    
    # Health
    health = report.get("health", {})
    print("🧪 Verificação de Saúde")
    ruff = health.get("ruff", {})
    if ruff.get("available"):
        status = "✅" if ruff["passed"] else "❌"
        print(f"   {status} ruff check . ({ruff.get('summary', '')})")
    else:
        print("   ⚪ ruff não disponível")
    
    if health.get("is_django"):
        tests = health.get("django_tests", {})
        if tests.get("available"):
            status = "✅" if tests["passed"] else "❌"
            print(f"   {status} django tests ({tests.get('summary', '')})")
    print()
    
    # Recomendações
    print("━"*55)
    print("📋 RECOMENDAÇÕES")
    print("━"*55 + "\n")
    
    # Lógica de recomendação
    days = temporal.get("days_ago", 0)
    has_active = active.get("count", 0) > 0
    is_healthy = ruff.get("passed", True) and health.get("django_tests", {}).get("passed", True)
    
    if days > 90 and not is_healthy:
        print("⚠️  ALERTA: Projeto necessita de manutenção!")
        print("\nSugestão: Criar change QUICK de warm-up:\n")
        print("/opsx:new warmup-project-recovery\n")
        print("Tasks sugeridas:")
        print("- [ ] 1.1 Atualizar dependências")
        print("- [ ] 1.2 Verificar migrações pendentes")
        print("- [ ] 1.3 Corrigir erros de lint")
        print("- [ ] 1.4 Garantir que tests passam")
        print("- [ ] 1.5 Atualizar docs se necessário")
        
    elif has_active:
        change = active["changes"][0]
        print("✅ Recomendação: Retomar change ativo\n")
        print(f"Change: {change['id']}")
        print(f"Progresso: {change.get('tasks', {}).get('progress', '?')}")
        
        if change.get("next_pending_slice"):
            print(f"\nPróximo slice: {change['next_pending_slice'][:70]}")
        
        print("\n" + "─"*55)
        print("📝 Prompt de reentrada pronto:")
        print("─"*55)
        print(resurrector.generate_prompt(change['id']))
        
    else:
        print("✅ Projeto limpo e saudável!")
        print("\nSugestão: Criar novo change para próxima feature")
        print("/opsx:new [nome-da-feature]")
    
    print("\n" + "━"*55 + "\n")

if __name__ == "__main__":
    warmup = "--warmup" in sys.argv
    
    resurrector = ProjectResurrector()
    report = resurrector.analyze()
    print_report(report, warmup)
```

---

## Integração com Workflow ESAA

Esta skill é o **ponto de entrada** ao alternar entre projetos:

```
# Fluxo de trabalho com múltiplos projetos

Projeto A (trabalho há 2 semanas)
   ↓
(cd projeto-B)
/project-resurrection
   ↓
[Skill analisa e sugere retomada]
   ↓
[Usa prompt de reentrada fornecido]
   ↓
Trabalha em Projeto B
   ↓
(cd projeto-C)
/project-resurrection
   ↓
...
```

---

## Casos de Uso Específicos

### 1. Alternância Diária (mesmo dia)

```
Manhã: Projeto A
Tarde: Projeto B
/project-resurrection  # 1 min para relembrar
Noite: Projeto C
/project-resurrection  # 1 min para relembrar
```

### 2. Retomada Semanal (após fim de semana)

```
Segunda: /project-resurrection
# Detecta que último trabalho foi sexta
# Mostra exatamente onde parou
```

### 3. Retomada Mensal (após pausa longa)

```
Após 1 mês: /project-resurrection
# Detecta projeto "frio"
# Sugere warm-up obrigatório
# Atualizações de dependências
```

### 4. Resgate de Projeto Abandonado

```
Após 6 meses: /project-resurrection
# Detecta 180+ dias sem atividade
# Sugere revisão completa de documentação
# Verifica se stack ainda é relevante
```

---

## Instalação

```bash
# 1. Copiar pasta para skills do Pi
cp -r project-resurrection ~/.pi/skills/

# 2. Instalar dependências (se necessário)
pip install GitPython python-dateutil pyyaml

# 3. Skill disponível como /project-resurrection
```

---

*Skill criada para SOP ESAA Solopreneur v4.1 - Seção 10*
