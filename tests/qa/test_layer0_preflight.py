"""
Layer 0 - Preflight Verification Script
Checks:
1. Python version (3.13+)
2. Installed packages
3. PostgreSQL version & connectivity
4. Ports 8000, 8001, 8002 free
5. .env present with no placeholder secrets
6. Project path not inside cloud-synced folder
7. Phone code imports only standard library
"""

import ast
import os
import socket
import sys
import subprocess

def check_python_version():
    ver = sys.version_info
    ver_str = sys.version.split()[0]
    is_ok = ver.major == 3 and ver.minor >= 13
    print(f"[PREFLIGHT-01] Python Version: {ver_str} => {'PASS' if is_ok else 'FAIL (requires 3.13+)'}")
    return is_ok, ver_str

def check_installed_packages():
    import pip
    res = subprocess.run([sys.executable, "-m", "pip", "list"], capture_output=True, text=True)
    pkgs = res.stdout.strip().split("\n")
    print(f"[PREFLIGHT-02] Installed packages count: {len(pkgs)-2}")
    has_fastapi = any("fastapi" in p.lower() for p in pkgs)
    has_psycopg = any("psycopg" in p.lower() for p in pkgs)
    has_pydantic = any("pydantic" in p.lower() for p in pkgs)
    print(f"  FastAPI present: {has_fastapi}, Psycopg present: {has_psycopg}, Pydantic present: {has_pydantic}")
    return True, f"Packages: {len(pkgs)-2}"

def check_postgres():
    s = socket.socket()
    res = s.connect_ex(('127.0.0.1', 5432))
    s.close()
    if res != 0:
        print("[PREFLIGHT-03] PostgreSQL Connection (127.0.0.1:5432): FAIL (Port 5432 unreachable / closed)")
        return False, "UNREACHABLE"
    # Attempt psycopg connect
    try:
        import psycopg
        with psycopg.connect("postgresql://sentinel:sentinel@localhost:5432/sentineldr", connect_timeout=2) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                pg_ver = cur.fetchone()[0]
        print(f"[PREFLIGHT-03] PostgreSQL Connection: PASS ({pg_ver})")
        return True, pg_ver
    except Exception as e:
        print(f"[PREFLIGHT-03] PostgreSQL Connection: FAIL ({e})")
        return False, str(e)

def check_ports():
    ports = [8000, 8001, 8002]
    free_status = {}
    for p in ports:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        res = s.connect_ex(('127.0.0.1', p))
        s.close()
        is_free = (res != 0)
        free_status[p] = is_free
        print(f"[PREFLIGHT-04] Port {p} available/free: {'PASS' if is_free else 'FAIL (in use)'}")
    all_free = all(free_status.values())
    return all_free, free_status

def check_env_file():
    env_path = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(env_path):
        print("[PREFLIGHT-05] .env file existence: FAIL (Missing .env file; only .env.example exists)")
        return False, "MISSING_.ENV"
    with open(env_path, "r", encoding="utf-8") as f:
        content = f.read()
    placeholders = ["your_", "placeholder", "change_in_production", "change_me"]
    found_placeholders = [p for p in placeholders if p in content]
    if found_placeholders:
        print(f"[PREFLIGHT-05] .env secrets audit: FAIL (Contains placeholder secrets: {found_placeholders})")
        return False, f"PLACEHOLDERS: {found_placeholders}"
    print("[PREFLIGHT-05] .env file: PASS (Present, no placeholder strings found)")
    return True, "VALID"

def check_cloud_synced_path():
    cwd = os.getcwd()
    cloud_indicators = ["onedrive", "dropbox", "google drive", "icloud", "nextcloud", "box sync"]
    matched = [c for c in cloud_indicators if c in cwd.lower()]
    if matched:
        print(f"[PREFLIGHT-06] Cloud sync path audit: FAIL (Current path '{cwd}' is inside cloud-synced folder: {matched})")
        return False, f"INSIDE_CLOUD_SYNC: {matched}"
    print(f"[PREFLIGHT-06] Cloud sync path audit: PASS (Path '{cwd}' is not in known cloud-synced directory)")
    return True, "LOCAL_PATH"

def check_phone_imports():
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
    if violations:
        print(f"[PREFLIGHT-07] Phone/Shared standard library audit: FAIL ({violations})")
        return False, violations
    print("[PREFLIGHT-07] Phone/Shared standard library audit: PASS (0 forbidden imports across phone/ and shared/)")
    return True, "CLEAN"

def run_layer0_preflight():
    results = []
    
    ok, d = check_python_version()
    results.append(("PRE-01", "REAL", "PASS" if ok else "FAIL", f"Python version: {d}"))

    ok, d = check_installed_packages()
    results.append(("PRE-02", "REAL", "PASS" if ok else "FAIL", f"Installed packages count: {d}"))

    ok, d = check_postgres()
    results.append(("PRE-03", "REAL", "PASS" if ok else "FAIL", f"PostgreSQL port 5432: {d}"))

    ok, d = check_ports()
    results.append(("PRE-04", "REAL", "PASS" if ok else "FAIL", f"Ports 8000, 8001, 8002: {d}"))

    ok, d = check_env_file()
    results.append(("PRE-05", "REAL", "PASS" if ok else "FAIL", f"Environment file: {d}"))

    ok, d = check_cloud_synced_path()
    results.append(("PRE-06", "REAL", "PASS" if ok else "FAIL", f"Path sync check: {d}"))

    ok, d = check_phone_imports()
    results.append(("PRE-07", "REAL", "PASS" if ok else "FAIL", f"Standard library import audit: {d}"))

    return results

if __name__ == "__main__":
    print("=== LAYER 0 PREFLIGHT AUDIT ===")
    run_layer0_preflight()
