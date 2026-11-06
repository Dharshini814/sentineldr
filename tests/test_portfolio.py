"""
SentinelDR Portfolio Integration Tests
Verifies HTML page serving, read API data parity across nodes,
no secret leaks, protected outbox write atomicity, and unsupported failover features.
"""

import json
import os
import sqlite3
import sys
import threading
import time
import urllib.error
import urllib.request
import pytest
from starlette.testclient import TestClient

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from laptop.server import app as laptop_app
from phone.server import PhoneServer
from shared.config import NodeConfig


@pytest.fixture(scope="module")
def laptop_client():
    return TestClient(laptop_app)


@pytest.fixture(scope="module")
def phone_server_url(tmp_path_factory):
    tmp_dir = tmp_path_factory.mktemp("phone_portfolio_test")
    db_path = str(tmp_dir / "phone_portfolio.db")
    nonce_path = str(tmp_dir / "phone_portfolio_nonce.db")

    config = NodeConfig(node_type="phone")
    config.port = 0  # Dynamic ephemeral port to avoid collisions
    config.database_path = db_path
    config.nonce_cache_db = nonce_path

    server = PhoneServer(config)
    t = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.1), daemon=True)
    t.start()
    time.sleep(0.1)

    url = f"http://127.0.0.1:{server.config.port}"
    yield url, config, server

    server.stop()


def phone_request(base_url: str, path: str, method: str = "GET", data: dict = None, headers: dict = None) -> tuple:
    full_url = f"{base_url}{path}"
    req_headers = headers or {}
    req_data = None
    if data is not None:
        req_data = json.dumps(data).encode("utf-8")
        req_headers["Content-Type"] = "application/json"

    req = urllib.request.Request(full_url, data=req_data, headers=req_headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            content_type = resp.headers.get("Content-Type", "")
            raw = resp.read()
            if "application/json" in content_type:
                body = json.loads(raw.decode("utf-8"))
            else:
                body = raw.decode("utf-8")
            return resp.status, body, content_type
    except urllib.error.HTTPError as e:
        content_type = e.headers.get("Content-Type", "")
        raw = e.read()
        if "application/json" in content_type:
            body = json.loads(raw.decode("utf-8"))
        else:
            body = raw.decode("utf-8")
        return e.code, body, content_type


# 1. Page-Serving Parity Tests
def test_laptop_serves_unmodified_html(laptop_client):
    resp = laptop_client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    text = resp.text
    assert "MyPortfolio." in text
    assert "Cybersecurity Enthusiast" in text
    assert "Vulnerability Scanner" in text
    assert "PhishGuard" in text


def test_phone_serves_unmodified_html(phone_server_url):
    url, _, _ = phone_server_url
    status, text, content_type = phone_request(url, "/")
    assert status == 200
    assert "text/html" in content_type
    assert "MyPortfolio." in text
    assert "Cybersecurity Enthusiast" in text
    assert "Vulnerability Scanner" in text
    assert "PhishGuard" in text


# 2. Data Parity Across Read Endpoints
def test_profile_data_parity(laptop_client, phone_server_url):
    url, _, _ = phone_server_url
    resp_laptop = laptop_client.get("/api/v1/portfolio/profile").json()
    _, resp_phone, _ = phone_request(url, "/api/v1/portfolio/profile")

    assert resp_laptop["ok"] is True
    assert resp_phone["ok"] is True
    lp_data = resp_laptop["data"]
    ph_data = resp_phone["data"]

    assert lp_data["name"] == ph_data["name"]
    assert lp_data["headline"] == ph_data["headline"]
    assert lp_data["bio_primary"] == ph_data["bio_primary"]
    assert lp_data["bio_secondary"] == ph_data["bio_secondary"]
    assert lp_data["cta_text"] == ph_data["cta_text"]


def test_skills_data_parity(laptop_client, phone_server_url):
    url, _, _ = phone_server_url
    resp_laptop = laptop_client.get("/api/v1/portfolio/skills").json()
    _, resp_phone, _ = phone_request(url, "/api/v1/portfolio/skills")

    assert resp_laptop["ok"] is True
    assert resp_phone["ok"] is True
    lp_skills = resp_laptop["data"]["skills"]
    ph_skills = resp_phone["data"]["skills"]

    assert len(lp_skills) == len(ph_skills) == 4
    categories_lp = [s["category"] for s in lp_skills]
    categories_ph = [s["category"] for s in ph_skills]
    assert categories_lp == categories_ph


def test_projects_data_parity(laptop_client, phone_server_url):
    url, _, _ = phone_server_url
    resp_laptop = laptop_client.get("/api/v1/portfolio/projects").json()
    _, resp_phone, _ = phone_request(url, "/api/v1/portfolio/projects")

    assert resp_laptop["ok"] is True
    assert resp_phone["ok"] is True
    lp_projects = resp_laptop["data"]["projects"]
    ph_projects = resp_phone["data"]["projects"]

    assert len(lp_projects) == len(ph_projects) == 3
    titles_lp = [p["title"] for p in lp_projects]
    titles_ph = [p["title"] for p in ph_projects]
    assert titles_lp == titles_ph == ["Vulnerability Scanner", "Task Management System", "PhishGuard"]


def test_experience_and_education_parity(laptop_client, phone_server_url):
    url, _, _ = phone_server_url
    # Experience
    resp_lp_exp = laptop_client.get("/api/v1/portfolio/experience").json()["data"]["experience"]
    _, resp_ph_exp, _ = phone_request(url, "/api/v1/portfolio/experience")
    assert len(resp_lp_exp) == len(resp_ph_exp["data"]["experience"]) == 1

    # Education
    resp_lp_edu = laptop_client.get("/api/v1/portfolio/education").json()["data"]["education"]
    _, resp_ph_edu, _ = phone_request(url, "/api/v1/portfolio/education")
    assert len(resp_lp_edu) == len(resp_ph_edu["data"]["education"]) == 1


def test_contact_no_secret_leaks(laptop_client, phone_server_url):
    url, _, _ = phone_server_url
    resp_lp = laptop_client.get("/api/v1/portfolio/contact").json()["data"]
    _, resp_ph, _ = phone_request(url, "/api/v1/portfolio/contact")
    data_ph = resp_ph["data"]

    for contact_data in (resp_lp, data_ph):
        assert "email" in contact_data
        assert "linkedin" in contact_data
        assert "github" in contact_data
        # Ensure private admin fields or secrets are NOT leaked
        assert "admin_key" not in contact_data
        assert "hmac_secret" not in contact_data
        assert "password" not in contact_data


def test_compatibility_endpoint_aliases(laptop_client, phone_server_url):
    url, _, _ = phone_server_url
    # /api/v1/profile alias
    assert laptop_client.get("/api/v1/profile").status_code == 200
    st_ph_profile, _, _ = phone_request(url, "/api/v1/profile")
    assert st_ph_profile == 200

    # /api/v1/contact alias
    assert laptop_client.get("/api/v1/contact").status_code == 200
    st_ph_contact, _, _ = phone_request(url, "/api/v1/contact")
    assert st_ph_contact == 200


# 3. Protected Outbox Write Path
def test_laptop_protected_write_generates_outbox_atomically(laptop_client):
    from laptop.server import db as laptop_db, config, state_machine
    from shared.ownership import OwnershipRecord, sign_ownership_record

    # Ensure laptop has valid active lease for protected write
    now = time.time()
    state_machine._state = "PRIMARY_ACTIVE"
    sig = sign_ownership_record(config.cluster_id, "laptop", state_machine.current_epoch, "lease-portfolio-test", now + 60.0, "witness", laptop_db.witness_secret)
    lease = OwnershipRecord(config.cluster_id, "laptop", state_machine.current_epoch, "lease-portfolio-test", now + 60.0, "witness", sig, now)
    laptop_db.set_ownership(lease)

    payload = {
        "name": "Alice Auditor",
        "email": "alice@security.org",
        "subject": "Vulnerability Report",
        "message": "Found interesting behavior in test environment."
    }
    resp = laptop_client.post("/api/v1/portfolio/contact", json=payload)
    assert resp.status_code == 201
    body = resp.json()
    assert body["ok"] is True
    op_id = body["data"]["operation_id"]
    assert op_id is not None
    assert body["data"]["status"] == "PERSISTED_IN_OUTBOX"

    # Verify atomic outbox insertion in change_log table
    from laptop.server import db as laptop_db
    if laptop_db.using_sqlite_fallback:
        conn = sqlite3.connect(laptop_db._sqlite_path)
        cur = conn.cursor()
        cur.execute("SELECT operation_id, entity_type, operation, origin_node_id FROM change_log WHERE operation_id = ?", (op_id,))
        row = cur.fetchone()
        conn.close()
        assert row is not None
        assert row[0] == op_id
        assert row[1] == "inquiry"
        assert row[2] == "upsert"
        assert row[3] == "laptop"


def test_phone_standby_rejects_protected_write(phone_server_url):
    url, config, server = phone_server_url
    payload = {
        "name": "Bob Intruder",
        "email": "bob@standby.org",
        "subject": "Standby Write Test",
        "message": "Attempting write while node is SECONDARY_STANDBY."
    }
    status, body, _ = phone_request(url, "/api/v1/portfolio/contact", method="POST", data=payload)
    # Standby must fail closed and reject writes
    assert status == 403
    assert body["ok"] is False
    assert body["error"]["code"] == "FORBIDDEN"

    # Verify no row created in phone database change_log
    conn = sqlite3.connect(config.database_path)
    cur = conn.cursor()
    cur.execute("SELECT count(*) FROM change_log WHERE origin_node_id = 'phone'")
    count = cur.fetchone()[0]
    conn.close()
    assert count == 0, "No change_log rows should exist on standby node"


# 4. Unsupported Failover Features
def test_unsupported_upload_rejected_with_clear_message(laptop_client, phone_server_url):
    url, _, _ = phone_server_url
    # Laptop
    resp_lp = laptop_client.post("/api/v1/portfolio/upload", json={"file": "test.png"})
    assert resp_lp.status_code == 400
    body_lp = resp_lp.json()
    assert body_lp["error"]["code"] == "FEATURE_UNSUPPORTED_DURING_FAILOVER"
    assert "File uploads are strictly unsupported" in body_lp["error"]["message"]

    # Phone
    st_ph, body_ph, _ = phone_request(url, "/api/v1/portfolio/upload", method="POST", data={"file": "test.png"})
    assert st_ph == 400
    assert body_ph["error"]["code"] == "FEATURE_UNSUPPORTED_DURING_FAILOVER"
    assert "File uploads are strictly unsupported" in body_ph["error"]["message"]


def test_unsupported_websocket_rejected(laptop_client, phone_server_url):
    url, _, _ = phone_server_url
    # Laptop
    resp_lp = laptop_client.get("/ws")
    assert resp_lp.status_code == 400
    assert resp_lp.json()["error"]["code"] == "FEATURE_UNSUPPORTED_DURING_FAILOVER"

    # Phone
    st_ph, body_ph, _ = phone_request(url, "/ws")
    assert st_ph == 400
    assert body_ph["error"]["code"] == "FEATURE_UNSUPPORTED_DURING_FAILOVER"
