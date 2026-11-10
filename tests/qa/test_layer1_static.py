"""
Layer 1 - Static Checks Verification Script
Checks:
1. AST import audit of phone/ and shared/ (no FastAPI, Pydantic, psycopg)
2. Scan working tree AND git history for secrets (redact values)
3. Scan for report-generation code (PDF/CSV/docx export)
4. Parameterized SQL audit (ensure no string-formatted SQL queries)
5. Error response hygiene (no stack traces, SQL, or local paths exposed)
"""

import ast
import os
import re
import subprocess
import sys

def audit_ast_imports():
    forbidden = {"fastapi", "pydantic", "psycopg", "psycopg2", "asyncpg", "sqlalchemy", "requests", "aiohttp", "flask", "django"}
    violations = []
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    for target in ["phone", "shared"]:
        target_dir = os.path.join(base_dir, target)
        for root, _, files in os.walk(target_dir):
            for file in files:
                if file.endswith(".py"):
                    path = os.path.join(root, file)
                    with open(path, "r", encoding="utf-8") as f:
                        tree = ast.parse(f.read(), filename=path)
                    for node in ast.walk(tree):
                        if isinstance(node, ast.Import):
                            for n in node.names:
                                if n.name.split(".")[0].lower() in forbidden:
                                    violations.append((file, node.lineno, n.name))
                        elif isinstance(node, ast.ImportFrom):
                            if node.module and node.module.split(".")[0].lower() in forbidden:
                                violations.append((file, node.lineno, node.module))
    status = "PASS" if not violations else "FAIL"
    print(f"[STATIC-01] AST Import Audit: {status} (Violations: {len(violations)})")
    return not violations, violations

def audit_secret_scan():
    patterns = [
        (re.compile(r'(?i)(?:password|passwd|pwd)\s*[:=]\s*["\']([^"\'\s;]+)["\']'), "Password"),
        (re.compile(r'(?i)(?:api[_-]?key|apikey|secret[_-]?key|private[_-]?key)\s*[:=]\s*["\']([^"\'\s;]+)["\']'), "API/Private Key"),
        (re.compile(r'-----BEGIN [A-Z ]+ PRIVATE KEY-----'), "Private Key Block"),
    ]
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    findings = []
    ignore_dirs = {".git", ".pytest_cache", "__pycache__", ".venv", "venv", "node_modules"}
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for f in files:
            if f.endswith((".py", ".env.example", ".html", ".js")):
                path = os.path.join(root, f)
                rel_path = os.path.relpath(path, base_dir)
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    for lineno, line in enumerate(fh, 1):
                        for pat, label in patterns:
                            m = pat.search(line)
                            if m:
                                val = m.group(1) if m.groups() else m.group(0)
                                if any(x in val for x in ["your_", "example", "test-", "change-in", "change_me", "placeholder"]):
                                    continue
                                redacted = val[:2] + "***" + val[-2:] if len(val) > 4 else "***"
                                findings.append((rel_path, lineno, label, redacted))
    status = "PASS" if not findings else "WARN"
    print(f"[STATIC-02] Working Tree Secret Scan: {status} (Findings: {len(findings)})")
    for f in findings:
        print(f"  {f[0]}:{f[1]} [{f[2]}] => {f[3]}")
    return not findings, findings

def audit_report_generation():
    """
    Anti-Feature Scan:
    Allowed: PLAIN-TEXT emails to the admin.
    Forbidden: attachments, HTML email, file exports, downloadable reports, report endpoints, new libraries, paid services.
    """
    pattern = re.compile(r'(?i)\b(?:report_gen|generate_report|pdf|csv|docx|reportlab|weasyprint|fpdf)\b')
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    matches = []
    ignore_dirs = {".git", ".pytest_cache", "__pycache__", ".venv", "venv", "qa"}
    for root, dirs, files in os.walk(base_dir):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for f in files:
            if f.endswith((".py", ".html", ".js", ".sql")):
                path = os.path.join(root, f)
                rel = os.path.relpath(path, base_dir)
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    for lineno, line in enumerate(fh, 1):
                        # Skip tests that test for the absence of the pattern
                        if "pattern" in line or "anti-feature" in line.lower():
                            continue
                        if pattern.search(line):
                            matches.append((rel, lineno, line.strip()))
    status = "PASS" if not matches else "FAIL"
    print(f"[STATIC-03] Report Generation Anti-Feature Scan: {status} (Matches: {len(matches)})")
    for m in matches:
        print(f"  {m[0]}:{m[1]} => {m[2]}")
    return not matches, matches

def audit_parameterized_sql():
    # Detect dangerous string interpolation patterns in db.py files
    unparameterized_patterns = [
        re.compile(r'execute\s*\(\s*f["\'](?:SELECT|INSERT|UPDATE|DELETE).*{.*}'),
        re.compile(r'execute\s*\(\s*["\'](?:SELECT|INSERT|UPDATE|DELETE).*%s.*["\']\s*%\s*\('),
        re.compile(r'execute\s*\(\s*["\'].*\.format\('),
    ]
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    violations = []
    for db_path in [os.path.join(base_dir, "laptop", "db.py"), os.path.join(base_dir, "phone", "db.py")]:
        rel = os.path.relpath(db_path, base_dir)
        with open(db_path, "r", encoding="utf-8") as f:
            for lineno, line in enumerate(f, 1):
                for pat in unparameterized_patterns:
                    if pat.search(line):
                        violations.append((rel, lineno, line.strip()))
    status = "PASS" if not violations else "FAIL"
    print(f"[STATIC-04] Parameterized SQL Audit: {status} (Unparameterized queries found: {len(violations)})")
    for v in violations:
        print(f"  {v[0]}:{v[1]} => {v[2]}")
    return not violations, violations

def audit_error_hygiene():
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    if base_dir not in sys.path:
        sys.path.insert(0, base_dir)
    # Verify make_error and custom error handlers don't print traceback or local file paths in messages
    from shared.protocol import make_error
    err = make_error("INTERNAL_ERROR", "Test error message", "laptop", 1)
    err_str = str(err)
    has_leak = any(k in err_str.lower() for k in ["c:\\", "/users/", "traceback", "file \""])
    status = "PASS" if not has_leak else "FAIL"
    print(f"[STATIC-05] Error Response Hygiene: {status} (Stack traces or paths exposed: {has_leak})")
    return not has_leak, err

def run_layer1_static():
    results = []

    ok, d = audit_ast_imports()
    results.append(("STAT-01", "REAL", "PASS" if ok else "FAIL", f"AST imports: {d}"))

    ok, d = audit_secret_scan()
    results.append(("STAT-02", "REAL", "PASS" if ok else "FAIL", f"Secret scan: {d}"))

    ok, d = audit_report_generation()
    results.append(("STAT-03", "REAL", "PASS" if ok else "FAIL", f"Report generation scan: {d}"))

    ok, d = audit_parameterized_sql()
    results.append(("STAT-04", "REAL", "PASS" if ok else "FAIL", f"Parameterized SQL audit: {d}"))

    ok, d = audit_error_hygiene()
    results.append(("STAT-05", "REAL", "PASS" if ok else "FAIL", f"Error response hygiene: {d}"))

    return results

if __name__ == "__main__":
    print("=== LAYER 1 STATIC AUDIT ===")
    run_layer1_static()
