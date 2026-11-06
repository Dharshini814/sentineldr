# SentinelDR - Ownership, Leases, and Fencing Architecture

## 1. Overview & Choice of Mechanism

In accordance with Phase 5 requirements, SentinelDR enforces the core invariant:
> **Never allow two writable primaries.** If ownership cannot be proven, fail closed into `SAFE_MODE` (read-only). A shared secret plus two local epoch counters is **not** a witness.

SentinelDR employs **Option A: Independent Witness / Quorum Service**. An external, independent arbiter acts as the third quorum member to grant and deny cryptographically signed, time-bounded, monotonic epoch write leases.

```
       +-------------------------------------------------------------+
       |               Independent Witness Service                   |
       |  - Tracks monotonic epoch (N -> N+1)                        |
       |  - Grants time-bounded HMAC-signed write leases             |
       |  - Denies candidate B if candidate A holds unexpired lease  |
       +-------------------------------------------------------------+
                        ^                           ^
     Lease Heartbeat /  |                           |  Lease Acquire /
     Renew (HTTPS)      |                           |  Failover (HTTPS)
                        v                           v
         +-----------------------+         +-----------------------+
         |      Laptop Node      | ======= |      Phone Node       |
         |     (Primary Active)  |  LAN/WAN|    (Secondary Standby)|
         |  Holds Lease @ Epoch 1|Heartbeat|   Observes Missed Beats|
         +-----------------------+         +-----------------------+
```

---

## 2. Ownership Record Specification

The `OwnershipRecord` is persisted atomically in SQLite (`phone`) and PostgreSQL/SQLite (`laptop`) within the `ownership` table:

| Field | Type | Description |
|---|---|---|
| `cluster_id` | `TEXT PRIMARY KEY` | Cluster identifier (e.g. `sentineldr-cluster-01`). |
| `owner_node_id` | `TEXT NOT NULL` | Node ID authorized to accept writes (`laptop` or `phone`). |
| `epoch` | `INTEGER NOT NULL` | Monotonically increasing generation number. |
| `lease_id` | `TEXT NOT NULL` | Cryptographic UUID uniquely identifying this lease grant. |
| `lease_expires_at` | `REAL NOT NULL` | Unix epoch timestamp when lease expires. |
| `granted_by` | `TEXT NOT NULL` | Granting authority (`witness` or `bootstrap`). |
| `signature` | `TEXT NOT NULL` | HMAC-SHA256 hex digest proving record authenticity. |
| `updated_at` | `REAL NOT NULL` | Local update timestamp. |

### Cryptographic Signature Verification
Canonical string:
$$\text{canonical} = \text{cluster\_id} : \text{owner\_node\_id} : \text{epoch} : \text{lease\_id} : \text{lease\_expires\_at}_{.3f} : \text{granted\_by}$$
Signature is verified in constant time (`hmac.compare_digest`).

---

## 3. How the Witness Grants and Denies Leases

The Witness evaluates all lease requests (`POST /api/v1/witness/lease/acquire`) under three strict mathematical invariants:

1. **Active Primary Protection (Denial):**
   If Candidate $B$ requests a lease while Node $A$ holds an unexpired lease ($\text{now} < \text{lease\_expires\_at}$), the Witness **denies** Candidate $B$ with `409 Conflict` (`LEASE_HELD_BY_ACTIVE_PRIMARY`).
2. **Safe Failover After Expiration (Grant):**
   If Node $A$'s lease has expired ($\text{now} \ge \text{lease\_expires\_at}$), Node $B$ is granted the lease. The Witness advances the epoch monotonically:
   $$\text{epoch}_{new} = \max(\text{current\_epoch} + 1, \text{requested\_epoch})$$
   Any subsequent renewal attempts by Node $A$ with epoch $\le N$ are rejected.
3. **Owner Renewal:**
   If the current owner renews before expiration, the lease duration is extended without incrementing the epoch.
4. **Voluntary Release:**
   During a planned maintenance or failover, the current owner calls `POST /api/v1/witness/lease/release`, freeing the lease immediately.

---

## 4. Bounded Clock-Skew Policy

Distributed systems must never trust an unbounded local clock. SentinelDR enforces a two-tier clock guard:

1. **Peer Request Skew Guard:**
   `POST /api/v1/peer/lease/request` requires a `sent_at` timestamp. If:
   $$|t_{local} - t_{peer}| > \text{SDR\_MAX\_CLOCK\_SKEW} \quad (\text{default } 2.0\text{s})$$
   the request is rejected with `400 Bad Request` (`CLOCK_SKEW_EXCEEDED`).
2. **Receiver Clock Lease Expiration Guard:**
   When verifying write leases, the local write guard tests:
   $$t_{local} + \text{max\_clock\_skew} < \text{lease\_expires\_at}$$
   Even if the local clock drifts forward by up to $1.0\text{s}$, the lease must remain valid. If it fails, the node fails closed.

---

## 5. Genuine Write Guard on Every Protected Write

The Phase 3 boolean placeholder (`is_primary`) is replaced with an enforced multi-layered write guard in `protected_write`:

1. **State Machine Verification:** Node role must be `PRIMARY_ACTIVE` or `SECONDARY_ACTIVE`.
2. **Ownership Record Check:** Active record in `ownership` table must match:
   - `owner_node_id == origin_node_id`
   - `epoch == origin_epoch`
   - `cluster_id == SDR_CLUSTER_ID`
   - Signature is valid.
3. **Lease Validity Check:** Current time plus skew bound must not exceed `lease_expires_at`.
4. **Atomic Outbox Insert:** Data change and outbox change occur in the exact same transaction. Any failure rolls back the entire operation.

---

## 6. Cluster State Machine

SentinelDR enforces a strict 10-state machine:

| State | Description | Can Write? |
|---|---|---|
| `STARTING` | Bootstrapping process and validating DB readiness | No |
| `PRIMARY_ACTIVE` | Active writable primary holding valid lease | **Yes** (with valid lease) |
| `SECONDARY_STANDBY` | Passive read-only standby receiving replication | No |
| `SUSPECTED_OFFLINE` | Peer has missed $\ge 3$ consecutive heartbeats | No |
| `PROMOTION_PENDING` | Requesting lease from Witness | No |
| `SECONDARY_ACTIVE` | Promoted secondary holding Witness lease | **Yes** (with valid lease) |
| `RECOVERING` | Primary node restarting after outage | No |
| `RECONCILING` | Catching up outbound/inbound replication | No |
| `FAILBACK_PENDING` | Ready to transition back to normal roles | No |
| `SAFE_MODE` | Fail-closed state when witness is unreachable | No |

### Illegal Transition Enforcement
Any transition not present in the transition graph is rejected with `ILLEGAL_TRANSITION`. Every transition emits an audit log event into `audit_events`.
