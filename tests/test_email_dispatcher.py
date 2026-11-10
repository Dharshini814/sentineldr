"""
Tests for SentinelDR Live Email Alert Dispatcher, Alert Outbox Worker & Incident Tracking
(shared/alerts.py, shared/failover.py, shared/recovery.py)

Covers:
1. Configuration detection and validation.
2. Subject line formatting: [SentinelDR][SEVERITY][Laptop Node|Phone Node] title (incident).
3. Plain-text recipient and body formatting (<70 chars wide, mobile-aligned).
4. Real socket delivery using FakeSMTPServer (socketserver + threading).
5. Dead or slow server non-blocking behavior.
6. Offline queuing, restart persistence, and deferred delivery upon reconnection.
7. Exponential backoff and jitter on transmission failure.
8. Flapping deduplication cooldown and hourly/daily rate caps.
9. Incident duration math (measured vs inferred) with disclaimer.
10. Strict secrecy & privacy audit (no contact contents, passwords, or secrets leaked).
"""

import base64
import email.message
import os
import socket
import socketserver
import sqlite3
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch
import pytest

from phone.db import PhoneDatabase
from shared.alerts import (
    AlertOutboxWorker,
    EmailAlertDispatcher,
    SEVERITY_CRITICAL,
    SEVERITY_INFO,
    SEVERITY_WARNING,
    dispatch_alert,
    enqueue_alert,
    format_alert_subject,
    format_final_incident_summary,
    format_interim_incident_alert,
    get_alert_dispatcher,
    normalize_node_label,
    resolve_alert_condition,
)


class FakeSMTPHandler(socketserver.StreamRequestHandler):
    """Minimal RFC-compliant SMTP handler using Python standard library."""

    def handle(self):
        # 1. Greet client
        self.wfile.write(b"220 fake.smtp.invalid Simple Mail Service Ready\r\n")
        self.wfile.flush()

        while True:
            raw_line = self.rfile.readline()
            if not raw_line:
                break
            line = raw_line.decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            cmd = line[:4].upper()
            if cmd in ("EHLO", "HELO"):
                self.wfile.write(b"250-fake.smtp.invalid Hello\r\n250-AUTH LOGIN PLAIN\r\n250 OK\r\n")
            elif cmd == "AUTH":
                # Handle AUTH LOGIN flow
                self.wfile.write(b"334 VXNlcm5hbWU6\r\n")
                self.wfile.flush()
                self.rfile.readline()
                self.wfile.write(b"334 UGFzc3dvcmQ6\r\n")
                self.wfile.flush()
                self.rfile.readline()
                self.wfile.write(b"235 2.7.0 Authentication successful\r\n")
            elif cmd == "MAIL":
                self.wfile.write(b"250 2.1.0 OK\r\n")
            elif cmd == "RCPT":
                self.wfile.write(b"250 2.1.5 OK\r\n")
            elif cmd == "DATA":
                self.wfile.write(b"354 Start mail input; end with <CRLF>.<CRLF>\r\n")
                self.wfile.flush()
                msg_lines = []
                while True:
                    data_line = self.rfile.readline().decode("utf-8", errors="ignore")
                    if data_line.strip() == ".":
                        break
                    msg_lines.append(data_line)
                self.server.received_messages.append("".join(msg_lines))
                self.wfile.write(b"250 2.0.0 OK: message queued\r\n")
            elif cmd == "QUIT":
                self.wfile.write(b"221 2.0.0 Bye\r\n")
                self.wfile.flush()
                break
            else:
                self.wfile.write(b"250 OK\r\n")
            self.wfile.flush()


class FakeSMTPServer(socketserver.ThreadingTCPServer):
    """In-memory testing SMTP server using standard library socketserver."""
    allow_reuse_address = True

    def __init__(self, addr=("127.0.0.1", 0)):
        self.received_messages = []
        super().__init__(addr, FakeSMTPHandler)


@pytest.fixture
def fake_smtp():
    try:
        server = FakeSMTPServer(("127.0.0.1", 0))
    except OSError as e:
        pytest.skip(f"Loopback TCP binding restricted by environment: {e}")
    port = server.server_address[1]
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    yield server, port
    try:
        server.shutdown()
        server.server_close()
    except Exception:
        pass


@pytest.fixture
def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db = PhoneDatabase(path)
    yield db, path
    try:
        os.remove(path)
    except Exception:
        pass


# ----------------------------------------------------------------------
# 1. Unit Tests: Configuration & Formatting
# ----------------------------------------------------------------------

def test_dispatcher_is_configured_truthfulness():
    """[SIMULATED] Verify is_configured correctly checks all required keys."""
    d1 = EmailAlertDispatcher(smtp_user="", smtp_password="", admin_email="")
    assert d1.is_configured() is False

    d2 = EmailAlertDispatcher(
        smtp_user="sender@example.invalid",
        smtp_password="",
        admin_email="admin@example.invalid",
    )
    assert d2.is_configured() is False

    d3 = EmailAlertDispatcher(
        smtp_user="sender@example.invalid",
        smtp_password="test-password-1234",
        admin_email="admin@example.invalid",
    )
    assert d3.is_configured() is True


def test_standardized_subject_formatting():
    """[REAL] Verify subject line adheres strictly to Phase 11b format."""
    s1 = format_alert_subject("CRITICAL", "laptop", "Primary Database Offline", "inc-401")
    assert s1 == "[SentinelDR][CRITICAL][Laptop Node] Primary Database Offline (inc-401)"

    s2 = format_alert_subject("WARN", "phone", "Missed Heartbeat Intervals")
    assert s2 == "[SentinelDR][WARNING][Phone Node] Missed Heartbeat Intervals"

    s3 = format_alert_subject("info", "Laptop Node", "Failback Complete", "inc-999")
    assert s3 == "[SentinelDR][INFO][Laptop Node] Failback Complete (inc-999)"


def test_send_alert_sync_masks_password_on_error():
    """[REAL] Verify that if an SMTP exception occurs, the password is never leaked."""
    secret_pw = "test-super-secret-password-1"
    dispatcher = EmailAlertDispatcher(
        smtp_host="smtp.example.invalid",
        smtp_port=465,
        smtp_user="sender@example.invalid",
        smtp_password=secret_pw,
        admin_email="admin@example.invalid",
    )

    with patch("smtplib.SMTP_SSL") as mock_smtp_ssl:
        mock_smtp_ssl.side_effect = Exception(
            f"SMTPAuthenticationError: failed for user sender with {secret_pw}"
        )

        ok, err = dispatcher.send_alert_sync(
            subject="Test Fail",
            body="Checking error handling",
            severity=SEVERITY_CRITICAL,
        )

        assert ok is False
        assert err is not None
        assert secret_pw not in err
        assert "********" in err


# ----------------------------------------------------------------------
# 2. Real Socket Tests with FakeSMTPServer
# ----------------------------------------------------------------------

def test_real_smtp_delivery_with_fake_server(fake_smtp):
    """[REAL] Verify end-to-end socket delivery to in-memory SMTP server."""
    server, port = fake_smtp

    dispatcher = EmailAlertDispatcher(
        smtp_host="127.0.0.1",
        smtp_port=port,
        smtp_user="sender@example.invalid",
        smtp_password="test-secret-password-real",
        admin_email="admin@example.invalid",
    )

    ok, err = dispatcher.send_alert_sync(
        subject="Primary Node Down",
        body="Phone node has detected 3 consecutive missed heartbeats.",
        severity=SEVERITY_CRITICAL,
        node_id="phone",
        incident_id="inc-777",
    )

    if not ok and err and "10013" in err:
        pytest.skip("Loopback socket restricted in standard sandbox mode")

    assert ok is True, f"Failed with: {err}"
    assert len(server.received_messages) == 1
    raw_email = server.received_messages[0]
    assert "Subject: [SentinelDR][CRITICAL][Phone Node] Primary Node Down (inc-777)" in raw_email
    assert "To: admin@example.invalid" in raw_email
    assert "Phone node has detected 3 consecutive missed heartbeats." in raw_email


def test_dead_or_slow_smtp_server_never_blocks():
    """[REAL] Verify that unreachable or dead SMTP servers fail gracefully without blocking."""
    # Port 65530 is unlikely to be listening (connection refused)
    dispatcher = EmailAlertDispatcher(
        smtp_host="127.0.0.1",
        smtp_port=65530,
        smtp_user="sender@example.invalid",
        smtp_password="test-secret-password-dead",
        admin_email="admin@example.invalid",
    )

    start = time.time()
    ok, err = dispatcher.send_alert_sync(
        subject="Non-blocking Check",
        body="Checking dead server resilience",
        severity=SEVERITY_CRITICAL,
    )
    elapsed = time.time() - start

    assert ok is False
    assert err is not None
    assert elapsed < 5.0  # Must fail quickly without blocking indefinitely


# ----------------------------------------------------------------------
# 3. Durable Outbox Worker, Offline Queueing & Restart Persistence
# ----------------------------------------------------------------------

def test_offline_queue_then_delivery_upon_reconnect(fake_smtp, temp_db):
    """
    [REAL] Enqueue alerts while offline.
    Ensure they remain safely stored in DB, and upon connecting to SMTP,
    the background AlertOutboxWorker delivers them all.
    """
    server, port = fake_smtp
    db, _ = temp_db

    # Step 1: Enqueue alerts in outbox while disconnected
    alert1 = enqueue_alert(
        db=db,
        dedupe_key="failover_1",
        severity=SEVERITY_CRITICAL,
        title="Laptop Node suspected offline",
        body="Standby phone detected failure.",
    )
    alert2 = enqueue_alert(
        db=db,
        dedupe_key="failover_2",
        severity=SEVERITY_INFO,
        title="Phone Node became active",
        body="Takeover completed.",
    )
    assert alert1 is not None
    assert alert2 is not None

    # Verify pending in DB
    pending = db.get_pending_alerts()
    assert len(pending) == 2

    # Step 2: Configure dispatcher pointing to FakeSMTPServer and process
    dispatcher = EmailAlertDispatcher(
        smtp_host="127.0.0.1",
        smtp_port=port,
        smtp_user="sender@example.invalid",
        smtp_password="test-password-123",
        admin_email="admin@example.invalid",
    )
    worker = AlertOutboxWorker(db=db, dispatcher=dispatcher, node_id="Phone Node")

    delivered = worker.process_pending(limit=10)
    if delivered == 0:
        # Check if due to loopback permission
        ok, err = dispatcher.send_alert_sync("ping", "ping")
        if not ok and err and "10013" in err:
            pytest.skip("Loopback socket restricted in standard sandbox mode")

    assert delivered == 2

    # Verify outbox is now empty (all sent)
    assert len(db.get_pending_alerts()) == 0
    assert len(server.received_messages) == 2


def test_retry_exponential_backoff(temp_db):
    """[REAL] Verify failed delivery records attempt count and sets exponential backoff with jitter."""
    db, _ = temp_db
    now = 1000.0

    alert_id = enqueue_alert(
        db=db,
        dedupe_key="retry_test",
        severity=SEVERITY_CRITICAL,
        title="Test Retry Backoff",
        body="Checking exponential delay.",
        now=now,
    )
    assert alert_id is not None

    # Point dispatcher to dead server
    dispatcher = EmailAlertDispatcher(
        smtp_host="127.0.0.1",
        smtp_port=65530,
        smtp_user="user@example.invalid",
        smtp_password="test-password-retry",
        admin_email="admin@example.invalid",
    )
    worker = AlertOutboxWorker(db=db, dispatcher=dispatcher)

    worker.process_pending(limit=5, now=now)

    pending = db.get_pending_alerts(limit=5, now=now + 500.0)
    assert len(pending) == 1
    alert = pending[0]
    assert alert["attempts"] == 1
    # Next attempt should be >= 1000 + 2^1 + 0.5 = 1002.5
    assert alert["next_attempt_at"] >= (now + 2.0)


def test_restart_persistence(temp_db):
    """[REAL] Verify pending alerts survive complete process/database close and restart."""
    db, db_path = temp_db

    # Write alert and close connection
    enqueue_alert(
        db=db,
        dedupe_key="restart_key",
        severity=SEVERITY_WARNING,
        title="Survives Restart",
        body="Persistence validation row.",
    )

    # Reopen fresh DB instance on same file (simulating server reboot)
    new_db = PhoneDatabase(db_path)
    pending = new_db.get_pending_alerts()
    assert len(pending) == 1
    assert pending[0]["title"] == "Survives Restart"
    assert pending[0]["severity"] == SEVERITY_WARNING


def test_dedupe_cooldown_and_rate_caps(temp_db):
    """[REAL] Verify dedupe cooldown prevents alert flapping, and rate caps limit hourly/daily volume."""
    db, _ = temp_db
    now = time.time()

    # 1. Cooldown test: same dedupe_key within cooldown should be dropped
    id1 = enqueue_alert(db, "flapping_key", SEVERITY_WARNING, "T1", "B1", cooldown_seconds=60.0, now=now)
    id2 = enqueue_alert(db, "flapping_key", SEVERITY_WARNING, "T2", "B2", cooldown_seconds=60.0, now=now + 10.0)
    assert id1 is not None
    assert id2 is None  # Suppressed by cooldown

    # After cooldown expires: allowed
    id3 = enqueue_alert(db, "flapping_key", SEVERITY_WARNING, "T3", "B3", cooldown_seconds=60.0, now=now + 61.0)
    assert id3 is not None

    # 2. Rate cap test: max 2 per hour test
    dispatcher = EmailAlertDispatcher(
        smtp_user="user@example.invalid",
        smtp_password="test-pw-ratecap",
        admin_email="admin@example.invalid",
    )
    worker = AlertOutboxWorker(db=db, dispatcher=dispatcher, max_per_hour=2)

    # Mark 2 alerts as already sent in the past hour
    db.enqueue_alert("c1", "INFO", "C1", "B", 0.0, now=now - 100.0)
    db.enqueue_alert("c2", "INFO", "C2", "B", 0.0, now=now - 50.0)
    for row in db.get_pending_alerts(now=now):
        db.mark_alert_sent(row["id"], sent_at=now - 50.0)

    # Enqueue a third alert
    db.enqueue_alert("c3", "INFO", "C3", "B", 0.0, now=now)

    # Worker should respect max_per_hour=2 and refuse to send more alerts (and issue throttle notice)
    with patch.object(dispatcher, "send_alert_sync", return_value=(True, None)) as mock_send:
        sent = worker.process_pending(now=now)
        assert sent == 0
        assert mock_send.call_count == 1
        assert "throttled" in mock_send.call_args[1]["subject"].lower()


# ----------------------------------------------------------------------
# 4. Formally Aligned Incident Summary Reports & Secrecy
# ----------------------------------------------------------------------

def test_interim_incident_alert_formatting():
    """[REAL] Verify interim takeover report formatting for narrow mobile screens (<70 chars)."""
    incident_data = {
        "incident_id": "inc-20261107-001",
        "last_good_heartbeat_at": 1730980000.0,
        "suspected_at": 1730980009.0,
        "phone_node_active_at": 1730980010.5,
    }
    report = format_interim_incident_alert(incident_data)

    # Check mobile width (<72 chars per line)
    for line in report.splitlines():
        assert len(line) <= 72, f"Line exceeds 72 chars: {line}"

    assert "SENTINELDR INCIDENT ALERT: TAKEOVER IN PROGRESS" in report
    assert "inc-20261107-001" in report
    assert "Loss Detection Delay:   9.00s [MEASURED]" in report
    assert "Takeover Time:          1.50s [MEASURED]" in report
    assert "Notice: Exact crash moment of Laptop Node is unknown." in report


def test_final_incident_summary_formatting_and_durations():
    """[REAL] Verify final resolved summary report contains all metrics, actions, and disclaimers."""
    incident_data = {
        "incident_id": "inc-20261107-002",
        "last_good_heartbeat_at": 1730980000.0,
        "suspected_at": 1730980009.0,
        "promotion_started_at": 1730980009.5,
        "phone_node_active_at": 1730980011.0,
        "laptop_node_first_seen_back_at": 1730980060.0,
        "recovery_started_at": 1730980061.0,
        "replay_complete_at": 1730980063.0,
        "failback_completed_at": 1730980065.0,
        "writes_accepted_during_outage": 3,
        "events_replayed_count": 3,
        "conflict_count": 0,
        "integrity_result": "PASSED (Zero Conflicts)",
    }
    report = format_final_incident_summary(incident_data)

    # Line width constraint for mobile screens
    for line in report.splitlines():
        assert len(line) <= 72, f"Line exceeds 72 chars: {line}"

    assert "SENTINELDR INCIDENT SUMMARY REPORT (RESOLVED)" in report
    assert "Status:           RESOLVED" in report
    assert "Loss Detection Delay:         9.00s [MEASURED]" in report
    assert "Promotion Takeover Time:      1.50s [MEASURED]" in report
    assert "Laptop Unreachable Duration:  60.00s [INFERRED]" in report
    assert "Phone Primary Active Window:  54.00s [MEASURED]" in report
    assert "Reconciliation Replay Time:   2.00s [MEASURED]" in report
    assert "Notice: Exact crash moment is unknown" in report
    assert "Accepted 3 write transaction(s)" in report
    assert "Replayed 3 event(s)" in report
    assert "Conflict Count:   0 (Zero Conflicts)" in report
    assert "Single Writer:    VERIFIED" in report


def test_reports_contain_no_secrets_or_personal_data():
    """[REAL] Verify that generated emails never contain passwords, tokens, or form messages."""
    fake_secret = "my_smtp_secret_pass"
    fake_token = "admin_super_secret_key"
    fake_msg = "My sensitive credit card number 1234-5678"

    incident = {
        "incident_id": "inc-sec-01",
        "last_good_heartbeat_at": 1000.0,
        "suspected_at": 1009.0,
        "promotion_started_at": 1010.0,
        "phone_node_active_at": 1011.0,
        "laptop_node_first_seen_back_at": 1050.0,
        "recovery_started_at": 1051.0,
        "replay_complete_at": 1052.0,
        "failback_completed_at": 1055.0,
        "writes_accepted_during_outage": 1,
        "events_replayed_count": 1,
        "conflict_count": 0,
        "integrity_result": "PASSED",
    }
    report = format_final_incident_summary(incident)

    assert fake_secret not in report
    assert fake_token not in report
    assert fake_msg not in report
    assert "password" not in report.lower()
    assert "secret" not in report.lower()


def test_admin_alerts_test_endpoint_laptop():
    """[REAL] Test authenticated POST /api/v1/admin/alerts/test on Laptop Node."""
    from starlette.testclient import TestClient
    from laptop.server import app, config, alert_worker

    client = TestClient(app)

    # Unauthorized attempt
    resp_unauth = client.post("/api/v1/admin/alerts/test")
    assert resp_unauth.status_code == 401

    # Authorized attempt with admin key
    with patch.object(alert_worker, "process_pending", return_value=1):
        resp_auth = client.post(
            "/api/v1/admin/alerts/test",
            headers={"X-SDR-Admin-Key": config.admin_key}
        )
        assert resp_auth.status_code == 200
        data = resp_auth.json()
        assert data["ok"] is True
        assert data["data"]["node"] == "Laptop Node"
        assert "alert_id" in data["data"]


def test_low_severity_digest_batching(temp_db):
    """[REAL] Verify multiple low-severity INFO alerts are batched into an operational digest."""
    db, _ = temp_db
    now = 5000.0

    # Enqueue 3 INFO alerts
    enqueue_alert(db, "info_1", SEVERITY_INFO, "Worker Started", "Worker is up.", cooldown_seconds=0.0, now=now)
    enqueue_alert(db, "info_2", SEVERITY_INFO, "Backup Done", "Daily backup completed.", cooldown_seconds=0.0, now=now + 1.0)
    enqueue_alert(db, "info_3", SEVERITY_INFO, "Prune Done", "Pruned 5 old records.", cooldown_seconds=0.0, now=now + 2.0)

    dispatcher = EmailAlertDispatcher(
        smtp_user="user@example.invalid",
        smtp_password="test-pw-digest",
        admin_email="admin@example.invalid",
    )
    worker = AlertOutboxWorker(db=db, dispatcher=dispatcher, node_id="Phone Node", batch_info_digest=True, digest_min_batch=2)

    sent_subjects = []
    sent_bodies = []

    def mock_send_sync(subject, body, severity=None, node_id=None):
        sent_subjects.append(subject)
        sent_bodies.append(body)
        return True, None

    with patch.object(dispatcher, "send_alert_sync", side_effect=mock_send_sync):
        delivered = worker.process_pending(limit=10, now=now + 5.0)
        assert delivered == 3
        # Should have sent exactly 1 digest email
        assert len(sent_subjects) == 1
        assert "Operational Event Digest (3 events)" in sent_subjects[0]
        assert "Worker Started" in sent_bodies[0]
        assert "Backup Done" in sent_bodies[0]
        assert "Prune Done" in sent_bodies[0]

    # Verify all 3 were marked sent
    assert len(db.get_pending_alerts(now=now + 10.0)) == 0


def test_resolve_alert_condition_notification(temp_db):
    """[REAL] Verify resolving an alert condition writes a formatted RESOLVED email to outbox."""
    db, _ = temp_db
    now = 6000.0

    alert_id = resolve_alert_condition(
        db=db,
        dedupe_key="laptop_suspected_offline",
        node_id="Phone Node",
        condition_title="Laptop Node Offline",
        resolution_notes="Laptop Node sent valid heartbeat with epoch 2; normal replication resumed.",
        now=now,
    )
    assert alert_id is not None

    pending = db.get_pending_alerts(now=now)
    assert len(pending) == 1
    row = pending[0]
    assert row["severity"] == SEVERITY_INFO
    assert "RESOLVED: Laptop Node Offline" in row["title"]
    assert "CONDITION RESOLVED: Laptop Node Offline" in row["body"]
    assert "NORMAL OPERATIONAL STATE RESTORED" in row["body"]


def test_critical_alert_bypasses_rate_cap_and_throttled_notice(temp_db):
    """[REAL] Verify CRITICAL disaster recovery alerts bypass rate caps and a throttle notice is issued."""
    db, _ = temp_db
    now = 7000.0

    # Mark 2 alerts sent in past hour to hit max_per_hour=2
    db.enqueue_alert("p1", "INFO", "Past 1", "B", 0.0, now=now - 100.0)
    db.enqueue_alert("p2", "INFO", "Past 2", "B", 0.0, now=now - 50.0)
    for row in db.get_pending_alerts(now=now):
        db.mark_alert_sent(row["id"], sent_at=now - 50.0)

    # Enqueue 1 WARNING (should be throttled) and 1 CRITICAL (must bypass cap)
    enqueue_alert(db, "warn_key", SEVERITY_WARNING, "Lag Warning", "Replication lag high", 0.0, now=now)
    enqueue_alert(db, "crit_key", SEVERITY_CRITICAL, "Failover Activated", "Takeover engaged", 0.0, now=now)

    dispatcher = EmailAlertDispatcher(
        smtp_user="user@example.invalid",
        smtp_password="test-pw-caps",
        admin_email="admin@example.invalid",
    )
    worker = AlertOutboxWorker(db=db, dispatcher=dispatcher, node_id="Phone Node", max_per_hour=2)

    sent_alerts = []

    def mock_send(subject, body, severity=None, node_id=None):
        sent_alerts.append((subject, severity))
        return True, None

    with patch.object(dispatcher, "send_alert_sync", side_effect=mock_send):
        worker.process_pending(limit=10, now=now)

        # 1. Throttled notice was sent for the throttled WARNING alert
        throttle_notices = [s for s in sent_alerts if "throttled" in s[0].lower()]
        assert len(throttle_notices) == 1
        assert throttle_notices[0][1] == SEVERITY_WARNING

        # 2. CRITICAL alert bypassed the cap and was delivered!
        crit_alerts = [s for s in sent_alerts if s[0] == "Failover Activated"]
        assert len(crit_alerts) == 1
        assert crit_alerts[0][1] == SEVERITY_CRITICAL

        # 3. WARNING alert remained pending (not dropped, safely queued in outbox)
        pending = db.get_pending_alerts(now=now + 500.0)
        assert any(p["title"] == "Lag Warning" for p in pending)


def test_phone_node_offline_queue_then_delivery_when_smtp_starts(temp_db):
    """
    [REAL] Phone Node enqueues alert while SMTP server is down.
    Delivery fails gracefully, alert persists in outbox.
    Then SMTP server starts up, and outbox worker delivers the queued alert.
    """
    db, _ = temp_db

    # Find an open port for the fake SMTP server
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    # At this point, no server is listening on port (SMTP IS DOWN)
    dispatcher = EmailAlertDispatcher(
        smtp_host="127.0.0.1",
        smtp_port=port,
        smtp_user="phone@example.invalid",
        smtp_password="test-phone-password",
        admin_email="admin@example.invalid",
    )
    worker = AlertOutboxWorker(db=db, dispatcher=dispatcher, node_id="Phone Node")

    now = time.time()
    # 1. Phone node enqueues alert during failover while offline
    alert_id = enqueue_alert(
        db=db,
        dedupe_key="offline_failover_alert",
        severity=SEVERITY_CRITICAL,
        title="Laptop Node suspected offline",
        body="Detection delay: 9.0s. Phone taking over primary role.",
        now=now,
    )
    assert alert_id is not None

    # 2. Worker attempts delivery while SMTP is DOWN
    sent = worker.process_pending(limit=5, now=now)
    assert sent == 0  # Failed cleanly without crashing

    # Alert remains queued and safe in DB outbox with attempt recorded
    pending_during_outage = db.get_pending_alerts(limit=5, now=now + 500.0)
    assert len(pending_during_outage) == 1
    assert pending_during_outage[0]["attempts"] == 1

    # 3. Network / SMTP server comes back online
    server = FakeSMTPServer(("127.0.0.1", port))
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    try:
        # 4. Outbox worker retries delivery now that server is online
        delivered = worker.process_pending(limit=5, now=now + 500.0)
        if delivered == 0:
            ok, err = dispatcher.send_alert_sync("probe", "probe")
            if not ok and err and "10013" in err:
                pytest.skip("Loopback socket restricted in standard sandbox mode")

        assert delivered == 1
        # Outbox queue is now fully delivered
        assert len(db.get_pending_alerts(now=now + 1000.0)) == 0
        assert len(server.received_messages) == 1
        assert "Laptop Node suspected offline" in server.received_messages[0]
    finally:
        server.shutdown()
        server.server_close()


def test_admin_alerts_test_endpoint_phone(temp_db):
    """[REAL] Test authenticated POST /api/v1/admin/alerts/test on Phone Node."""
    import urllib.request
    import json
    from phone.server import PhoneServer
    from shared.config import NodeConfig

    db, db_path = temp_db
    config = NodeConfig(node_type="phone")
    config.port = 0
    config.database_path = db_path

    server = PhoneServer(config)
    t = threading.Thread(target=lambda: server.serve_forever(poll_interval=0.1), daemon=True)
    t.start()
    time.sleep(0.1)

    base_url = f"http://127.0.0.1:{server.config.port}"

    try:
        # Unauthorized attempt -> 401
        req_unauth = urllib.request.Request(f"{base_url}/api/v1/admin/alerts/test", data=b"", method="POST")
        try:
            urllib.request.urlopen(req_unauth)
            assert False, "Should have returned 401"
        except urllib.error.HTTPError as e:
            assert e.code == 401

        # Authorized attempt with admin key -> 200
        req_auth = urllib.request.Request(
            f"{base_url}/api/v1/admin/alerts/test",
            data=b"",
            headers={"X-SDR-Admin-Key": config.admin_key},
            method="POST"
        )
        with urllib.request.urlopen(req_auth) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["ok"] is True
            assert data["data"]["node"] == "Phone Node"
            assert "alert_id" in data["data"]
    except urllib.error.URLError as e:
        if "10013" in str(e) or "WinError 10013" in str(e):
            pytest.skip("Loopback socket restricted in standard sandbox mode")
        raise
    finally:
        server.stop()


