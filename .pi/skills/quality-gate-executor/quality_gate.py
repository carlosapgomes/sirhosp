#!/usr/bin/env python3
"""
Quality Gate Executor - Script Python autônomo para executar pipeline de qualidade.

Executa os comandos de validação definidos no AGENTS.md ou usa padrões baseados na stack.
Gera relatório estruturado em JSON, Markdown ou texto simples.

Licença: MIT
"""

import json
import subprocess
import sys
import os
import re
import shlex
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import argparse
import datetime

# ============================================================================
# Configurações
# ============================================================================

DEFAULT_TIMEOUT = 300  # 5 minutos por comando
MAX_OUTPUT_LENGTH = 1000  # Caracteres máximos por output

# Comandos padrão por stack
DEFAULT_COMMANDS = {
    "python": {
        "tests": "python3 -m pytest -q --tb=short",
        "lint": "ruff check .",
        "type_check": "mypy .",
        "format": "black --check .",
        "security": "bandit -r . -q",
        "django_check": "python3 manage.py check" if os.path.exists("manage.py") else None,
    },
    "javascript": {
        "tests": "npm test -- --passWithNoTests" if os.path.exists("package.json") else None,
        "lint": "npm run lint" if os.path.exists("package.json") else "eslint .",
        "type_check": "npm run type-check" if os.path.exists("package.json") else "tsc --noEmit",
        "build": "npm run build" if os.path.exists("package.json") else None,
        "audit": "npm audit --audit-level=moderate" if os.path.exists("package.json") else None,
    },
    "generic": {
        "git_status": "git status --porcelain",
        "git_branch": "git branch --show-current",
    }
}

# ============================================================================
# Funções principais
# ============================================================================

def detect_project_stack() -> str:
    """Detecta a stack principal do projeto."""
    if os.path.exists("pyproject.toml") or os.path.exists("requirements.txt") or os.path.exists("manage.py"):
        return "python"
    elif os.path.exists("package.json"):
        return "javascript"
    elif os.path.exists("go.mod"):
        return "golang"
    elif os.path.exists("pom.xml") or os.path.exists("build.gradle"):
        return "java"
    else:
        return "unknown"


def read_agents_md() -> Optional[Dict[str, str]]:
    """Lê comandos do AGENTS.md se existir."""
    agents_path = Path("AGENTS.md")
    if not agents_path.exists():
        return None
    
    commands = {}
    
    try:
        with open(agents_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # Procurar secao de comandos em formatos diferentes:
        # - "## 2. Comandos de Validação"
        # - "## 2) Comandos essenciais"
        # - "## Comandos ..."
        patterns = [
            r"## 2\. Comandos de Validação\s*(.*?)(?=^## |\Z)",
            r"## 2\. Comandos de Validacao\s*(.*?)(?=^## |\Z)",
            r"## Comandos de Validação\s*(.*?)(?=^## |\Z)",
            r"## Comandos de Validacao\s*(.*?)(?=^## |\Z)",
            r"## 2\. Validação\s*(.*?)(?=^## |\Z)",
            r"## 2\. Validacao\s*(.*?)(?=^## |\Z)",
            r"## Validação\s*(.*?)(?=^## |\Z)",
            r"## Validacao\s*(.*?)(?=^## |\Z)",
            r"## 2\)\s*Comandos essenciais\s*(.*?)(?=^## |\Z)",
            r"## 2\.\s*Comandos essenciais\s*(.*?)(?=^## |\Z)",
            r"## Comandos essenciais\s*(.*?)(?=^## |\Z)",
        ]
        
        section_content = None
        for pattern in patterns:
            match = re.search(pattern, content, re.MULTILINE | re.DOTALL | re.IGNORECASE)
            if match:
                section_content = match.group(1)
                break
        
        if not section_content:
            return None
        
        # Extrair comandos da secao:
        # 1) bullets com backticks
        # 2) blocos de codigo
        command_patterns = [
            r'-\s*(.*?):\s*`(.*?)`',  # - Nome: `comando`
            r'-\s*`(.*?)`',           # - `comando`
            r'\*\s*(.*?):\s*`(.*?)`', # * Nome: `comando`
            r'\*\s*`(.*?)`',          # * `comando`
        ]

        in_codeblock = False
        current_label = "command"
        for raw_line in section_content.split('\n'):
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped:
                continue

            if stripped.startswith("###"):
                current_label = re.sub(r"^#+\s*", "", stripped).strip().lower() or "command"
                continue

            if stripped.startswith("```"):
                in_codeblock = not in_codeblock
                continue

            line = line.strip()
                
            for pattern in command_patterns:
                match = re.match(pattern, line)
                if match:
                    if len(match.groups()) == 2:
                        # Formato: - Nome: `comando`
                        name = match.group(1).strip().lower()
                        cmd = match.group(2).strip()
                        commands[name] = cmd
                    else:
                        # Formato: - `comando`
                        cmd = match.group(1).strip()
                        # Extrair nome do comando (primeira palavra)
                        name = cmd.split()[0] if cmd.split() else "command"
                        commands[name] = cmd
                    break

            # Formato em bloco de codigo
            if in_codeblock and not line.startswith("#"):
                if re.match(r"^[A-Za-z0-9_./-]+", line):
                    commands[f"{current_label}_{len(commands)+1}"] = line
        
    except Exception as e:
        print(f"⚠️  Erro ao ler AGENTS.md: {e}", file=sys.stderr)
        return None
    
    return commands if commands else None


def command_binary_available(command: str) -> bool:
    """Checa se o executavel principal parece disponivel."""
    try:
        parts = shlex.split(command)
    except ValueError:
        return False
    if not parts:
        return False
    tool = parts[0]
    if tool in {"python3", "python", "bash", "sh"}:
        return True
    if os.path.isabs(tool) or tool.startswith("./"):
        return os.path.exists(tool)
    return any(
        os.path.exists(os.path.join(path, tool))
        for path in os.environ.get("PATH", "").split(os.pathsep)
        if path
    )


def run_command(name: str, command: str, timeout: int = DEFAULT_TIMEOUT) -> Dict:
    """Executa um comando e retorna resultados estruturados."""
    if not command:
        return {
            "name": name,
            "command": "",
            "success": False,
            "skipped": True,
            "output": "Comando vazio ou não configurado",
            "error": None,
            "duration": 0
        }

    if not command_binary_available(command):
        return {
            "name": name,
            "command": command,
            "success": False,
            "skipped": True,
            "output": "",
            "error": "Comando nao disponivel no ambiente",
            "duration": 0
        }
    
    start_time = datetime.datetime.now()
    
    try:
        # Executar comando com timeout
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.getcwd()
        )
        
        duration = (datetime.datetime.now() - start_time).total_seconds()
        
        # Determinar sucesso (código de saída 0)
        success = result.returncode == 0
        
        # Limitar tamanho do output
        stdout = result.stdout[:MAX_OUTPUT_LENGTH]
        stderr = result.stderr[:MAX_OUTPUT_LENGTH]
        
        # Combinar output
        output = stdout
        if stderr:
            output += f"\n--- stderr ---\n{stderr}"
        
        return {
            "name": name,
            "command": command,
            "success": success,
            "skipped": False,
            "output": output.strip(),
            "error": None if success else f"Exit code: {result.returncode}",
            "duration": round(duration, 2)
        }
        
    except subprocess.TimeoutExpired:
        duration = (datetime.datetime.now() - start_time).total_seconds()
        return {
            "name": name,
            "command": command,
            "success": False,
            "skipped": False,
            "output": "",
            "error": f"Timeout após {timeout} segundos",
            "duration": round(duration, 2)
        }
    except Exception as e:
        duration = (datetime.datetime.now() - start_time).total_seconds()
        return {
            "name": name,
            "command": command,
            "success": False,
            "skipped": False,
            "output": "",
            "error": str(e),
            "duration": round(duration, 2)
        }


def get_commands_to_run() -> List[Tuple[str, str]]:
    """Determina quais comandos executar baseado no projeto."""
    commands = []
    
    # 1. Tentar ler do AGENTS.md
    agents_commands = read_agents_md()
    if agents_commands:
        for name, cmd in agents_commands.items():
            commands.append((name, cmd))
        return commands
    
    # 2. Usar padrões baseados na stack
    stack = detect_project_stack()
    
    if stack == "python":
        default_cmds = DEFAULT_COMMANDS["python"]
        # Adicionar comandos Python
        for key, cmd in default_cmds.items():
            if cmd:
                commands.append((key, cmd))
    elif stack == "javascript":
        default_cmds = DEFAULT_COMMANDS["javascript"]
        # Adicionar comandos JavaScript
        for key, cmd in default_cmds.items():
            if cmd:
                commands.append((key, cmd))
    
    # 3. Adicionar comandos genéricos
    for key, cmd in DEFAULT_COMMANDS["generic"].items():
        if cmd:
            commands.append((key, cmd))
    
    return commands


def generate_report(results: List[Dict], format: str = "text") -> str:
    """Gera relatório no formato especificado."""
    if format == "json":
        return json.dumps({
            "timestamp": datetime.datetime.now().isoformat(),
            "project": os.path.basename(os.getcwd()),
            "branch": subprocess.run(
                "git branch --show-current", 
                shell=True, 
                capture_output=True, 
                text=True
            ).stdout.strip(),
            "commit": subprocess.run(
                "git rev-parse --short HEAD", 
                shell=True, 
                capture_output=True, 
                text=True
            ).stdout.strip(),
            "results": results,
            "summary": {
                "total": len(results),
                "passed": sum(1 for r in results if r["success"] and not r["skipped"]),
                "failed": sum(1 for r in results if not r["success"] and not r["skipped"]),
                "skipped": sum(1 for r in results if r["skipped"]),
                "total_duration": sum(r["duration"] for r in results)
            }
        }, indent=2)
    
    elif format == "markdown":
        report = [
            "# Quality Gate Report",
            "",
            f"**Data:** {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"**Projeto:** {os.path.basename(os.getcwd())}",
            f"**Branch:** {subprocess.run('git branch --show-current', shell=True, capture_output=True, text=True).stdout.strip()}",
            f"**Commit:** {subprocess.run('git rev-parse --short HEAD', shell=True, capture_output=True, text=True).stdout.strip()}",
            "",
            "## Resultados",
            ""
        ]
        
        for result in results:
            if result["skipped"]:
                report.append(f"### ⚪ {result['name']} (skipped)")
                report.append(f"```\n{result['output']}\n```")
            elif result["success"]:
                report.append(f"### ✅ {result['name']}")
                report.append(f"**Comando:** `{result['command']}`")
                report.append(f"**Duração:** {result['duration']}s")
                if result["output"]:
                    report.append(f"```\n{result['output']}\n```")
            else:
                report.append(f"### ❌ {result['name']}")
                report.append(f"**Comando:** `{result['command']}`")
                report.append(f"**Duração:** {result['duration']}s")
                report.append(f"**Erro:** {result['error']}")
                if result["output"]:
                    report.append(f"```\n{result['output']}\n```")
            report.append("")
        
        # Resumo
        passed = sum(1 for r in results if r["success"] and not r["skipped"])
        failed = sum(1 for r in results if not r["success"] and not r["skipped"])
        skipped = sum(1 for r in results if r["skipped"])
        total_duration = sum(r["duration"] for r in results)
        
        report.extend([
            "## Resumo",
            "",
            f"- **Total:** {len(results)} comandos",
            f"- **✅ Passaram:** {passed}",
            f"- **❌ Falharam:** {failed}",
            f"- **⚪ Skipped:** {skipped}",
            f"- **⏱️  Duração total:** {total_duration:.1f}s",
            "",
            f"**Status geral:** {'✅ PASS' if failed == 0 else '❌ FAIL'}",
            ""
        ])
        
        return "\n".join(report)
    
    else:  # text
        report = []
        report.append("=" * 60)
        report.append("QUALITY GATE REPORT")
        report.append("=" * 60)
        report.append(f"Data: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append(f"Projeto: {os.path.basename(os.getcwd())}")
        report.append("")
        
        for result in results:
            if result["skipped"]:
                report.append(f"[SKIP] {result['name']}: {result['output']}")
            elif result["success"]:
                report.append(f"[PASS] {result['name']} ({result['duration']}s)")
                if result["output"]:
                    # Mostrar apenas primeiras linhas em modo texto
                    lines = result["output"].split('\n')
                    if len(lines) > 3:
                        report.extend(lines[:3])
                        report.append("... (output truncated)")
                    else:
                        report.extend(lines)
            else:
                report.append(f"[FAIL] {result['name']} ({result['duration']}s): {result['error']}")
                if result["output"]:
                    lines = result["output"].split('\n')
                    if len(lines) > 5:
                        report.extend(lines[:5])
                        report.append("... (output truncated)")
                    else:
                        report.extend(lines)
            report.append("")
        
        # Resumo
        passed = sum(1 for r in results if r["success"] and not r["skipped"])
        failed = sum(1 for r in results if not r["success"] and not r["skipped"])
        total = len(results)
        
        report.append("-" * 60)
        report.append(f"RESUMO: {passed}/{total} passaram, {failed} falharam")
        report.append(f"STATUS: {'PASS' if failed == 0 else 'FAIL'}")
        report.append("=" * 60)
        
        return "\n".join(report)


def main():
    """Função principal."""
    parser = argparse.ArgumentParser(
        description="Quality Gate Executor - Executa pipeline de qualidade do projeto",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  %(prog)s                    # Executa quality gate com formato texto
  %(prog)s --format json      # Saída em JSON
  %(prog)s --format markdown  # Saída em Markdown
  %(prog)s --timeout 60       # Timeout de 60 segundos por comando
  %(prog)s --list             # Lista comandos que seriam executados
        """
    )
    
    parser.add_argument(
        "--format", 
        choices=["text", "json", "markdown"], 
        default="text",
        help="Formato de saída (padrão: text)"
    )
    
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"Timeout por comando em segundos (padrão: {DEFAULT_TIMEOUT})"
    )
    
    parser.add_argument(
        "--list",
        action="store_true",
        help="Apenas lista comandos que seriam executados, não executa"
    )
    
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Modo verboso (mostra mais detalhes)"
    )
    
    args = parser.parse_args()
    
    # Detectar comandos
    commands = get_commands_to_run()
    
    if args.verbose:
        print(f"🔍 Stack detectada: {detect_project_stack()}", file=sys.stderr)
        print(f"📋 {len(commands)} comandos encontrados:", file=sys.stderr)
        for name, cmd in commands:
            print(f"  - {name}: {cmd}", file=sys.stderr)
    
    if args.list:
        print("Comandos que seriam executados:")
        for name, cmd in commands:
            print(f"  {name}: {cmd}")
        return 0
    
    if not commands:
        print("⚠️  Nenhum comando encontrado para executar.", file=sys.stderr)
        print("   Crie um AGENTS.md ou use uma stack suportada (Python/JavaScript).", file=sys.stderr)
        return 1
    
    # Executar comandos
    results = []
    print(f"🚀 Executando quality gate com {len(commands)} comandos...", file=sys.stderr)
    
    for name, cmd in commands:
        if args.verbose:
            print(f"▶️  Executando: {name}...", file=sys.stderr)
        
        result = run_command(name, cmd, args.timeout)
        results.append(result)
        
        if args.verbose:
            status = "✅" if result["success"] else "❌"
            print(f"   {status} {name} ({result['duration']}s)", file=sys.stderr)
    
    # Gerar relatório
    report = generate_report(results, args.format)
    print(report)
    
    # Determinar código de saída
    failed = sum(1 for r in results if not r["success"] and not r["skipped"])
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    try:
        exit_code = main()
        sys.exit(exit_code)
    except KeyboardInterrupt:
        print("\n⏹️  Interrompido pelo usuário", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        print(f"💥 Erro não tratado: {e}", file=sys.stderr)
        if os.getenv("DEBUG"):
            import traceback
            traceback.print_exc()
        sys.exit(1)
