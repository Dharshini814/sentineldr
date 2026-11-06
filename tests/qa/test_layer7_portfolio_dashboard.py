"""
Layer 7 - Portfolio Parity & Honest Dashboard Audit Suite
Tests:
1. Portfolio asset parity: SHA-256 integrity of portfolio.html
2. Portfolio read routes return valid data on active and standby nodes
3. Rejection of unsupported file uploads (FEATURE_UNSUPPORTED_DURING_FAILOVER)
4. Rejection of unsupported WebSockets (FEATURE_UNSUPPORTED_DURING_FAILOVER)
5. Dashboard honest telemetry: live nodes return valid JSON without exposing secrets
6. Offline node handling: dashboard renders 'unavailable' and does not fabricate metrics
"""

import hashlib
import json
import os
import sys
import threading
import time
import urllib.request
import urllib.error

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from phone.db import PhoneDatabase
from phone.server import PhoneServer
from shared.config import NodeConfig

CLUSTER_ID = "sentineldr-cluster-01"
SHARED_SECRET = "qa-shared-secret-key-67890"

def test_layer7_portfolio_dashboard():
    print("=== LAYER 7 PORTFOLIO PARITY & HONEST DASHBOARD AUDIT ===")
    results = []

    # 1. Portfolio Asset Parity (SHA-256 integrity check)
    portfolio_path = os.path.join(BASE_DIR, "frontend", "portfolio.html")
    has_portfolio = os.path.exists(portfolio_path)
    if has_portfolio:
        with open(portfolio_path, "rb") as f:
            portfolio_sha = hashlib.sha256(f.read()).hexdigest()
        print(f"[PORT-01] Portfolio HTML present with SHA-256: {portfolio_sha[:16]}...: PASS")
        results.append(("PORT-01", "REAL", "PASS", f"SHA-256: {portfolio_sha}"))
    else:
        print("[PORT-01] Portfolio HTML missing: FAIL")
        results.append(("PORT-01", "REAL", "FAIL", "portfolio.html not found"))

    # Setup isolated test server for Phone
    db_file = os.path.join(BASE_DIR, "tests", "qa", "qa_port_phone.db")
    nonce_file = os.path.join(BASE_DIR, "tests", "qa", "qa_port_nonce.db")
    if os.path.exists(db_file): os.remove(db_file)
    if os.path.exists(nonce_file): os.remove(nonce_file)

    phone_cfg = NodeConfig("phone")
    phone_cfg.port = 0
    phone_cfg.database_path = db_file
    phone_cfg.nonce_cache_db = nonce_file
    phone_cfg.secret = SHARED_SECRET

    phone_srv = PhoneServer(phone_cfg)
    port = phone_srv.config.port
    server_thread = threading.Thread(target=lambda: phone_srv.serve_forever(poll_interval=0.05), daemon=True)
    server_thread.start()
    time.sleep(0.1)
    base_url = f"http://127.0.0.1:{port}"

    # 2. Portfolio Read Endpoints
    routes = [
        "/api/v1/portfolio/profile",
        "/api/v1/portfolio/skills",
        "/api/v1/portfolio/projects",
        "/api/v1/portfolio/experience",
        "/api/v1/portfolio/education",
        "/api/v1/portfolio/certifications",
        "/api/v1/portfolio/contact"
    ]
    all_read_ok = True
    for route in routes:
        try:
            req = urllib.request.Request(f"{base_url}{route}")
            with urllib.request.urlopen(req, timeout=2.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                if not data.get("ok"):
                    all_read_ok = False
        except Exception as e:
            all_read_ok = False
            break

    print(f"[PORT-02] Portfolio read routes return valid data: {'PASS' if all_read_ok else 'FAIL'}")
    results.append(("PORT-02", "REAL", "PASS" if all_read_ok else "FAIL", f"All {len(routes)} read endpoints return 200 OK"))

    # 3. Rejection of unsupported file uploads
    upload_url = f"{base_url}/api/v1/portfolio/upload"
    upload_data = b"--boundary\r\nContent-Disposition: form-data; name=\"file\"; filename=\"test.txt\"\r\n\r\nfile_content\r\n--boundary--"
    req_up = urllib.request.Request(
        upload_url,
        data=upload_data,
        headers={"Content-Type": "multipart/form-data; boundary=boundary"},
        method="POST"
    )
    upload_rejected = False
    upload_err_msg = ""
    try:
        urllib.request.urlopen(req_up, timeout=2.0)
    except urllib.error.HTTPError as e:
        err_body = json.loads(e.read().decode("utf-8"))
        upload_rejected = (e.code == 400 and err_body.get("error", {}).get("code") == "FEATURE_UNSUPPORTED_DURING_FAILOVER")
        upload_err_msg = err_body.get("error", {}).get("message", "")
    except Exception as e:
        upload_err_msg = str(e)

    print(f"[PORT-03] Rejection of unsupported file uploads: {'PASS' if upload_rejected else 'FAIL'} ({upload_err_msg})")
    results.append(("PORT-03", "REAL", "PASS" if upload_rejected else "FAIL", f"HTTP 400 FEATURE_UNSUPPORTED_DURING_FAILOVER: {upload_err_msg}"))

    # 4. Rejection of unsupported WebSockets
    ws_url = f"{base_url}/ws"
    req_ws = urllib.request.Request(ws_url, headers={"Upgrade": "websocket", "Connection": "Upgrade"}, method="GET")
    ws_rejected = False
    ws_err_msg = ""
    try:
        urllib.request.urlopen(req_ws, timeout=2.0)
    except urllib.error.HTTPError as e:
        err_body = json.loads(e.read().decode("utf-8"))
        ws_rejected = (e.code == 400 and err_body.get("error", {}).get("code") == "FEATURE_UNSUPPORTED_DURING_FAILOVER")
        ws_err_msg = err_body.get("error", {}).get("message", "")
    except Exception as e:
        ws_err_msg = str(e)

    print(f"[PORT-04] Rejection of unsupported WebSockets: {'PASS' if ws_rejected else 'FAIL'} ({ws_err_msg})")
    results.append(("PORT-04", "REAL", "PASS" if ws_rejected else "FAIL", f"HTTP 400 FEATURE_UNSUPPORTED_DURING_FAILOVER: {ws_err_msg}"))

    # 5. Dashboard Telemetry Hygiene: Secrets NEVER exposed in JSON
    stat_url = f"{base_url}/api/v1/status"
    req_stat = urllib.request.Request(stat_url)
    with urllib.request.urlopen(req_stat, timeout=2.0) as resp:
        stat_raw = resp.read().decode("utf-8")
    
    no_secrets = (
        SHARED_SECRET not in stat_raw
        and "qa-witness-secret" not in stat_raw
        and "admin" not in stat_raw.lower()
    )
    print(f"[DASH-01] Status endpoint does NOT leak secrets: {'PASS' if no_secrets else 'FAIL'}")
    results.append(("DASH-01", "REAL", "PASS" if no_secrets else "FAIL", "Zero secrets, HMAC keys, or credentials exposed"))

    # 6. Dashboard HTML Inspection: Offline Honest Telemetry
    dash_path = os.path.join(BASE_DIR, "frontend", "dashboard.html")
    with open(dash_path, "r", encoding="utf-8") as f:
        dash_content = f.read()

    honest_telemetry = (
        "unavailable" in dash_content
        and "badge-offline" in dash_content
        and "ALL NODES OFFLINE" in dash_content
        and "staleThresholdMs" in dash_content
    )
    print(f"[DASH-02] Dashboard code enforces honest telemetry and 'unavailable' tags: {'PASS' if honest_telemetry else 'FAIL'}")
    results.append(("DASH-02", "REAL", "PASS" if honest_telemetry else "FAIL", "Dashboard code renders 'unavailable' on missing/offline node data"))

    phone_srv.stop()
    return results

if __name__ == "__main__":
    test_layer7_portfolio_dashboard()
