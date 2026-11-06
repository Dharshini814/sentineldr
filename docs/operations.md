# SentinelDR - Operational Guide & Runbooks

## 1. Node Setup & Prerequisites

### 1.1 Laptop Node (Windows 11)
- **Runtime**: Python 3.13+ (64-bit).
- **Database**: PostgreSQL 16+ running on `localhost:5432` (or automatic SQLite development fallback).
- **Ingress**: Port 8000 (`0.0.0.0:8000`).
- **Bootstrap Command**:
  ```cmd
  scripts\setup-laptop.bat
  ```

### 1.2 Phone Node (Android Termux)
- **Runtime**: Python 3.10+ (Termux package `python`).
- **Database**: SQLite 3 (Termux package `sqlite`).
- **Dependencies**: **Zero third-party packages allowed**. Strictly standard library (`http.server`, `sqlite3`, `hashlib`, `urllib`).
- **Ingress**: Port 8001 (`0.0.0.0:8001`).
- **Bootstrap Command**:
  ```bash
  chmod +x scripts/setup-phone.sh
  ./scripts/setup-phone.sh
  ```

---

## 2. Android Termux Operational Survival Guide

Running an operational disaster recovery node on an Android smartphone requires specific OS-level configurations to prevent the kernel from freezing or killing the background process.

### 2.1 Termux Wake-Lock
Android aggressively enters deep sleep (Doze mode) when the screen turns off. To keep the CPU and network stack awake:
```bash
# Acquire wake-lock (included automatically in scripts/setup-phone.sh)
termux-wake-lock
```
To verify that the wake-lock is held, check the Android notification drawer for a persistent notification: *"Termux - wake lock held"*.

### 2.2 Android Battery Optimization Whitelist
1. Open Android **Settings** -> **Apps** -> **Termux**.
2. Select **Battery** (or Battery usage).
3. Set the battery usage mode to **"Unrestricted"** (Do not optimize).
4. On OEM devices with aggressive killers (Xiaomi MIUI/HyperOS, Samsung OneUI, OnePlus OxygenOS, Huawei EMUI):
   - Enable **"Autostart"** / **"Allow background activity"**.
   - Lock the Termux app in the Recent Apps carousel (padlock icon).
   - Disable *"Put unused apps to sleep"*.

### 2.3 Thermal & Power Management
- **Power Connection**: Keep the phone connected to a standard 5V/1A or 5V/2A slow charger. **Avoid high-wattage fast chargers (65W/100W)** while operating as a background server, as fast charging induces battery heat that triggers thermal throttling.
- **Ventilation**: Place the phone on a hard, flat surface (e.g. desk) away from direct sunlight. Do not enclose the phone inside thick silicone cases.
- **Battery Protection**: Enable Android's *"Protect Battery"* feature (caps charging at 80% or 85%) to prevent battery degradation during continuous 24/7 power connection.

### 2.4 Storage Management
- Use internal flash storage for the SQLite database (`~/sentineldr/phone_sentineldr.db`). Avoid external micro-SD cards due to unpredictable I/O latencies and corruption risks during sudden power cuts.
- Monitor disk space periodically:
  ```bash
  df -h $HOME
  ```

---

## 3. Liveness vs Readiness Probes

SentinelDR cleanly separates process liveness from cluster readiness:

| Endpoint | Probe Type | Purpose | HTTP 200 OK | HTTP 503 Unavailable |
| :--- | :--- | :--- | :--- | :--- |
| `GET /health` | **Liveness** | Checks if the HTTP server process is responsive and event loop is healthy. | Server process alive, minimal DB ping succeeds. | Server hung or database driver crashed. |
| `GET /ready` | **Readiness** | Checks if the node is fully initialized, database schema is valid, and ready to accept traffic. | Database healthy, schema intact, cluster state valid. | Database degraded, migrating, or disk full. |

---

## 4. Scheduled Backups & Retention Policy

### 4.1 Laptop PostgreSQL Backup
Create a scheduled task (Windows Task Scheduler) running every 6 hours:
```cmd
@echo off
set BACKUP_DIR=C:\SentinelDR\backups\laptop
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"
set TIMESTAMP=%date:~10,4%%date:~4,2%%date:~7,2%_%time:~0,2%%time:~3,2%%time:~6,2%
set TIMESTAMP=%TIMESTAMP: =0%
pg_dump -U sentinel -h localhost -d sentineldr -F c -b -v -f "%BACKUP_DIR%\laptop_backup_%TIMESTAMP%.dump"
```

### 4.2 Phone SQLite Backup
The SentinelDR database class provides an atomic, online backup mechanism via `db.create_database_backup(backup_dir)` using the SQLite Online Backup API (`conn.backup(backup_conn)`).

To automate on the phone via crontab:
```bash
# Add to termux crontab (crontab -e)
0 */6 * * * python3 -c "from phone.db import PhoneDatabase; from shared.config import NodeConfig; cfg=NodeConfig('phone'); db=PhoneDatabase(cfg.database_path); print(db.create_database_backup('/data/data/com.termux/files/home/sentineldr/backups'))"
```

### 4.3 Retention & Pruning
SentinelDR includes automated backup pruning via `prune_backups(backup_dir, max_keep=7)`:
- Retains the most recent 7 consistent backups.
- Older backup files are safely purged to prevent disk exhaustion.

---

## 5. Log Rotation & Monitoring Alerts

### 5.1 Log Rotation
All nodes write operational logs using `shared.logger.setup_logger()`, configured with standard-library `RotatingFileHandler`:
- **Max File Size**: 10 MB per log file.
- **Backup Count**: 5 rotated log files (`sentineldr.log`, `sentineldr.log.1`, ..., `sentineldr.log.5`).
- **Location**: `logs/sentineldr_{node_id}.log`.

### 5.2 Alert Conditions (`shared/alerts.py`)
The `AlertChecker` continuously evaluates the cluster state and surfaces operational alerts:

1. **`ALERT_SAFE_MODE` (CRITICAL)**: Node entered fail-closed `SAFE_MODE` (dual-writer risk, witness denial, or DB corruption). Writes are strictly blocked.
2. **`ALERT_LEASE_EXPIRED` (CRITICAL)**: Active lease has expired or remaining lease duration is under 5 seconds.
3. **`ALERT_UNRESOLVED_CONFLICTS` (CRITICAL)**: Divergent outbox writes detected in `conflict_records` table requiring operator manual resolution.
4. **`ALERT_INTEGRITY_MISMATCH` (CRITICAL)**: Multi-layer validation or canonical hash parity mismatch detected during failback.
5. **`ALERT_PEER_SUSPECTED_OFFLINE` (WARN)**: Heartbeat missed for 3 consecutive intervals (~9 seconds).
6. **`ALERT_REPLICATION_LAG` (WARN)**: Unreplicated outbox change log items exceed configured threshold (default: 50 items).

---

## 6. Operational Emergency Runbooks

### Runbook 1: Automatic Failover (Laptop Down -> Phone Promoted)
1. **Detection**: Laptop heartbeats cease. Phone accumulates 3 missed heartbeats and transitions from `SECONDARY_STANDBY` to `SUSPECTED_OFFLINE`.
2. **Safety Bounding**: Phone checks laptop's last lease expiry. Phone waits until `now > lease_expires_at + max_clock_skew`.
3. **Witness Arbitration**: Phone requests lease for Epoch $N+1$ from the Witness Quorum (`POST /api/v1/witness/lease/acquire`).
4. **Atomic Promotion**: If approved, Phone persists the lease atomically, executes `PRAGMA integrity_check`, and transitions to `SECONDARY_ACTIVE`.
5. **Edge Routing**: Cloudflare Worker edge router polls `GET /api/v1/active-origin`, detects Phone is writable with a valid lease, and redirects traffic to `backup-origin.sentineldr.in`.

### Runbook 2: Laptop Recovery & Controlled Failback
1. **Boot in Recovering**: Laptop starts in `STATE_RECOVERING`. Protected writes are fenced.
2. **Handshake**: Laptop authenticates Phone, reads Phone's active Epoch $N$ and sequence checkpoints.
3. **Consistent Snapshot**: Both nodes create a consistent backup in `backups/`.
4. **Outbox Catch-Up**: Laptop requests Phone-origin change log events created during the outage (`POST /api/v1/peer/replicate`), applying them idempotently into PostgreSQL (state `RECONCILING`).
5. **Integrity Parity Check**: Reconciler validates sequence ranges, entity counts, constraints, and canonical SHA-256 data hashes across all portfolio tables.
6. **Lease Acquisition**: Laptop acquires Epoch $N+1$ lease from Witness.
7. **Controlled Handoff**: Laptop sends handoff notification to Phone (`POST /api/v1/peer/failback/handoff`). Phone steps down to `SECONDARY_STANDBY`. Laptop transitions to `PRIMARY_ACTIVE`.

### Runbook 3: Emergency Break-Glass Safe Mode Recovery
If a node enters `SAFE_MODE` (e.g. witness network failure during a real disaster):
1. **Investigate Cause**:
   ```bash
   # Check active alerts and last audit events
   curl -H "Authorization: Bearer <ADMIN_KEY>" http://127.0.0.1:8000/api/v1/events
   ```
2. **Verify Quorum Reachability**: Ensure Witness server is reachable at `http://127.0.0.1:8002/health`.
3. **Operator Override Transition**:
   To manually clear Safe Mode and assign ownership after resolving the physical network:
   ```bash
   curl -X POST http://127.0.0.1:8000/api/v1/peer/failover \
     -H "Authorization: Bearer <ADMIN_KEY>" \
     -H "Content-Type: application/json" \
     -d '{"action": "FORCE_SAFE_RESET", "target_state": "PRIMARY_ACTIVE", "epoch": <NEXT_EPOCH>}'
   ```

### Runbook 4: Resolving Divergent Write Conflicts
If concurrent conflicting writes occurred under an edge-case network partition, they are preserved safely in the `conflict_records` table:
1. **Query Conflicts**:
   ```sql
   SELECT conflict_id, entity_type, entity_id, origin_node_id, local_data, remote_data, detected_at
   FROM conflict_records WHERE resolved = 0;
   ```
2. **Inspect and Select Canonical Version**: Review the JSON payloads of `local_data` and `remote_data`.
3. **Apply Resolution**:
   ```sql
   UPDATE portfolio_inquiries SET ... WHERE id = '<entity_id>';
   UPDATE conflict_records SET resolved = 1, resolution_notes = 'Operator manual resolution by <username>' WHERE conflict_id = '<conflict_id>';
   ```
4. **Resume Failback**: Once unresolved conflict count reaches 0, failback can proceed.

---

## 7. Credential Rotation Playbook

To rotate secrets in production without causing service interruption:

| Secret | Environment Variable | Affected Services | Rotation Strategy |
| :--- | :--- | :--- | :--- |
| **Peer HMAC Secret** | `SDR_HMAC_SECRET` | Laptop, Phone | Dual-secret transition window: Update `.env` on Phone first, reload, then update Laptop. |
| **Admin API Key** | `SDR_ADMIN_KEY` | Laptop, Phone, Monitoring | Update `.env` and restart monitoring agents with new bearer token. |
| **Witness Secret** | `SDR_WITNESS_SECRET` | Laptop, Phone, Witness | Update Witness server first, then update Laptop and Phone configs. |
| **PostgreSQL Password** | `DATABASE_URL` | Laptop | Run `ALTER USER sentinel WITH PASSWORD '...';`, update `.env`, restart Laptop server. |
| **Cloudflare API Token**| `CLOUDFLARE_API_TOKEN` | Edge Worker | Generate new scoped API token in Cloudflare dashboard, update `wrangler secret put`. |

---

## 8. Witness Service Production Architecture & Deployment

### 8.1 Production Role & Independence
In a two-node disaster recovery system (Laptop and Phone), an independent witness is essential to solve the **two-node split-brain problem**:
- **Why It Is Independent of Both Nodes:** In a pure two-node topology, an asymmetric network partition (e.g. Wi-Fi drops on the laptop, or ISP routing failure) prevents the two nodes from communicating. Without a third entity, neither node can determine whether the other node is dead or alive. If the phone promotes itself based only on missing heartbeats, and the laptop is still running, **both nodes become writable primaries**, leading to irreversible data divergence.
- **Quorum Arbitration:** The Witness resides in a **third, independent failure domain**. A cluster majority requires 2 out of 3 participants (`Node + Witness`). The Witness maintains monotonic epochs and signs a single active lease at any time. When a partition occurs, only the node that can reach the Witness and verify that the peer's lease has expired can be granted the writable lease.
- **Behavior When Unreachable (Fail-Closed):**
  - If the Witness is down or unreachable by the Phone during a failover attempt, the Phone **strictly refuses to promote itself** and enters `STATE_SAFE_MODE` (read-only).
  - If the Laptop is currently primary and cannot reach the Witness to renew its expiring lease, the Laptop's lease expires upon reaching `lease_expires_at` (maximum 120s), and the Laptop's write guard immediately begins rejecting all incoming writes with HTTP 403 Forbidden.
  - **Result:** Under Witness failure, the entire system **fails closed into read-only mode**, guaranteeing zero dual-writer states.

### 8.2 Deployment Targets
The Witness service is lightweight and standard-library based (`shared/witness.py`). It requires no database (operates in-memory or with a lightweight JSON state file) and should be deployed to a low-cost, high-availability cloud target:
1. **Target A: Standalone Cloud VM / Container (Fly.io / AWS EC2 / Hetzner / DigitalOcean):**
   - Single container running `python -m shared.witness`.
2. **Target B: Serverless Cloudflare Worker with KV / D1:**
   - Translates witness HMAC lease signing into a Cloudflare Worker at `witness.sentineldr.in`.

### 8.3 Step-by-Step Deployment (Linux Systemd / Docker)

#### Option 1: Systemd Service on Linux VPS
1. **Clone repository and set environment:**
   ```bash
   sudo mkdir -p /opt/sentineldr-witness
   sudo chown -R ubuntu:ubuntu /opt/sentineldr-witness
   cd /opt/sentineldr-witness
   # Copy shared/ directory and requirements
   ```
2. **Create environment file (`/etc/sentineldr-witness.env`):**
   ```ini
   SDR_CLUSTER_ID=sentineldr-cluster-01
   SDR_WITNESS_PORT=8002
   SDR_WITNESS_SECRET=your_32_byte_witness_secret_hex_here
   ```
3. **Create systemd unit file (`/etc/systemd/system/sentineldr-witness.service`):**
   ```ini
   [Unit]
   Description=SentinelDR Quorum Witness Service
   After=network.target

   [Service]
   Type=simple
   User=ubuntu
   WorkingDirectory=/opt/sentineldr-witness
   EnvironmentFile=/etc/sentineldr-witness.env
   ExecStart=/usr/bin/python3 -m shared.witness --port 8002
   Restart=always
   RestartSec=3

   [Install]
   WantedBy=multi-user.target
   ```
4. **Enable and start service:**
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now sentineldr-witness
   sudo systemctl status sentineldr-witness
   ```
5. **Verify Health Endpoint:**
   ```bash
   curl http://<witness-ip-or-domain>:8002/health
   # Expected: {"ok": true, "data": {"status": "HEALTHY", "service": "witness"}, ...}
   ```

#### Option 2: Docker Container
```bash
docker run -d \
  --name sentineldr-witness \
  --restart always \
  -p 8002:8002 \
  -e SDR_CLUSTER_ID=sentineldr-cluster-01 \
  -e SDR_WITNESS_SECRET=your_32_byte_witness_secret_hex_here \
  python:3.13-slim \
  python -c "from shared.witness import main; main()"
```
