# SentinelDR - System Architecture Document

## 1. System Overview & Philosophy

**SentinelDR** is a resilient, two-node disaster recovery (DR) architecture for a production portfolio web application. It bridges a high-performance Windows development machine (Laptop) and an ultra-low-power, always-on Android smartphone running Termux (Phone), arbitrated by an independent lightweight witness service and fronted by a dynamic Cloudflare Worker edge router.

### Core Philosophy & Invariant Rules
1. **Never Allow Dual Writable Primaries**: Under network partitions, hardware crashes, or clock drift, at most one node is legally permitted to accept user writes. If ownership safety cannot be proven, the system must **fail closed** into read-only `SAFE_MODE`.
2. **Asymmetric Engineering**:
   - **Laptop Node**: Windows 11, Python 3.13+, FastAPI, Pydantic, PostgreSQL (with automatic SQLite development fallback), Port 8000.
   - **Phone Node**: Android Termux, Python Standard Library `http.server` only, SQLite only, Port 8001. Strictly zero third-party dependencies.
3. **No Short-Cut Data Erasure**: Phone-origin writes committed during failover are first-class, durable citizens. Recovery must reconcile them idempotently into PostgreSQL without overwriting or skipping acknowledged changes.
4. **Zero Report-Generation Feature**: SentinelDR is strictly an operational disaster-recovery and portfolio serving platform. Any reporting engine (PDF, CSV, docx, analytics report generation) is an explicit anti-feature and strictly forbidden.

---

## 2. High-Level Topology

```mermaid
flowchart TD
    User([Public User / Browser]) --> CF[Cloudflare Worker Router\nportfolio.sentineldr.in]
    Operator([Operator / Dashboard]) --> Laptop[Laptop Node :8000\nWindows 11 / FastAPI\nPostgreSQL]
    Operator --> Phone[Phone Node :8001\nAndroid Termux / stdlib\nSQLite]

    subgraph Edge Layer
        CF
    end

    subgraph Primary Site [Primary Site - Laptop]
        Laptop --> LaptopDB[(PostgreSQL / SQLite)]
    end

    subgraph Backup Site [Backup Site - Phone]
        Phone --> PhoneDB[(SQLite)]
    end

    subgraph Quorum Witness
        Witness[Witness Quorum Service :8002\nEphemeral / Dedicated Port]
    end

    CF -- Active Origin Routing\n(Public Traffic Only) --> Laptop
    CF -. Failover Routing .-> Phone
    Laptop <-- Bidirectional Outbox Replication --> Phone
    Laptop -- Heartbeat (~3s) --> Phone
    Laptop <-- HMAC Lease Arbitration --> Witness
    Phone <-- HMAC Lease Arbitration --> Witness
```

---

## 3. Protocol & Security Specifications

### 3.1 Standard Response Envelope
All API endpoints across both nodes return a uniform JSON envelope adhering strictly to the contract defined in `shared/api_contract.py` and `shared/protocol.py`:

```json
{
  "ok": true,
  "data": { ... },
  "error": null,
  "meta": {
    "node_id": "laptop",
    "epoch": 1,
    "timestamp": 1741170000.123
  }
}
```

On error, `"ok": false`, `"data": null`, and `"error"` contains `{ "code": "...", "message": "...", "details": ... }`.

### 3.2 Peer Authentication & Anti-Replay
All peer-to-peer administrative endpoints (`/api/v1/peer/*`) require cryptographic authentication:
- **Headers Required**:
  - `X-SDR-Node`: Sending node identifier (`laptop`, `phone`, or `witness`).
  - `X-SDR-Epoch`: Monotonic cluster epoch.
  - `X-SDR-Timestamp`: Unix epoch timestamp with decimal precision.
  - `X-SDR-Nonce`: 16+ byte hexadecimal random nonce.
  - `X-SDR-Signature`: SHA256 HMAC calculated over:
    `METHOD\nPATH\nTIMESTAMP\nNONCE\nSHA256(BODY)`
- **Persistent Nonce Cache**: Every node maintains a dedicated SQLite table `nonce_cache (nonce, timestamp, node_id, PRIMARY KEY(nonce))` with a 30-second sliding expiration window. Replayed nonces or timestamps outside `now ± 30.0s` are immediately rejected with HTTP 401.

### 3.3 Public Cloudflare Boundary
- Public access to `/api/v1/peer/*` is blocked with HTTP 403 Forbidden at the Cloudflare Worker edge.
- Server-side verification on both nodes strictly requires valid HMAC signatures or Admin Bearer tokens, providing defense-in-depth even if origin ports are directly probed.

---

## 4. State Machine & Ownership Model

The cluster operates under a formal finite state machine defined in `shared/state_machine.py`:

```mermaid
stateDiagram-v2
    [*] --> STARTING
    STARTING --> PRIMARY_ACTIVE: Lease Granted (Laptop)
    STARTING --> SECONDARY_STANDBY: Bootstrapped (Phone)
    STARTING --> RECOVERING: Recovery Boot
    STARTING --> SAFE_MODE: Quorum/DB Failure

    PRIMARY_ACTIVE --> SUSPECTED_OFFLINE: Missed Heartbeats
    PRIMARY_ACTIVE --> RECOVERING: Reboot / Self-Fence
    PRIMARY_ACTIVE --> SAFE_MODE: Invariant Violation

    SECONDARY_STANDBY --> SUSPECTED_OFFLINE: 3x Missed Beats
    SECONDARY_STANDBY --> SAFE_MODE: Invariant Violation

    SUSPECTED_OFFLINE --> SECONDARY_STANDBY: Heartbeat Resumed
    SUSPECTED_OFFLINE --> PROMOTION_PENDING: Lease Expired + Witness Grant
    SUSPECTED_OFFLINE --> SAFE_MODE: Witness Denied / Unreachable

    PROMOTION_PENDING --> SECONDARY_ACTIVE: Integrity OK + Atomic Lease Persisted
    PROMOTION_PENDING --> SAFE_MODE: Corruption / Conflict Detected

    SECONDARY_ACTIVE --> FAILBACK_PENDING: Operator Handoff Initiated
    SECONDARY_ACTIVE --> SAFE_MODE: Dual-Writer Risk

    RECOVERING --> RECONCILING: Handshake + Backups Created
    RECONCILING --> FAILBACK_PENDING: Replay Complete + Parity Verified
    RECONCILING --> SAFE_MODE: Conflict / Integrity Failure

    FAILBACK_PENDING --> PRIMARY_ACTIVE: Laptop Resumes Primary
    FAILBACK_PENDING --> SECONDARY_STANDBY: Phone Steps Down
```

### 4.1 Ownership Records & Bounded Clock Skew
An `OwnershipRecord` comprises:
`cluster_id`, `owner_node_id`, `epoch` (strictly monotonic integer), `lease_id`, `lease_expires_at` (Unix timestamp), `granted_by` (`witness` or peer), and `signature`.

- **Atomic Persistence**: Before any node can transition to a writable role, the new ownership record must be committed to the database in a dedicated transaction.
- **Clock Skew Bounding**: Nodes enforce `max_clock_skew = 2.0s`. If a lease request or write occurs when local clock differs from lease timestamps beyond this bound, the request is rejected.
- **Genuine Write Guards**: Every protected write (such as portfolio inquiries) executes inside a transaction that verifies:
  1. `state_machine.is_writable() == True`
  2. Database lease record is valid, non-expired (`now <= lease_expires_at`), matching current epoch, with `owner_node_id == this_node`.

---

## 5. Replication & Failback Pipeline

```mermaid
sequenceDiagram
    autonumber
    participant U as User / Cloudflare
    participant L as Laptop (Primary)
    participant P as Phone (Standby)
    participant W as Witness Quorum

    Note over L,P: Normal Operation (Epoch 1)
    U->>L: POST /api/v1/portfolio/inquiry
    L->>L: Protected Write: Commit DB + Outbox (change_log) atomically
    L-->>U: 201 Created (operation_id)
    L->>P: POST /api/v1/peer/replicate (Batch of change_log events)
    P->>P: Deduplicate op_id + Validate sequence monotonicity + Apply DB
    P-->>L: 200 OK (ACK highest sequence)

    Note over L,W: Laptop Failure & Failover
    L-xP: Heartbeat drops for 3 intervals (9 seconds)
    P->>P: Transition SECONDARY_STANDBY -> SUSPECTED_OFFLINE
    P->>P: Check last lease expiry (wait until now > expires_at + skew)
    P->>W: POST /api/v1/witness/lease/acquire (Epoch 2)
    W-->>P: 200 OK (Signed Lease Epoch 2)
    P->>P: PRAGMA integrity_check + Atomic lease commit
    P->>P: Transition -> SECONDARY_ACTIVE

    Note over U,P: Failover Operation (Epoch 2)
    U->>P: POST /api/v1/portfolio/inquiry
    P->>P: Protected Write: Commit DB + Outbox atomically
    P-->>U: 201 Created

    Note over L,P: Recovery & Failback (Epoch 3)
    L->>L: Boots in RECOVERING (fenced/read-only)
    L->>P: Authenticate & Obtain Phone Epoch 2 Checkpoint
    L->>L: Create PostgreSQL Backup (pg_dump / snapshot)
    P->>P: Create SQLite Backup
    L->>P: Fetch Phone Outbox changes (Epoch 2)
    L->>L: Transition RECONCILING -> Replay events idempotently into PostgreSQL
    L->>L: Validate 6-layer parity: sequences, op counts, canonical hash
    L->>W: Acquire Epoch 3 Lease for Laptop
    W-->>L: Signed Lease Epoch 3
    L->>P: Notify Failback Handoff (Epoch 3 Lease)
    P->>P: Step down to SECONDARY_STANDBY
    L->>L: Transition to PRIMARY_ACTIVE
```

---

## 6. Anti-Feature Verification

| Component | Status | Verification Mechanism |
| :--- | :--- | :--- |
| **PDF Reporting** | ABSENT | Codebase grep confirms zero imports of `reportlab`, `fpdf`, `weasyprint`. |
| **CSV Export Engine** | ABSENT | No CSV file generation endpoints exist on either node. |
| **Docx / Office Generators** | ABSENT | No `python-docx` or office libraries present in dependencies or code. |
| **Automated Report Schedulers** | ABSENT | Background tasks are strictly limited to heartbeat and outbox replication. |
