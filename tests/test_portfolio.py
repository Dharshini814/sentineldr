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


# 5. Resume Builder & Cross-Node Synchronization Tests
def test_resume_data_parity(laptop_client, phone_server_url):
    url, _, _ = phone_server_url
    from shared.seed_data import RESUME_SEED
    from laptop.server import db as laptop_db, state_machine
    
    # Ensure baseline seed state on laptop
    laptop_db.save_resume(
        origin_node_id="laptop",
        origin_epoch=state_machine.current_epoch,
        name=RESUME_SEED["name"],
        title=RESUME_SEED["title"],
        email=RESUME_SEED["email"],
        phone=RESUME_SEED["phone"],
        location=RESUME_SEED["location"],
        summary=RESUME_SEED["summary"],
        skills=RESUME_SEED["skills"],
        experience=RESUME_SEED["experience"],
        education=RESUME_SEED["education"],
        template=RESUME_SEED["template"],
        is_primary=True
    )

    resp_lp = laptop_client.get("/api/v1/portfolio/resume").json()
    st_ph, resp_ph, _ = phone_request(url, "/api/v1/portfolio/resume")

    assert resp_lp["ok"] is True
    assert st_ph == 200
    assert resp_ph["ok"] is True
    lp_data = resp_lp["data"]
    ph_data = resp_ph["data"]

    assert lp_data["name"] == ph_data["name"]
    assert lp_data["title"] == ph_data["title"]
    assert lp_data["email"] == ph_data["email"]
    assert lp_data["phone"] == ph_data["phone"]
    assert lp_data["location"] == ph_data["location"]
    assert lp_data["summary"] == ph_data["summary"]
    assert lp_data["skills"] == ph_data["skills"]
    assert lp_data["template"] == ph_data["template"]


def test_laptop_resume_write_and_replication_to_phone(laptop_client, phone_server_url):
    from laptop.server import db as laptop_db, config, state_machine
    from shared.ownership import sign_ownership_record

    now = time.time()
    state_machine._state = "PRIMARY_ACTIVE"
    sig = sign_ownership_record(config.cluster_id, "laptop", state_machine.current_epoch, "lease-resume-test", now + 60.0, "witness", laptop_db.witness_secret)
    laptop_db.set_ownership(type("Record", (), {
        "cluster_id": config.cluster_id,
        "owner_node_id": "laptop",
        "epoch": state_machine.current_epoch,
        "lease_id": "lease-resume-test",
        "lease_expires_at": now + 60.0,
        "granted_by": "witness",
        "signature": sig
    })())

    updated_resume = {
        "name": "Dr. Dharshini Updated",
        "title": "Principal Distributed Systems Architect",
        "email": "dharshini.updated@sentineldr.dev",
        "phone": "+1 (555) 999-0000",
        "location": "Boston, MA",
        "summary": "Updated executive summary for disaster recovery test.",
        "skills": "Failover, Replication, SQLite WAL, PostgreSQL",
        "experience": "Lead Architect for SentinelDR Project.",
        "education": "Ph.D. in Computer Science",
        "template": "security"
    }

    # 1. POST to Laptop
    resp = laptop_client.post("/api/v1/portfolio/resume", json=updated_resume)
    assert resp.status_code == 200
    res_json = resp.json()
    assert res_json["ok"] is True
    op_id = res_json["data"]["operation_id"]

    # Verify Laptop db was updated
    lp_resume = laptop_client.get("/api/v1/portfolio/resume").json()["data"]
    assert lp_resume["name"] == "Dr. Dharshini Updated"
    assert lp_resume["title"] == "Principal Distributed Systems Architect"

    # 2. Replicate change_log events to Phone node
    url, phone_config, phone_server = phone_server_url
    checkpoint = phone_server.db.get_replication_checkpoint("laptop")
    last_seq = checkpoint["last_applied_sequence"]
    events_to_sync = laptop_db.get_pending_replication_events("laptop", from_sequence=last_seq + 1, limit=500)

    ok, applied_seq, dup_count, missing, has_gap, err = phone_server.db.apply_replication_batch(
        origin_node_id="laptop",
        batch_id="batch-resume-sync-1",
        events=events_to_sync
    )
    assert ok is True

    # 3. Verify Phone db now reflects the exact same resume
    st_ph, resp_ph, _ = phone_request(url, "/api/v1/portfolio/resume")
    assert st_ph == 200
    ph_data = resp_ph["data"]
    assert ph_data["name"] == "Dr. Dharshini Updated"
    assert ph_data["title"] == "Principal Distributed Systems Architect"
    assert ph_data["email"] == "dharshini.updated@sentineldr.dev"
    assert ph_data["summary"] == "Updated executive summary for disaster recovery test."


def test_phone_resume_write_during_failover_and_replay_to_laptop(laptop_client, phone_server_url):
    url, phone_config, phone_server = phone_server_url
    from laptop.server import db as laptop_db
    from shared.ownership import sign_ownership_record

    # Reset laptop checkpoint for phone to align with fresh ephemeral phone test fixture
    import sqlite3
    conn = sqlite3.connect(laptop_db._sqlite_path)
    conn.execute("DELETE FROM replication_checkpoint WHERE peer_node_id = 'phone'")
    conn.commit()
    conn.close()

    # 1. Promote Phone node to active primary
    now = time.time()
    phone_server.state_machine._state = "PRIMARY_ACTIVE"
    phone_server.state_machine.set_epoch(2)
    phone_sig = sign_ownership_record(phone_config.cluster_id, "phone", 2, "lease-phone-promoted", now + 60.0, "witness", phone_server.db.witness_secret)
    phone_server.db.set_ownership(type("Record", (), {
        "cluster_id": phone_config.cluster_id,
        "owner_node_id": "phone",
        "epoch": 2,
        "lease_id": "lease-phone-promoted",
        "lease_expires_at": now + 60.0,
        "granted_by": "witness",
        "signature": phone_sig
    })())

    failover_resume = {
        "name": "Dr. Dharshini (Phone DR Active)",
        "title": "Disaster Recovery Commander",
        "email": "dharshini.dr@sentineldr.dev",
        "phone": "+1 (555) 888-1111",
        "location": "Failover Edge Node",
        "summary": "Resume edited on Phone Node during primary outage.",
        "skills": "Termux, Standard Library, Outbox Replay",
        "experience": "Successfully commanded failover during outage.",
        "education": "High Availability Systems Architecture",
        "template": "minimal"
    }

    # 2. Write to Phone node
    status, body, _ = phone_request(url, "/api/v1/portfolio/resume", method="POST", data=failover_resume)
    assert status == 200
    assert body["ok"] is True
    op_id = body["data"]["operation_id"]

    # Phone reflects edit
    _, ph_get, _ = phone_request(url, "/api/v1/portfolio/resume")
    assert ph_get["data"]["name"] == "Dr. Dharshini (Phone DR Active)"

    # 3. Simulate recovery replay to Laptop node
    phone_events = phone_server.db.get_pending_replication_events("phone", 1, 50)
    dr_events = [e for e in phone_events if e["operation_id"] == op_id]
    assert len(dr_events) == 1

    ok, applied_seq, dup_count, missing, has_gap, err = laptop_db.apply_replication_batch(
        origin_node_id="phone",
        batch_id="batch-phone-to-laptop-1",
        events=dr_events
    )
    assert ok is True

    # Laptop reflects the resume edited on phone!
    lp_get = laptop_client.get("/api/v1/portfolio/resume").json()
    assert lp_get["data"]["name"] == "Dr. Dharshini (Phone DR Active)"
    assert lp_get["data"]["title"] == "Disaster Recovery Commander"

    # Clean up and restore baseline seed state
    from shared.seed_data import RESUME_SEED
    laptop_db.save_resume(
        origin_node_id="laptop",
        origin_epoch=1,
        name=RESUME_SEED["name"],
        title=RESUME_SEED["title"],
        email=RESUME_SEED["email"],
        phone=RESUME_SEED["phone"],
        location=RESUME_SEED["location"],
        summary=RESUME_SEED["summary"],
        skills=RESUME_SEED["skills"],
        experience=RESUME_SEED["experience"],
        education=RESUME_SEED["education"],
        template=RESUME_SEED["template"],
        is_primary=True
    )


def test_standby_phone_rejects_resume_write(phone_server_url):
    url, phone_config, phone_server = phone_server_url
    phone_server.state_machine._state = "SECONDARY_STANDBY"

    payload = {
        "name": "Intruder Edit",
        "title": "Unauthorized Writer",
        "email": "intruder@fail.org",
        "phone": "000",
        "location": "Void",
        "summary": "Should be rejected",
        "skills": "None",
        "experience": "None",
        "education": "None",
        "template": "modern"
    }
    status, body, _ = phone_request(url, "/api/v1/portfolio/resume", method="POST", data=payload)
    assert status == 403
    assert body["ok"] is False
    assert body["error"]["code"] == "FORBIDDEN"
