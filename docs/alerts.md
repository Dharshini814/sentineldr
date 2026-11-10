# SentinelDR Alerting & Email Configuration

This guide details the automated email alert pipeline, durable outbox delivery, and incident tracking for SentinelDR across the Laptop Node (Windows) and Phone Node (Android Termux), delivering formally aligned plain-text alerts to the Admin Device.

---

## 1. Terminology

| Term | Role | Execution Environment |
| :--- | :--- | :--- |
| **Laptop Node** | Primary cluster node (port 8000) | Windows 11 host (FastAPI, PostgreSQL / SQLite fallback) |
| **Phone Node** | Standby disaster-recovery node (port 8001) | Android Termux environment (Python standard library only) |
| **Admin Device** | Notification endpoint (reads emails via Gmail app) | Administrator's personal mobile phone (runs no SentinelDR code) |

---

## 2. Architecture & Durable Alert Outbox

SentinelDR uses a **Durable Alert Outbox** (`alert_outbox` table in the node's local database) combined with an asynchronous background daemon worker (`AlertOutboxWorker`).

```
Failover / Recovery Event
         │
         ▼ (Atomic DB transaction)
┌───────────────────────────────────────────┐
│     alert_outbox (SQLite / PostgreSQL)     │
│  - id, dedupe_key, severity, title, body   │
│  - created_at, sent_at, attempts, next_try│
└───────────────────────────────────────────┘
         │
         ▼ (Polled asynchronously by AlertOutboxWorker)
┌───────────────────────────────────────────┐
│  - Exponential backoff with jitter        │
│  - Flapping deduplication cooldown        │
│  - Rate caps (max 20/hr, max 100/day)     │
└───────────────────────────────────────────┘
         │
         ▼ (Standard smtplib via SSL:465)
┌───────────────────────────────────────────┐
│             smtp.gmail.com                │
└───────────────────────────────────────────┘
         │
         ▼ (Push notification)
┌───────────────────────────────────────────┐
│       Admin Device (Gmail Mobile App)     │
└───────────────────────────────────────────┘
```

### Key Guarantees
1. **Zero Blocker Policy**: Alert generation and SMTP network transmission NEVER block HTTP request threads, witness quorum leases, database writes, or replication loops.
2. **Offline Resilience**: If the internet or local Wi-Fi drops, alerts are persisted durably in `alert_outbox`. Once connectivity returns, the background worker automatically drains the queue.
3. **Crash Persistence**: Pending alerts survive process restarts, node reboots, and power cycles.
4. **Rate Caps & Flapping Protection**:
   - `dedupe_key` with cooldown prevents flapping when heartbeats jitter.
   - Maximum 20 alerts per hour and 100 alerts per day per node.
5. **Strict Anti-Feature Boundary**:
   - **Allowed**: Plain-text emails to the admin.
   - **Forbidden**: Attachments, HTML email, file exports, downloadable reports, report endpoints, new libraries, paid services.

---

## 3. Incident Lifecycle & Email Alerts

### Phase 1: Primary Server Fails (Laptop Node Goes Offline)
1. **Heartbeat Loss Detection**:
   - Phone Node misses 3 consecutive heartbeats (~9s).
   - Phone Node moves state from `SECONDARY_STANDBY` to `SUSPECTED_OFFLINE`.
   - Generates `OPEN` incident record in `incidents` table.
   - Dispatches Warning alert:
     `[SentinelDR][WARNING][Phone Node] Laptop Node suspected offline (inc-...)`
2. **Takeover & Disaster Recovery Activation**:
   - Phone Node validates bounded clock skew against witness quorum lease.
   - Phone Node acquires next epoch lease from Witness.
   - Phone Node verifies SQLite physical integrity (`PRAGMA integrity_check`).
   - Phone Node transitions to `SECONDARY_ACTIVE` and un-fences local writes.
   - Enqueues **Interim Takeover Report**:
     `[SentinelDR][CRITICAL][Phone Node] Phone Node became active (inc-...)`

### Phase 2: Operations During Outage
- Phone Node serves portfolio and accepts user inquiries into `change_log`.
- Tracks `writes_accepted_during_outage` in the incident record.

### Phase 3: Primary Server Reboots & Failback Completes
1. **Discovery & Recovery Entry**:
   - Laptop Node returns online, discovers Phone Node is active.
   - Laptop Node enters `RECOVERING` state (read-only fenced).
   - Replays all mutations from Phone Node outbox into Laptop database.
   - Validates cryptographic canonical hash parity and zero conflicts.
2. **Failback Finalization**:
   - Fences Phone Node writes.
   - Acquires next epoch lease and restores Laptop Node to `PRIMARY_ACTIVE`.
   - Steps down Phone Node to `SECONDARY_STANDBY`.
   - Finalizes incident status as `RESOLVED`.
   - Enqueues **Formally Aligned Final Summary Report**:
     `[SentinelDR][INFO][Laptop Node] Failback complete - Laptop restored as primary (inc-...)`

---

## 4. Formally Aligned Incident Summary Report Format

The final report is formatted specifically for narrow mobile screens (<70 characters width):

```
======================================================================
SENTINELDR INCIDENT SUMMARY REPORT (RESOLVED)
======================================================================
Incident ID:      inc-1730980000-a1b2c3
Status:           RESOLVED
Primary Node:     Laptop Node (port 8000)
Standby Node:     Phone Node (port 8001)
----------------------------------------------------------------------
INCIDENT TIMELINE (UTC)
----------------------------------------------------------------------
Last Good Heartbeat:          2026-11-07 14:00:00 UTC
Laptop Suspected Offline:     2026-11-07 14:00:09 UTC
Phone Promotion Initiated:    2026-11-07 14:00:09 UTC
Phone Assumed Primary:        2026-11-07 14:00:11 UTC
Laptop Reconnected Online:    2026-11-07 14:01:00 UTC
Recovery Catchup Started:     2026-11-07 14:01:01 UTC
Replication Replay Done:      2026-11-07 14:01:03 UTC
Failback Completed:           2026-11-07 14:01:05 UTC
----------------------------------------------------------------------
OPERATIONAL DURATIONS
----------------------------------------------------------------------
Loss Detection Delay:         9.00s [MEASURED]
Promotion Takeover Time:      1.50s [MEASURED]
Laptop Unreachable Duration:  60.00s [INFERRED]
Phone Primary Active Window:  54.00s [MEASURED]
Reconciliation Replay Time:   2.00s [MEASURED]
* Notice: Exact crash moment is unknown; unreachable duration is
  inferred from the last healthy heartbeat to first reconnection.
----------------------------------------------------------------------
ACTIONS PERFORMED BY THE PHONE NODE
----------------------------------------------------------------------
* Detected loss of Laptop Node (3 missed heartbeat intervals)
* Successfully acquired lease from Independent Witness
* Assumed disaster recovery primary role (SECONDARY_ACTIVE)
* Accepted 3 write transaction(s) during outage
* Queued all mutations into change_log for downstream replay
* Fenced local writes and stepped down gracefully upon failback
----------------------------------------------------------------------
ACTIONS PERFORMED BY THE LAPTOP NODE
----------------------------------------------------------------------
* Node returned online and initiated automatic state discovery
* Entered RECOVERING state and initiated restartable catch-up
* Replayed 3 event(s) idempotently from Phone Node outbox
* Validated cryptographic canonical hash parity between databases
* Conflict check verified: 0 conflicts detected
* Acquired next epoch lease and restored PRIMARY_ACTIVE role
----------------------------------------------------------------------
FINAL CLUSTER STATE & INTEGRITY
----------------------------------------------------------------------
Active Primary:   Laptop Node (:8000)
Standby Node:     Phone Node (:8001)
Conflict Count:   0 (Zero Conflicts)
Integrity Check:  PASSED (Zero Conflicts)
Single Writer:    VERIFIED (Laptop Node exclusively writable)
Cluster Health:   OPTIMAL & FULLY SYNCHRONIZED
======================================================================
```

---

## 5. Setting up Admin Device Gmail Filters

To ensure critical failover alerts wake up the administrator immediately and bypass low-priority email folders:

1. Open Gmail on desktop or web browser: [https://mail.google.com/](https://mail.google.com/).
2. In the search box at the top, click the **Show search options** icon.
3. In the **Subject** field, enter:
   ```
   [SentinelDR][CRITICAL]
   ```
4. Click **Create filter**.
5. Check the following actions:
   - [x] **Never send it to Spam**
   - [x] **Always mark it as important**
   - [x] **Categorize as: Primary**
   - [x] (Optional) **Apply the label**: `SentinelDR-Incidents`
6. Click **Create filter**.
7. On your **Admin Device (mobile phone)**:
   - Open the **Gmail App** > **Settings** > your email account > **Manage labels**.
   - Select `Primary` (or `SentinelDR-Incidents`) > set **Notifications** to **All** and enable **High priority / Sound alert**.

---

## 6. Testing & Admin Verification Tools

### Quick SMTP Verification
To test basic SMTP credentials directly from terminal:
```bash
python scripts/test_email_alert.py
```

### Authenticated Admin API Test Endpoint
Both the Laptop Node and Phone Node expose an authenticated endpoint to trigger a pipeline verification email:

```bash
# On Laptop Node (:8000)
curl -X POST http://localhost:8000/api/v1/admin/alerts/test \
     -H "X-SDR-Admin-Key: <YOUR_ADMIN_KEY>"

# On Phone Node (:8001)
curl -X POST http://localhost:8001/api/v1/admin/alerts/test \
     -H "X-SDR-Admin-Key: <YOUR_ADMIN_KEY>"
```

**Expected Response**:
```json
{
  "ok": true,
  "data": {
    "status": "SENT",
    "alert_id": "9a8b7c6d5e...",
    "node": "Laptop Node",
    "sent_immediately": true,
    "recipient": "admin@example.invalid",
    "message": "Test alert created and submitted to delivery pipeline."
  },
  "node_id": "laptop",
  "epoch": 1
}
```
An authenticated test email will arrive on the Admin Device confirming that the outbox delivery worker and SMTP channel are fully operational.

---

## 7. Real-Device Failover & Failback Verification Runbook

Follow this step-by-step verification runbook to test end-to-end failover, disaster recovery takeover, and automatic recovery/failback across real devices.

### Step 1: Start the Witness Service (Test Setup)

```bash
# Terminal 1 (on Laptop or independent test machine)
python shared/witness.py
```

> [!WARNING]
> **Test Environment Notice**: Running the witness locally on the Laptop (`http://127.0.0.1:8002`) is strictly a **TEST setup** and is **NOT independent**.
> In a production deployment, the witness service MUST reside on an independent 3rd failure domain (e.g., a lightweight cloud instance on Fly.io, AWS, or an external Raspberry Pi) so that a physical power failure or network loss on the Laptop Node does not bring down the witness quorum.

### Step 2: Start the Cluster Nodes

```bash
# Terminal 2 (Phone Node - Android Termux)
cd ~/sentineldr
python phone/server.py

# Terminal 3 (Laptop Node - Windows PowerShell)
cd C:\Users\Dharshini\OneDrive\Desktop\Documents\sentineldr
python laptop/server.py
```

Verify that the Laptop starts as `PRIMARY_ACTIVE` (port 8000) and the Phone starts as `SECONDARY_STANDBY` (port 8001).

### Step 3: Graceful Stop vs. Hard Process Crash

When testing failover, understand the crucial behavioral difference:

| Action | Command | Node Behavior | SentinelDR Test Purpose |
| :--- | :--- | :--- | :--- |
| **Graceful Stop** | Press `Ctrl+C` in the Laptop terminal | Process intercepts `SIGINT`, flushes outbox, closes DB connections cleanly. | Validates planned maintenance shutdown. |
| **Hard Crash** | `taskkill /F /IM python.exe` (or close terminal window) | Simulates sudden kernel panic, hardware fault, or unexpected power loss. No graceful handlers execute. | **True Disaster Recovery**: Validates missed heartbeat detection, bounded-skew lease fencing, and outbox recovery. |

To execute a realistic disaster recovery test, simulate a **hard crash** by forcibly killing the Laptop Node process:

```powershell
# On Windows PowerShell:
Get-Process python | Where-Object { $_.MainWindowTitle -match "laptop" -or $_.CommandLine -match "laptop/server" } | Stop-Process -Force
```

### Step 4: Expected Timeline in Seconds (Named Waits)

From the moment the Laptop Node is terminated, the system progresses through the following deterministic timeline:

| Elapsed Time | Named Wait / Phase | Node | Actions & State Transitions | Dispatched Alert |
| :---: | :--- | :--- | :--- | :--- |
| **0.0s** | *Injection Moment* | Laptop | Laptop process killed. Last good heartbeat recorded. | None (crash moment is unknown to Phone) |
| **0.0s – 3.0s** | *Heartbeat Interval 1* | Phone | Phone expects heartbeat at 3.0s cadence; missed (1/3). | None |
| **3.0s – 6.0s** | *Heartbeat Interval 2* | Phone | Second expected heartbeat missed (2/3). | None |
| **6.0s – 9.0s** | *Heartbeat Interval 3* | Phone | Third consecutive heartbeat missed (3/3 threshold reached). | None |
| **~9.0s** | **Loss Detection Delay [MEASURED]** | Phone | Phone transitions `SECONDARY_STANDBY` $\rightarrow$ `SUSPECTED_OFFLINE`. Opens incident record `inc-...`. | `[SentinelDR][WARNING][Phone Node] Laptop Node suspected offline` |
| **9.0s – 10.5s** | **Lease & Takeover Wait [MEASURED]** | Phone | Phone transitions to `PROMOTION_PENDING`. Checks bounded clock-skew lease expiry, acquires next epoch lease from Witness, verifies SQLite PRAGMA integrity, and transitions to `SECONDARY_ACTIVE`. | `[SentinelDR][CRITICAL][Phone Node] Phone Node became active (Interim Takeover Report)` |
| **10.5s – 60.0s** | **Outage Primary Active Window [MEASURED]** | Phone | Phone serves portfolio traffic and accepts user inquiries. All mutations are assigned monotonic sequences and logged in `change_log`. | None (normal operational writes) |
| **60.0s** | *Reconnection* | Laptop | Administrator restarts Laptop Node (`python laptop/server.py`). | `[SentinelDR][INFO][Laptop Node] Recovery started` |
| **60.0s – 62.0s** | **Reconciliation Replay Time [MEASURED]** | Laptop | Laptop discovers Phone is `SECONDARY_ACTIVE`, enters `RECOVERING`, takes consistent local backup, replays Phone `change_log` events idempotently. | None |
| **62.0s – 63.5s** | **Integrity Verification Wait [MEASURED]** | Laptop | Validates sequence continuity, table row counts, and canonical SHA-256 data hashes between nodes. Asserts zero conflicts. | None |
| **~65.0s** | **Failback Completion [MEASURED]** | Laptop | Steps down Phone Node to `SECONDARY_STANDBY`. Laptop acquires primary lease and resumes `PRIMARY_ACTIVE`. Incident marked `RESOLVED`. | `[SentinelDR][INFO][Laptop Node] Failback complete - Laptop restored as primary (Final Incident Summary)` |

### Step 5: Checking Audit Logs & Incident Emails Afterwards

#### 1. Checking the SQLite Audit Log on Phone Node (Termux)
```bash
sqlite3 phone_sentineldr.db "SELECT strftime('%Y-%m-%d %H:%M:%S', timestamp, 'unixepoch'), event_type, severity, details FROM audit_log ORDER BY timestamp DESC LIMIT 15;"
```
You will observe:
- `HEARTBEAT_LOSS_DETECTED` (misses: 3)
- `PROMOTION_PENDING_ENTERED`
- `WITNESS_LEASE_REQUEST_SENT`
- `OWNERSHIP_LEASE_PERSISTED`
- `PROMOTION_SUCCESSFUL_SECONDARY_ACTIVE`
- `PEER_RECONCILIATION_CHANGES_SERVED`
- `FAILBACK_STEPDOWN_SECONDARY_STANDBY`

#### 2. Checking the Audit Log on Laptop Node
Query the authenticated events endpoint:
```bash
curl -H "X-SDR-Admin-Key: <YOUR_ADMIN_KEY>" http://localhost:8000/api/v1/events?limit=10
```
You will observe:
- `RECOVERY_STARTED`
- `RECONCILIATION_COMPLETED`
- `RECOVERY_INTEGRITY_VALIDATED`
- `FAILBACK_COMPLETED_PRIMARY_ACTIVE`

#### 3. Checking Incident Emails on Admin Device (Mobile Phone)
Open the **Gmail App** on your Admin Device. You will find:
1. **Interim Alert** (Subject: `[SentinelDR][CRITICAL][Phone Node] Phone Node became active (inc-...)`):
   - Shows Loss Detection Delay (~9.00s [MEASURED])
   - Shows Promotion Takeover Time (~1.50s [MEASURED])
   - Formatted for mobile screens with clear notice that exact crash moment is unknown.
2. **Final Summary Report** (Subject: `[SentinelDR][INFO][Laptop Node] Failback complete - Laptop restored as primary (inc-...)`):
   - Status: `RESOLVED`
   - Complete UTC timeline from heartbeat loss to failback.
   - Durations explicitly labeled `[MEASURED]` vs `[INFERRED]`.
   - Actions performed by Phone Node during outage.
   - Actions performed by Laptop Node during catch-up.
   - Single-writer verification and zero-conflict validation.

