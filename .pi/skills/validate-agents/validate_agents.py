#!/usr/bin/env python3
"""Validate code files against AGENTS.md anti-patterns.

Stdlib-only utility intended for local checks, hooks, and CI.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_POLICY = 2

SEVERITY_RANK = {"none": 0, "low": 1, "medium": 2, "critical": 3}
SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".html", ".htm"}


@dataclass
class Violation:
    rule_id: str
    severity: str
    file: str
    line: int
    message: str
    suggestion: str
    fix_available: bool = False


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def extract_anti_patterns(agents_path: Path) -> List[str]:
    content = read_text(agents_path)
    if not content:
        return []

    lines = content.splitlines()
    start = None
    end = len(lines)

    for i, line in enumerate(lines):
        if line.strip().lower().startswith("## 8.") and "anti" in line.lower():
            start = i + 1
            break

    if start is None:
        return []

    for i in range(start, len(lines)):
        if lines[i].strip().startswith("## "):
            end = i
            break

    rules: List[str] = []
    for line in lines[start:end]:
        stripped = line.strip()
        if stripped.startswith("-"):
            rules.append(stripped.lstrip("- ").strip())

    return rules


def git_list_files(project_root: Path, staged: bool) -> List[str]:
    if not (project_root / ".git").exists():
        return []

    if staged:
        proc = subprocess.run(
            ["git", "-C", str(project_root), "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode != 0:
            return []
        return [line.strip() for line in proc.stdout.splitlines() if line.strip()]

    proc = subprocess.run(
        ["git", "-C", str(project_root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        return []

    paths: List[str] = []
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        raw = line[3:]
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        path = raw.strip()
        if path:
            paths.append(path)
    return paths


def discover_files(project_root: Path, requested: Sequence[str], staged: bool) -> List[Path]:
    if requested:
        candidates = [project_root / p for p in requested]
    else:
        from_git = git_list_files(project_root, staged=staged)
        if from_git:
            candidates = [project_root / p for p in from_git]
        else:
            candidates = [
                p
                for p in project_root.rglob("*")
                if p.is_file()
                and p.suffix.lower() in SUPPORTED_EXTENSIONS
                and "/.git/" not in p.as_posix()
                and "/node_modules/" not in p.as_posix()
                and "/.pi/" not in p.as_posix()
                and "/.codex/" not in p.as_posix()
            ]

    files: List[Path] = []
    seen: set[str] = set()
    for path in candidates:
        if not path.exists() or not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            continue
        key = str(path.resolve())
        if key in seen:
            continue
        seen.add(key)
        files.append(path)
    return files


def find_todo_without_issue(text: str, rel: str) -> List[Violation]:
    violations: List[Violation] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        if not re.search(r"\b(TODO|FIXME|HACK|XXX)\b", line, re.IGNORECASE):
            continue
        has_ref = bool(re.search(r"(#\d+|[A-Z]{2,10}-\d+)", line))
        if not has_ref:
            violations.append(
                Violation(
                    rule_id="todo-without-issue",
                    severity="low",
                    file=rel,
                    line=idx,
                    message="TODO/FIXME sem referência de issue",
                    suggestion="Adicionar referência (#123 ou PROJ-123).",
                    fix_available=False,
                )
            )
    return violations


def find_inline_script(text: str, rel: str) -> List[Violation]:
    violations: List[Violation] = []
    for match in re.finditer(r"<script(?![^>]*\bsrc=)[^>]*>", text, re.IGNORECASE):
        line = text.count("\n", 0, match.start()) + 1
        violations.append(
            Violation(
                rule_id="inline-script",
                severity="medium",
                file=rel,
                line=line,
                message="JavaScript inline detectado em HTML",
                suggestion="Mover JS para arquivo estático e referenciar com src.",
                fix_available=False,
            )
        )
    return violations


def find_hardcoded_secrets(text: str, rel: str, language: str) -> List[Violation]:
    violations: List[Violation] = []
    if language == "python":
        pattern = re.compile(
            r"\b([A-Z0-9_]*(?:SECRET|TOKEN|API_KEY|PASSWORD)[A-Z0-9_]*)\s*=\s*['\"]([^'\"]{4,})['\"]"
        )
    else:
        pattern = re.compile(
            r"\b([A-Z0-9_]*(?:SECRET|TOKEN|API_KEY|PASSWORD)[A-Z0-9_]*)\s*[:=]\s*['\"]([^'\"]{4,})['\"]"
        )

    for idx, line in enumerate(text.splitlines(), start=1):
        m = pattern.search(line)
        if not m:
            continue
        value = m.group(2).lower()
        if value in {"changeme", "placeholder", "example", "dummy", "test", "dev"}:
            continue
        violations.append(
            Violation(
                rule_id="hardcoded-secret",
                severity="critical",
                file=rel,
                line=idx,
                message=f"Possível segredo hardcoded ({m.group(1)})",
                suggestion="Mover segredo para variável de ambiente/cofre.",
                fix_available=False,
            )
        )
    return violations


def find_raw_sql_fstrings(text: str, rel: str) -> List[Violation]:
    violations: List[Violation] = []
    pattern = re.compile(r"\b(?:execute|executemany|raw)\s*\(\s*f['\"]", re.IGNORECASE)
    for idx, line in enumerate(text.splitlines(), start=1):
        if pattern.search(line):
            violations.append(
                Violation(
                    rule_id="raw-sql-fstring",
                    severity="critical",
                    file=rel,
                    line=idx,
                    message="SQL dinâmico com f-string detectado",
                    suggestion="Usar query parametrizada.",
                    fix_available=False,
                )
            )
    return violations


def find_python_ast_violations(text: str, rel: str) -> List[Violation]:
    violations: List[Violation] = []
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        violations.append(
            Violation(
                rule_id="python-syntax",
                severity="medium",
                file=rel,
                line=exc.lineno or 1,
                message=f"Erro de sintaxe Python: {exc.msg}",
                suggestion="Corrigir sintaxe antes da validação.",
                fix_available=False,
            )
        )
        return violations

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    violations.append(
                        Violation(
                            rule_id="wildcard-import",
                            severity="medium",
                            file=rel,
                            line=node.lineno,
                            message="Import wildcard detectado",
                            suggestion="Importar símbolos explícitos.",
                            fix_available=False,
                        )
                    )

        if isinstance(node, ast.ExceptHandler) and node.type is None:
            violations.append(
                Violation(
                    rule_id="bare-except",
                    severity="medium",
                    file=rel,
                    line=node.lineno,
                    message="except: sem tipo de exceção",
                    suggestion="Trocar para except Exception: (ou exceção específica).",
                    fix_available=True,
                )
            )

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            violations.append(
                Violation(
                    rule_id="print-call",
                    severity="medium",
                    file=rel,
                    line=node.lineno,
                    message="print() detectado (preferir logging)",
                    suggestion="Usar logger apropriado.",
                    fix_available=False,
                )
            )

        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            end_line = getattr(node, "end_lineno", node.lineno)
            if end_line - node.lineno + 1 > 50:
                violations.append(
                    Violation(
                        rule_id="long-function",
                        severity="low",
                        file=rel,
                        line=node.lineno,
                        message=f"Função longa ({end_line - node.lineno + 1} linhas)",
                        suggestion="Extrair partes em funções menores.",
                        fix_available=False,
                    )
                )

    return violations


def apply_safe_fixes(path: Path, text: str) -> tuple[str, int]:
    """Apply deterministic low-risk fixes. Returns (updated_text, fix_count)."""
    fix_count = 0

    def repl(match: re.Match[str]) -> str:
        nonlocal fix_count
        fix_count += 1
        indent = match.group(1) or ""
        comment = match.group(2) or ""
        return f"{indent}except Exception:{comment}"

    updated = re.sub(r"^(\s*)except\s*:\s*(#.*)?$", repl, text, flags=re.MULTILINE)

    if updated != text:
        path.write_text(updated, encoding="utf-8")

    return updated, fix_count


def analyze_file(path: Path, project_root: Path) -> tuple[List[Violation], int]:
    rel = path.relative_to(project_root).as_posix()
    text = read_text(path)
    if not text:
        return [], 0

    violations: List[Violation] = []
    ext = path.suffix.lower()

    violations.extend(find_todo_without_issue(text, rel))

    if ext in {".html", ".htm"}:
        violations.extend(find_inline_script(text, rel))

    if ext == ".py":
        violations.extend(find_hardcoded_secrets(text, rel, "python"))
        violations.extend(find_raw_sql_fstrings(text, rel))
        violations.extend(find_python_ast_violations(text, rel))

    if ext in {".js", ".ts", ".tsx", ".jsx"}:
        violations.extend(find_hardcoded_secrets(text, rel, "javascript"))

    lines = text.count("\n") + 1
    return violations, lines


def should_fail(violations: Sequence[Violation], fail_on: str) -> bool:
    threshold = SEVERITY_RANK[fail_on]
    if threshold == 0:
        return False
    return any(SEVERITY_RANK[v.severity] >= threshold for v in violations)


def render_text(
    *,
    files: Sequence[Path],
    violations: Sequence[Violation],
    anti_patterns: Sequence[str],
    total_lines: int,
    fixes_applied: int,
    fail_on: str,
) -> str:
    by_sev = {"critical": 0, "medium": 0, "low": 0}
    for v in violations:
        by_sev[v.severity] += 1

    lines: List[str] = []
    lines.append("validate-agents report")
    lines.append("=" * 22)
    lines.append(f"Files analyzed: {len(files)}")
    lines.append(f"Lines analyzed: {total_lines}")
    lines.append(f"Anti-pattern rules loaded from AGENTS.md: {len(anti_patterns)}")
    lines.append(f"Fail threshold: {fail_on}")
    lines.append("")

    if not violations:
        lines.append("✅ No violations found.")
    else:
        lines.append(f"Violations: {len(violations)}")
        lines.append(f"  critical: {by_sev['critical']}")
        lines.append(f"  medium:   {by_sev['medium']}")
        lines.append(f"  low:      {by_sev['low']}")
        lines.append("")
        for v in violations:
            lines.append(
                f"- [{v.severity.upper()}] {v.file}:{v.line} {v.rule_id} — {v.message}"
            )
            lines.append(f"  suggestion: {v.suggestion}")
            if v.fix_available:
                lines.append("  fix: available with --fix")

    if fixes_applied:
        lines.append("")
        lines.append(f"Auto-fixes applied: {fixes_applied}")

    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate code against AGENTS.md anti-patterns")
    parser.add_argument("files", nargs="*", help="Files to validate (default: modified files)")
    parser.add_argument("--project-root", default=".", help="Project root path")
    parser.add_argument("--staged", action="store_true", help="Validate staged files when no files are provided")
    parser.add_argument("--fix", action="store_true", help="Apply safe automatic fixes when possible")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    parser.add_argument(
        "--fail-on",
        choices=["none", "critical", "medium", "low"],
        default="critical",
        help="Policy threshold. Exit 2 when violations at/above severity exist",
    )
    args = parser.parse_args()

    project_root = Path(args.project_root).resolve()
    files = discover_files(project_root, args.files, staged=args.staged)
    anti_patterns = extract_anti_patterns(project_root / "AGENTS.md")

    violations: List[Violation] = []
    total_lines = 0
    fixes_applied = 0

    for path in files:
        file_violations, line_count = analyze_file(path, project_root)
        total_lines += line_count
        violations.extend(file_violations)

        if args.fix and path.suffix.lower() == ".py":
            original = read_text(path)
            _, changed = apply_safe_fixes(path, original)
            fixes_applied += changed

    if args.fix and fixes_applied:
        # Re-run analysis after fixes to keep report accurate.
        violations = []
        total_lines = 0
        for path in files:
            file_violations, line_count = analyze_file(path, project_root)
            total_lines += line_count
            violations.extend(file_violations)

    failing = should_fail(violations, args.fail_on)

    if args.format == "json":
        payload = {
            "ok": not failing,
            "policy_failed": failing,
            "files_analyzed": len(files),
            "lines_analyzed": total_lines,
            "anti_patterns_loaded": len(anti_patterns),
            "fail_on": args.fail_on,
            "fixes_applied": fixes_applied,
            "violations": [asdict(v) for v in violations],
            "counts": {
                "critical": sum(1 for v in violations if v.severity == "critical"),
                "medium": sum(1 for v in violations if v.severity == "medium"),
                "low": sum(1 for v in violations if v.severity == "low"),
            },
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(
            render_text(
                files=files,
                violations=violations,
                anti_patterns=anti_patterns,
                total_lines=total_lines,
                fixes_applied=fixes_applied,
                fail_on=args.fail_on,
            ),
            end="",
        )

    return EXIT_POLICY if failing else EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
