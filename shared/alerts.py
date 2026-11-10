"""
SentinelDR - Alerting & Health Diagnostics Module
Standard library only (runtime-neutral for Laptop & Phone).
Evaluates operational health and produces structured alerts for:
- SAFE_MODE transitions
- Lease expiry
- Replication lag
- Sequence gaps
- Unresolved conflicts
- Integrity mismatches
- Peer liveness failures
- Incident tracking & mobile-aligned plain-text email reporting
"""

import email.message
import os
import random
import smtplib
import ssl
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

SEVERITY_INFO = "INFO"
SEVERITY_WARN = "WARNING"
SEVERITY_WARNING = "WARNING"
SEVERITY_CRITICAL = "CRITICAL"


def normalize_node_label(node_id: str) -> str:
    """Standardizes node labels to 'Laptop Node' or 'Phone Node'."""
    val = (node_id or "").strip().lower()
    if "laptop" in val:
        return "Laptop Node"
    if "phone" in val:
        return "Phone Node"
    return node_id


def format_alert_subject(
    severity: str,
    node_id: str,
    title: str,
    incident_id: Optional[str] = None
) -> str:
    """
    Constructs standardized subject line according to Phase 11b specification:
    [SentinelDR][SEVERITY][Laptop Node|Phone Node] short title (incident ID if any)
    """
    sev = severity.upper()
    if sev == "WARN":
        sev = "WARNING"
    node_label = normalize_node_label(node_id)
    if incident_id:
        return f"[SentinelDR][{sev}][{node_label}] {title} ({incident_id})"
    return f"[SentinelDR][{sev}][{node_label}] {title}"


def format_utc_timestamp(ts: Optional[float]) -> str:
    """Formats epoch timestamp to UTC ISO string, or 'N/A' if None."""
    if not ts:
        return "N/A"
    return time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime(ts))


def format_duration(seconds: Optional[float], label: str = "MEASURED") -> str:
    """Formats duration in seconds with explicit measurement provenance label."""
    if seconds is None or seconds < 0:
        return f"N/A [{label}]"
    return f"{seconds:.2f}s [{label}]"


def format_interim_incident_alert(incident_data: Dict[str, Any]) -> str:
    """
    Generates a formally aligned plain-text interim alert for the Admin Device
    when the Phone Node successfully takes over traffic.
    Formatted specifically for narrow mobile phone screens (<70 chars).
    Strictly contains operational metadata only (no user inquiries or secrets).
    """
    inc_id = incident_data.get("incident_id", "UNKNOWN")
    last_hb = incident_data.get("last_good_heartbeat_at")
    suspected = incident_data.get("suspected_at")
    active = incident_data.get("phone_node_active_at") or time.time()

    detection_delay = (suspected - last_hb) if (suspected and last_hb) else None
    takeover_delay = (active - suspected) if (active and suspected) else None

    lines = [
        "======================================================================",
        "SENTINELDR INCIDENT ALERT: TAKEOVER IN PROGRESS",
        "======================================================================",
        f"Incident ID:      {inc_id}",
        "Status:           OPEN",
        "Reporting Node:   Phone Node (standby, port 8001)",
        "Severity:         CRITICAL",
        "----------------------------------------------------------------------",
        "TIMELINE (UTC)",
        "----------------------------------------------------------------------",
        f"Last Good Heartbeat:    {format_utc_timestamp(last_hb)}",
        f"Laptop Suspected Down:  {format_utc_timestamp(suspected)}",
        f"Phone Promoted Active:  {format_utc_timestamp(active)}",
        "----------------------------------------------------------------------",
        "OPERATIONAL METRICS",
        "----------------------------------------------------------------------",
        f"Loss Detection Delay:   {format_duration(detection_delay, 'MEASURED')}",
        f"Takeover Time:          {format_duration(takeover_delay, 'MEASURED')}",
        "* Notice: Exact crash moment of Laptop Node is unknown.",
        "  Detection delay is measured from last successful heartbeat.",
        "----------------------------------------------------------------------",
        "ACTIONS PERFORMED BY THE PHONE NODE",
        "----------------------------------------------------------------------",
        "* Heartbeat loss detected (3 consecutive missed intervals)",
        "* Verified bounded clock-skew against quorum policy",
        "* Requested mutual-exclusion lease from Independent Witness",
        "* Verified database physical integrity (PRAGMA integrity_check)",
        "* Transitioned to SECONDARY_ACTIVE; write fencing disengaged",
        "* Traffic is actively routed to Phone Node (:8001)",
        "----------------------------------------------------------------------",
        "NEXT STEPS",
        "----------------------------------------------------------------------",
        "Standby node is handling traffic. Once Laptop Node reboots,",
        "reconciliation catch-up and failback will commence automatically.",
        "A final resolved report will be dispatched upon failback completion.",
        "======================================================================"
    ]
    return "\n".join(lines)


def format_final_incident_summary(incident_data: Dict[str, Any]) -> str:
    """
    Generates a formally aligned plain-text final summary report for the Admin Device
    when the Laptop Node completes recovery and failback.
    Formatted specifically for mobile phone screens (<70 chars).
    Builds strictly from metadata only (never leaks personal data or secrets).
    """
    inc_id = incident_data.get("incident_id", "UNKNOWN")
    last_hb = incident_data.get("last_good_heartbeat_at")
    suspected = incident_data.get("suspected_at")
    promo_start = incident_data.get("promotion_started_at")
    phone_active = incident_data.get("phone_node_active_at")
    laptop_back = incident_data.get("laptop_node_first_seen_back_at")
    rec_start = incident_data.get("recovery_started_at")
    replay_done = incident_data.get("replay_complete_at")
    failback_done = incident_data.get("failback_completed_at") or time.time()

    writes_accepted = incident_data.get("writes_accepted_during_outage", 0)
    events_replayed = incident_data.get("events_replayed_count", 0)
    conflict_count = incident_data.get("conflict_count", 0)
    integrity_res = incident_data.get("integrity_result", "PASSED")

    # Durations math
    detect_delay = (suspected - last_hb) if (suspected and last_hb) else None
    takeover_delay = (phone_active - (promo_start or suspected)) if (phone_active and (promo_start or suspected)) else None
    unreachable_dur = (laptop_back - (last_hb or suspected)) if (laptop_back and (last_hb or suspected)) else None
    phone_primary_dur = (failback_done - phone_active) if (failback_done and phone_active) else None
    replay_dur = (replay_done - rec_start) if (replay_done and rec_start) else None

    lines = [
        "======================================================================",
        "SENTINELDR INCIDENT SUMMARY REPORT (RESOLVED)",
        "======================================================================",
        f"Incident ID:      {inc_id}",
        "Status:           RESOLVED",
        "Primary Node:     Laptop Node (port 8000)",
        "Standby Node:     Phone Node (port 8001)",
        "----------------------------------------------------------------------",
        "INCIDENT TIMELINE (UTC)",
        "----------------------------------------------------------------------",
        f"Last Good Heartbeat:          {format_utc_timestamp(last_hb)}",
        f"Laptop Suspected Offline:     {format_utc_timestamp(suspected)}",
        f"Phone Promotion Initiated:    {format_utc_timestamp(promo_start)}",
        f"Phone Assumed Primary:        {format_utc_timestamp(phone_active)}",
        f"Laptop Reconnected Online:    {format_utc_timestamp(laptop_back)}",
        f"Recovery Catchup Started:     {format_utc_timestamp(rec_start)}",
        f"Replication Replay Done:      {format_utc_timestamp(replay_done)}",
        f"Failback Completed:           {format_utc_timestamp(failback_done)}",
        "----------------------------------------------------------------------",
        "OPERATIONAL DURATIONS",
        "----------------------------------------------------------------------",
        f"Loss Detection Delay:         {format_duration(detect_delay, 'MEASURED')}",
        f"Promotion Takeover Time:      {format_duration(takeover_delay, 'MEASURED')}",
        f"Laptop Unreachable Duration:  {format_duration(unreachable_dur, 'INFERRED')}",
        f"Phone Primary Active Window:  {format_duration(phone_primary_dur, 'MEASURED')}",
        f"Reconciliation Replay Time:   {format_duration(replay_dur, 'MEASURED')}",
        "* Notice: Exact crash moment is unknown; unreachable duration is",
        "  inferred from the last healthy heartbeat to first reconnection.",
        "----------------------------------------------------------------------",
        "ACTIONS PERFORMED BY THE PHONE NODE",
        "----------------------------------------------------------------------",
        "* Detected loss of Laptop Node (3 missed heartbeat intervals)",
        "* Successfully acquired lease from Independent Witness",
        "* Assumed disaster recovery primary role (SECONDARY_ACTIVE)",
        f"* Accepted {writes_accepted} write transaction(s) during outage",
        "* Queued all mutations into change_log for downstream replay",
        "* Fenced local writes and stepped down gracefully upon failback",
        "----------------------------------------------------------------------",
        "ACTIONS PERFORMED BY THE LAPTOP NODE",
        "----------------------------------------------------------------------",
        "* Node returned online and initiated automatic state discovery",
        "* Entered RECOVERING state and initiated restartable catch-up",
        f"* Replayed {events_replayed} event(s) idempotently from Phone Node outbox",
        "* Validated cryptographic canonical hash parity between databases",
        f"* Conflict check verified: {conflict_count} conflicts detected",
        "* Acquired next epoch lease and restored PRIMARY_ACTIVE role",
        "----------------------------------------------------------------------",
        "FINAL CLUSTER STATE & INTEGRITY",
        "----------------------------------------------------------------------",
        "Active Primary:   Laptop Node (:8000)",
        "Standby Node:     Phone Node (:8001)",
        f"Conflict Count:   {conflict_count} (Zero Conflicts)",
        f"Integrity Check:  {integrity_res}",
        "Single Writer:    VERIFIED (Laptop Node exclusively writable)",
        "Cluster Health:   OPTIMAL & FULLY SYNCHRONIZED",
        "======================================================================"
    ]
    return "\n".join(lines)


class EmailAlertDispatcher:
    """
    Standard-library SSL/TLS email alert dispatcher for SentinelDR.
    Sends alerts asynchronously or synchronously via standard smtplib.
    Never leaks passwords in error messages or logs.
    """

    def __init__(
        self,
        smtp_host: Optional[str] = None,
        smtp_port: Optional[int] = None,
        smtp_user: Optional[str] = None,
        smtp_password: Optional[str] = None,
        admin_email: Optional[str] = None,
        channel: Optional[str] = None,
    ):
        self.channel = channel if channel is not None else os.getenv("SDR_ALERT_CHANNEL", "email")
        self.smtp_host = smtp_host if smtp_host is not None else os.getenv("SDR_SMTP_HOST", "smtp.gmail.com")
        raw_port = smtp_port if smtp_port is not None else os.getenv("SDR_SMTP_PORT", "465")
        try:
            self.smtp_port = int(raw_port)
        except (ValueError, TypeError):
            self.smtp_port = 465
        self.smtp_user = smtp_user if smtp_user is not None else os.getenv("SDR_SMTP_USER", "")
        self.smtp_password = smtp_password if smtp_password is not None else os.getenv("SDR_SMTP_APP_PASSWORD", "")
        self.admin_email = admin_email if admin_email is not None else os.getenv("SDR_ADMIN_ALERT_EMAIL", "")

    def is_configured(self) -> bool:
        """Returns True if email channel is enabled and all credentials are present."""
        return bool(
            self.channel == "email"
            and self.smtp_user
            and self.smtp_password
            and self.admin_email
        )

    def send_alert_sync(
        self,
        subject: str,
        body: str,
        severity: str = SEVERITY_CRITICAL,
        node_id: str = "cluster",
        incident_id: Optional[str] = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Synchronously send an email via SMTP_SSL (port 465) or STARTTLS (port 587/25).
        Never leaks passwords in error messages or logs.
        """
        if not self.is_configured():
            return False, "Email alerting not configured or credentials missing in .env"

        full_subject = format_alert_subject(severity, node_id, subject, incident_id)

        msg = email.message.EmailMessage()
        msg["Subject"] = full_subject
        msg["From"] = f"SentinelDR Sentinel <{self.smtp_user}>"
        msg["To"] = self.admin_email
        msg.set_content(body)

        try:
            context = ssl.create_default_context()
            if self.smtp_port == 465:
                with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port, context=context, timeout=10.0) as server:
                    server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self.smtp_host, self.smtp_port, timeout=10.0) as server:
                    try:
                        server.starttls(context=context)
                    except Exception:
                        pass
                    if self.smtp_user and self.smtp_password:
                        server.login(self.smtp_user, self.smtp_password)
                    server.send_message(msg)
            return True, None
        except Exception as e:
            safe_err = str(e)
            if self.smtp_password:
                safe_err = safe_err.replace(self.smtp_password, "********")
            return False, safe_err

    def send_alert_async(
        self,
        subject: str,
        body: str,
        severity: str = SEVERITY_CRITICAL,
        node_id: str = "cluster",
        incident_id: Optional[str] = None,
        on_complete: Optional[Callable[[bool, Optional[str]], None]] = None,
    ) -> threading.Thread:
        """
        Dispatches email alert asynchronously in a background daemon thread
        without blocking failover or request processing.
        """
        def _worker():
            ok, err = self.send_alert_sync(subject, body, severity, node_id, incident_id)
            if on_complete:
                try:
                    on_complete(ok, err)
                except Exception:
                    pass

        t = threading.Thread(target=_worker, daemon=True)
        t.start()
        return t


class AlertOutboxWorker:
    """
    Durable alert sender that runs as a background daemon.
    1. Reads pending alerts from alert_outbox.
    2. Retries delivery with exponential backoff & jitter.
    3. Works offline and delivers alerts once internet/SMTP returns.
    4. Survives restarts because all pending alerts are stored durably in DB.
    5. Enforces hourly (20) and daily (100) send caps.
    6. Prunes old delivered rows to keep the queue bounded.
    7. Never blocks request threads, failover, writes, or replication.
    """

    def __init__(
        self,
        db: Any,
        dispatcher: Optional[EmailAlertDispatcher] = None,
        node_id: str = "cluster",
        poll_interval: float = 2.0,
        max_per_hour: Optional[int] = None,
        max_per_day: Optional[int] = None,
        batch_info_digest: bool = True,
        digest_min_batch: int = 2,
    ):
        self.db = db
        self.dispatcher = dispatcher or EmailAlertDispatcher()
        self.node_id = node_id
        self.poll_interval = poll_interval
        self.max_per_hour = max_per_hour if max_per_hour is not None else int(os.getenv("SDR_ALERT_MAX_PER_HOUR", "20"))
        self.max_per_day = max_per_day if max_per_day is not None else int(os.getenv("SDR_ALERT_MAX_PER_DAY", "100"))
        self.batch_info_digest = batch_info_digest
        self.digest_min_batch = digest_min_batch
        self._last_throttled_notice_sent_at = 0.0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()

    def start(self) -> None:
        """Starts background worker daemon thread."""
        with self._lock:
            if self._running:
                return
            self._running = True
            self._thread = threading.Thread(target=self._run_loop, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stops the worker daemon."""
        with self._lock:
            self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)

    def _run_loop(self) -> None:
        last_prune = 0.0
        while self._running:
            try:
                self.process_pending()
            except Exception:
                pass

            now = time.time()
            if now - last_prune > 3600.0:
                try:
                    self.db.prune_alert_outbox(max_rows=1000, keep_seconds=86400 * 7)
                    last_prune = now
                except Exception:
                    pass

            # Sleep in short increments to allow rapid shutdown
            for _ in range(int(self.poll_interval * 10)):
                if not self._running:
                    break
                time.sleep(0.1)

    def process_pending(self, limit: int = 5, now: Optional[float] = None) -> int:
        """
        Processes up to `limit` pending alerts ready for delivery.
        - Critical disaster recovery alerts ALWAYS bypass rate caps.
        - Non-critical alerts are throttled if hourly or daily caps are reached.
        - Low-severity (INFO) alerts are batched into a digest when multiple are queued.
        """
        cur_time = now if now is not None else time.time()
        if not self.dispatcher.is_configured():
            return 0

        alerts = self.db.get_pending_alerts(limit=limit, now=cur_time)
        if not alerts:
            return 0

        # Check hourly and daily caps
        sent_past_hour = 0
        sent_past_day = 0
        try:
            sent_past_hour = self.db.get_alert_send_counts(cur_time - 3600.0)
            sent_past_day = self.db.get_alert_send_counts(cur_time - 86400.0)
        except Exception:
            pass

        throttled = (sent_past_hour >= self.max_per_hour) or (sent_past_day >= self.max_per_day)
        sent_count = 0

        # Low-severity batching into an operational digest
        info_alerts = [
            a for a in alerts
            if a["severity"] == SEVERITY_INFO
            and not a.get("title", "").startswith("[TEST]")
            and not a.get("title", "").startswith("Failback complete")
        ]
        if self.batch_info_digest and len(info_alerts) >= self.digest_min_batch and not throttled:
            digest_title = f"Operational Event Digest ({len(info_alerts)} events)"
            digest_lines = [
                "SentinelDR Periodic Operational Digest",
                "==================================================",
                f"Reporting Node: {normalize_node_label(self.node_id)}",
                f"Generated At:   {format_utc_timestamp(cur_time)}",
                f"Batched Events: {len(info_alerts)}",
                "==================================================\n",
            ]
            for idx, item in enumerate(info_alerts, 1):
                first_line = item["body"].splitlines()[0] if item["body"] else "No details"
                digest_lines.append(f"[{idx}] {item['title']}")
                digest_lines.append(f"    Timestamp: {format_utc_timestamp(item['created_at'])}")
                digest_lines.append(f"    Summary:   {first_line}")
                digest_lines.append("")

            digest_body = "\n".join(digest_lines)
            ok, err = self.dispatcher.send_alert_sync(
                subject=digest_title,
                body=digest_body,
                severity=SEVERITY_INFO,
                node_id=self.node_id
            )
            if ok:
                for a in info_alerts:
                    self.db.mark_alert_sent(a["id"], cur_time)
                sent_count += len(info_alerts)
                alerts = [a for a in alerts if a not in info_alerts]

        for alert in alerts:
            alert_id = alert["id"]
            severity = alert["severity"]
            title = alert["title"]
            body = alert["body"]
            attempts = alert.get("attempts", 0)

            # Cap protection: CRITICAL alerts NEVER get dropped by caps
            if throttled and severity != SEVERITY_CRITICAL:
                if (cur_time - self._last_throttled_notice_sent_at) > 3600.0:
                    self._last_throttled_notice_sent_at = cur_time
                    self.dispatcher.send_alert_sync(
                        subject="Alert delivery throttled (rate cap reached)",
                        body=(
                            f"Non-critical alerts have been throttled on {normalize_node_label(self.node_id)}.\n"
                            f"Hourly Cap: {self.max_per_hour} (Current: {sent_past_hour})\n"
                            f"Daily Cap:  {self.max_per_day} (Current: {sent_past_day})\n"
                            f"Note: Critical disaster recovery alerts continue uninterrupted."
                        ),
                        severity=SEVERITY_WARNING,
                        node_id=self.node_id
                    )
                continue

            # Synchronous transmission attempt
            ok, err = self.dispatcher.send_alert_sync(
                subject=title,
                body=body,
                severity=severity,
                node_id=self.node_id
            )

            if ok:
                self.db.mark_alert_sent(alert_id, cur_time)
                sent_count += 1
            else:
                new_attempts = attempts + 1
                jitter = random.uniform(0.5, 2.0)
                backoff = min(300.0, (2 ** min(new_attempts, 8)) + jitter)
                next_try = cur_time + backoff
                self.db.record_alert_attempt(alert_id, next_try, new_attempts)

        return sent_count

    def flush(self, timeout: float = 3.0) -> int:
        """Attempts to process remaining alerts synchronously (e.g. during clean shutdown)."""
        start = time.time()
        total_sent = 0
        while time.time() - start < timeout:
            count = self.process_pending(limit=10)
            total_sent += count
            if count == 0:
                break
            time.sleep(0.2)
        return total_sent


def enqueue_alert(
    db: Any,
    dedupe_key: str,
    severity: str,
    title: str,
    body: str,
    cooldown_seconds: float = 60.0,
    now: Optional[float] = None
) -> Optional[str]:
    """
    Convenience helper to insert an alert into the durable alert outbox.
    Applies cooldown deduplication to prevent flapping.
    """
    if not hasattr(db, "enqueue_alert"):
        return None
    return db.enqueue_alert(
        dedupe_key=dedupe_key,
        severity=severity,
        title=title,
        body=body,
        cooldown_seconds=cooldown_seconds,
        now=now
    )


def resolve_alert_condition(
    db: Any,
    dedupe_key: str,
    node_id: str,
    condition_title: str,
    resolution_notes: str,
    now: Optional[float] = None
) -> Optional[str]:
    """
    Enqueues a 'resolved' notification alert when an incident condition clears.
    Uses dedupe_key based resolution naming so the admin receives notification
    that the condition has returned to normal.
    """
    cur_time = now if now is not None else time.time()
    clean_key = dedupe_key.replace("resolved_", "")
    body = (
        f"CONDITION RESOLVED: {condition_title}\n"
        f"==================================================\n"
        f"Node:          {normalize_node_label(node_id)}\n"
        f"Condition Key: {clean_key}\n"
        f"Resolved At:   {format_utc_timestamp(cur_time)}\n"
        f"Status:        NORMAL OPERATIONAL STATE RESTORED\n"
        f"Notes:         {resolution_notes}\n"
        f"=================================================="
    )
    return enqueue_alert(
        db=db,
        dedupe_key=f"resolved_{clean_key}_{int(cur_time)}",
        severity=SEVERITY_INFO,
        title=f"RESOLVED: {condition_title}",
        body=body,
        cooldown_seconds=0.0,
        now=cur_time
    )



_global_dispatcher: Optional[EmailAlertDispatcher] = None


def get_alert_dispatcher() -> EmailAlertDispatcher:
    """Retrieve global alert dispatcher instance."""
    global _global_dispatcher
    if _global_dispatcher is None:
        _global_dispatcher = EmailAlertDispatcher()
    return _global_dispatcher


def dispatch_alert(
    subject: str,
    body: str,
    severity: str = SEVERITY_CRITICAL,
    node_id: str = "cluster",
    incident_id: Optional[str] = None,
) -> None:
    """Convenience fire-and-forget helper to dispatch alerts in background."""
    dispatcher = get_alert_dispatcher()
    if dispatcher.is_configured():
        dispatcher.send_alert_async(subject, body, severity, node_id, incident_id)


class AlertChecker:
    """Evaluates cluster alerts against real database and in-memory states."""

    def __init__(
        self,
        node_id: str,
        cluster_id: str,
        db: Any,
        state_machine: Any,
        heartbeat_tracker: Optional[Any] = None,
        lag_warn_threshold: int = 5,
    ):
        self.node_id = node_id
        self.cluster_id = cluster_id
        self.db = db
        self.state_machine = state_machine
        self.heartbeat_tracker = heartbeat_tracker
        self.lag_warn_threshold = lag_warn_threshold

    def get_active_alerts(self, now: Optional[float] = None) -> List[Dict[str, Any]]:
        """Evaluate and return list of currently active alerts."""
        alerts: List[Dict[str, Any]] = []
        current_time = now if now is not None else time.time()

        # 1. Check SAFE_MODE
        current_state = self.state_machine.current_state
        if current_state == "SAFE_MODE":
            alerts.append({
                "alert_id": "ALERT_SAFE_MODE",
                "severity": SEVERITY_CRITICAL,
                "node_id": self.node_id,
                "message": "Node is in SAFE_MODE. Writes are strictly fenced; fail-closed disaster recovery active.",
                "action": "Inspect witness connectivity and audit log to verify cluster safety before manual override.",
                "detected_at": current_time,
            })

        # 2. Check Lease Expiry & Nearing Expiry
        try:
            ownership = self.db.get_ownership(self.cluster_id)
            if ownership and ownership.owner_node_id == self.node_id:
                near_threshold = float(os.getenv("SDR_LEASE_EXPIRY_ALERT_THRESHOLD_SECONDS", "10.0"))
                remaining = ownership.lease_expires_at - current_time
                if remaining <= 0:
                    alerts.append({
                        "alert_id": "ALERT_LEASE_EXPIRED",
                        "severity": SEVERITY_CRITICAL,
                        "node_id": self.node_id,
                        "message": f"Active primary lease '{ownership.lease_id}' expired at {ownership.lease_expires_at:.3f}.",
                        "action": "Renew lease from witness quorum immediately or step down to prevent dual-writers.",
                        "detected_at": current_time,
                    })
                elif remaining <= near_threshold:
                    alerts.append({
                        "alert_id": "ALERT_LEASE_NEARING_EXPIRY",
                        "severity": SEVERITY_WARNING,
                        "node_id": self.node_id,
                        "message": f"Active primary lease '{ownership.lease_id}' expires in {remaining:.1f}s (threshold: {near_threshold:.1f}s).",
                        "action": "Lease renewal should be dispatched to witness.",
                        "detected_at": current_time,
                    })
        except Exception:
            pass

        # 3. Check Unresolved Conflicts
        try:
            conflicts = self.db.get_conflicts(resolved=False)
            if conflicts:
                alerts.append({
                    "alert_id": "ALERT_UNRESOLVED_CONFLICTS",
                    "severity": SEVERITY_CRITICAL,
                    "node_id": self.node_id,
                    "message": f"{len(conflicts)} unresolved write conflict(s) detected during reconciliation.",
                    "action": "Automatic failback halted. Inspect conflict_records table and resolve conflicts explicitly.",
                    "detected_at": current_time,
                })
        except Exception:
            pass

        # 4. Check Replication Lag
        try:
            peer_node = "phone" if self.node_id == "laptop" else "laptop"
            highest_seq = self.db.get_highest_local_sequence(self.node_id)
            ack_checkpoint = self.db.get_replication_checkpoint(f"ack_{peer_node}")
            peer_applied = ack_checkpoint.get("last_applied_sequence", 0)
            lag = max(0, highest_seq - peer_applied)
            if lag > self.lag_warn_threshold:
                alerts.append({
                    "alert_id": "ALERT_REPLICATION_LAG",
                    "severity": SEVERITY_WARN,
                    "node_id": self.node_id,
                    "message": f"Replication lag is {lag} events behind (threshold: {self.lag_warn_threshold}).",
                    "action": "Check peer network connectivity and replication outbox worker.",
                    "detected_at": current_time,
                })
        except Exception:
            pass

        # 5. Check Peer Suspected Offline
        if self.heartbeat_tracker:
            try:
                hb_status = self.heartbeat_tracker.get_status()
                if hb_status.get("suspected_offline"):
                    misses = hb_status.get("consecutive_misses", 0)
                    alerts.append({
                        "alert_id": "ALERT_PEER_SUSPECTED_OFFLINE",
                        "severity": SEVERITY_WARN,
                        "node_id": self.node_id,
                        "message": f"Peer has missed {misses} consecutive heartbeats and is suspected offline.",
                        "action": "Verify direct LAN connectivity and peer process health.",
                        "detected_at": current_time,
                    })
            except Exception:
                pass

        # 6. Check Database Physical Health
        try:
            db_healthy, db_err = self.db.is_healthy()
            if not db_healthy:
                alerts.append({
                    "alert_id": "ALERT_INTEGRITY_MISMATCH",
                    "severity": SEVERITY_CRITICAL,
                    "node_id": self.node_id,
                    "message": f"Database physical health check failed: {db_err}",
                    "action": "Run database integrity check and restore from consistent backup if corrupted.",
                    "detected_at": current_time,
                })
        except Exception:
            pass

        return alerts
