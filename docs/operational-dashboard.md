# SentinelDR — Operational Telemetry Dashboard Specification (Phase 8)

## 1. Overview & Architecture

SentinelDR provides honest, live, runtime-neutral operational visibility across both cluster nodes (Laptop Primary and Phone Secondary) via a single-page telemetry dashboard (`frontend/dashboard.html`).

The dashboard is engineered with zero external dependencies (pure vanilla HTML5, CSS3, and modern ECMAScript), ensuring complete offline functionality in partitioned or disaster recovery environments.

```
                      +-----------------------------+
                      |   frontend/dashboard.html   |
                      |  (Browser Single Page App)  |
                      +--------------+--------------+
                                     |
              +----------------------+----------------------+
              | Polls every 3.5s                            | Polls every 3.5s
              | Timeout 2.5s                                | Timeout 2.5s
              v                                             v
  +-----------------------+                     +-----------------------+
  |  Laptop Primary Node  |                     |  Phone Secondary Node |
  |      (Port 8000)      |                     |      (Port 8001)      |
  |  FastAPI / PostgreSQL |                     |  http.server / SQLite |
  +-----------------------+                     +-----------------------+
              |                                             |
              +-- GET /dashboard or /dashboard.html         +-- GET /dashboard or /dashboard.html
              +-- GET /api/v1/dashboard/status              +-- GET /api/v1/dashboard/status
              +-- GET /api/v1/dashboard/events              +-- GET /api/v1/dashboard/events
```

---

## 2. Telemetry Contract (`GET /api/v1/dashboard/status`)

Both nodes expose identical unprivileged status contracts under `GET /api/v1/dashboard/status`:

```json
{
  "ok": true,
  "data": {
    "cluster_id": "sentineldr-cluster-01",
    "node_id": "laptop",
    "node_type": "laptop",
    "role": "PRIMARY_ACTIVE",
    "epoch": 1,
    "db_ready": true,
    "db_healthy": true,
    "uptime_seconds": 142.5,
    "ownership": {
      "owner_node_id": "laptop",
      "epoch": 1,
      "safety_status": "VALID",
      "remaining_seconds": 45.2,
      "granted_by": "witness"
    },
    "heartbeat": {
      "elapsed_seconds": 1.2,
      "consecutive_misses": 0,
      "suspected_offline": false
    },
    "replication": {
      "highest_local_sequence": 14,
      "peer_applied_sequence": 14,
      "lag": 0,
      "pending_outbox_count": 0
    },
    "recovery": {
      "phase": "PRIMARY_ACTIVE",
      "unresolved_conflicts": 0,
      "integrity_status": "POSTGRES_OK"
    },
    "connectivity": {
      "peer_api_reachability": "ONLINE"
    }
  },
  "request_id": "req-...",
  "node_id": "laptop",
  "epoch": 1
}
```

---

## 3. Public Sanitized Audit Stream (`GET /api/v1/dashboard/events`)

The dashboard streams recent audit records from `audit_events` through `GET /api/v1/dashboard/events`.

### Redaction & Boundary Enforcement:
- Unprivileged endpoint accessible from approved origins.
- Sensitive keys (`secret`, `key`, `password`, `token`, `signature`, `auth`, `credential`) are automatically masked with `[REDACTED]`.
- Active secrets (`hmac_secret`, `admin_key`, `witness_secret`) are scrubbed from string payloads and detail blocks before transmission.
- Private keys, signing material, and internal tokens never reach the browser under any condition.

---

## 4. UI Layout & Panels

The dashboard features eight dedicated operational areas:

1. **Global Cluster Status Pill & Active Alert Banner**:
   - `CLUSTER HEALTHY` (green dot) when both nodes are online.
   - `DEGRADED (1 NODE DOWN)` (orange dot) with contextual alert banner explaining failover/fencing state.
   - `ALL NODES OFFLINE` (red pulsing dot) with critical warning.
2. **Node Cards (Laptop Primary & Phone Secondary)**:
   - Dedicated statuses: `ONLINE`, `OFFLINE`, `STALE DATA` (>8s latency), or `UNKNOWN`.
   - Live telemetry: endpoint, cluster role, monotonic epoch, database health, uptime.
3. **Ownership & Lease Fencing Panel**:
   - Active owner, epoch, safety status (`VALID`, `EXPIRED`, `SAFE_MODE_FENCED`), remaining lease duration, grantor (`witness`).
4. **Heartbeat & Failure Detection Panel**:
   - Expected interval (3.0s), elapsed time since last beat, consecutive misses, failure threshold (3 misses / 9.0s), failure detection decoupled from promotion.
5. **Replication & Outbox Pipeline Panel**:
   - Committed sequence, peer applied sequence, lag count, pending outbox events, deduplication enforcement indicator.
6. **Recovery & Reconciliation Panel**:
   - Cluster phase, unresolved conflicts count, database physical integrity status (`PRAGMA_OK` / `POSTGRES_OK`), backup retention status (7-day window).
7. **Connectivity & Ingress Panel**:
   - Direct Peer API Reachability (`ONLINE` / `OFFLINE` / `STANDBY`) distinct from Cloudflare Tunnel status (`NOT_CONFIGURED` awaiting Phase 9).
8. **Live Audit Events Stream**:
   - Timestamped table showing node, epoch, severity badge (`INFO`, `WARN`, `CRITICAL`), event type, and redacted detail metadata.

---

## 5. Security & CORS Origin Policy

To prevent cross-site request forgery and data exfiltration while allowing the dual-node dashboard to query both endpoints:
- Wildcard CORS (`*`) with credentials is explicitly forbidden.
- Origin matching is strictly enforced against `ALLOWED_ORIGINS`:
  - `http://localhost:8000`
  - `http://127.0.0.1:8000`
  - `http://localhost:8001`
  - `http://127.0.0.1:8001`
- Unapproved origins receive 403 or no `Access-Control-Allow-Origin` header.

---

## 6. Truthfulness Guarantees

In accordance with SentinelDR's core architectural tenets:
1. **Never Fabricate Values**: If a node or metric is unreachable, the dashboard renders `"unavailable"` styled with `.val-unavailable`. Missing data is never coerced to `0` or fake healthy stats.
2. **Data Age Tracking**: Each node card records its last successful payload timestamp. If background polling is blocked or delayed beyond 8 seconds, the badge immediately updates to `STALE DATA`.
3. **Non-Overlapping Polling**: An in-flight lock (`state.isPolling`) and `AbortController` (2500ms timeout) prevent socket starvation, thread pool exhaustion, or queued requests piling up during network hiccups.
