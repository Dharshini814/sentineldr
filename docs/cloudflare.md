# SentinelDR — Cloudflare Routing & Ingress Guide (Phase 9)

## 1. Overview & Architecture

SentinelDR routes public traffic through Cloudflare's edge to provide high availability and instantaneous disaster recovery failover between the **Laptop Primary** (`localhost:8000`) and the **Phone Secondary** (`localhost:8001`).

```
                              Public Internet
                                     |
                                     v
                       https://portfolio.sentineldr.in
                                     |
                  +--------------------------------------+
                  |   Cloudflare Worker (Edge Router)    |
                  |     cloudflare/worker.js             |
                  |                                      |
                  | - Blocks /api/v1/peer/* (403)        |
                  | - Checks /api/v1/active-origin       |
                  | - Fences writes if in Standby/Safe   |
                  +------------------+-------------------+
                                     |
                  +------------------+------------------+
                  |                                     |
                  v                                     v
   https://primary-origin.sentineldr.in   https://backup-origin.sentineldr.in
                  |                                     |
          [cloudflared tunnel]                  [cloudflared tunnel]
                  |                                     |
                  v                                     v
      Laptop Node (Windows)                 Phone Node (Android Termux)
           Port 8000                             Port 8001
      FastAPI / PostgreSQL                  http.server / SQLite
      Role: PRIMARY_ACTIVE                  Role: SECONDARY_STANDBY
```

---

## 2. Core Operational Guarantees

1. **Tunnel Health Alone Never Selects a Non-Owner**:
   - Cloudflare Tunnels maintain active outbound connections on both Laptop and Phone. A healthy tunnel on the Phone node while in `SECONDARY_STANDBY` or `SAFE_MODE` **never** receives write traffic.
   - The Cloudflare Worker directly queries `GET /api/v1/active-origin` to inspect `role`, `epoch`, and cryptographic `lease_valid` before proxying requests.
2. **Perimeter Defense**:
   - All internal peer replication and cluster consensus endpoints (`/api/v1/peer/*`: heartbeat, replicate, lease, failover, recovery, failback) are intercepted and dropped at Cloudflare's edge with `403 Forbidden`.
   - In addition, origin servers require HMAC-SHA256 signatures, timestamps, and persistent nonces on all peer endpoints as defense-in-depth.
3. **Read / Write Splitting During Safe Mode**:
   - If the cluster enters `SAFE_MODE` or no writable primary holds a valid lease, read-only visitors (`GET /`, `GET /api/v1/portfolio/*`) can still view the cached or replica portfolio.
   - Any user-generated write mutation (`POST /api/v1/portfolio/inquiry`) is rejected at the edge with `503 Service Unavailable` and a SentinelDR error envelope, guaranteeing zero dual-writers and zero lost writes.
4. **Origin Isolation**:
   - The diagnostic hostnames `primary-origin.sentineldr.in` and `backup-origin.sentineldr.in` remain active and unchanged for administration, direct diagnostics, and witness replication.

---

## 3. Implementation Breakdown

### Components Implemented in Codebase:
| Component | Location | Description |
| :--- | :--- | :--- |
| **Edge Router Script** | `cloudflare/worker.js` | Cloudflare Worker intercepting `portfolio.sentineldr.in/*`, evaluating `/api/v1/active-origin`, blocking peer routes, and proxying requests. |
| **Wrangler Configuration** | `cloudflare/wrangler.toml` | Deployment manifest with environment variables and route binding to zone `sentineldr.in`. |
| **Active-Origin Endpoint (Laptop)** | `laptop/server.py` | `GET /api/v1/active-origin` returning role, epoch, lease validity, and writable flag. |
| **Active-Origin Endpoint (Phone)** | `phone/server.py` | `GET /api/v1/active-origin` (100% standard library + SQLite). |
| **CORS Origins** | `shared/api_contract.py` | Restricts CORS headers strictly to `portfolio.sentineldr.in` and origin hosts. |
| **Local Worker Simulation** | `cloudflare/mock_worker.py` | Deterministic Python emulator of the edge router used for automated unit/integration testing. |
| **Routing Test Suite** | `tests/test_cloudflare_routing.py` | Automated tests verifying active-owner routing, healthy-tunnel non-owner rejection, peer endpoint blocking, and CORS. |

---

## 4. Remaining Account-Side Infrastructure Tasks (Manual Steps)

The following steps require your Cloudflare credentials and access to the Cloudflare Web Dashboard.

### Step 1: Zone Setup
1. Log in to the [Cloudflare Dashboard](https://dash.cloudflare.com).
2. Ensure your domain `sentineldr.in` is active with Cloudflare nameservers.

### Step 2: Configure Cloudflare Tunnels (`cloudflared`)
You need two tunnels (one on Laptop, one on Phone):

#### A. Laptop Tunnel Setup (Windows):
```powershell
# 1. Download and authenticate cloudflared
cloudflared tunnel login

# 2. Create the tunnel
cloudflared tunnel create sentineldr-laptop

# 3. Associate tunnel with primary origin hostname
cloudflared tunnel route dns sentineldr-laptop primary-origin.sentineldr.in

# 4. Create config file at ~/.cloudflared/config.yml:
tunnel: <TUNNEL_UUID>
credentials-file: C:\Users\<USER>\.cloudflared\<TUNNEL_UUID>.json

ingress:
  - hostname: primary-origin.sentineldr.in
    service: http://localhost:8000
  - service: http_status:404

# 5. Run the tunnel service
cloudflared tunnel run sentineldr-laptop
```

#### B. Phone Tunnel Setup (Android Termux):
```bash
# 1. Install cloudflared in Termux (or use arm64 binary)
pkg install cloudflared

# 2. Login and create backup tunnel
cloudflared tunnel login
cloudflared tunnel create sentineldr-phone

# 3. Associate tunnel with backup origin hostname
cloudflared tunnel route dns sentineldr-phone backup-origin.sentineldr.in

# 4. Configure ~/.cloudflared/config.yml:
tunnel: <TUNNEL_UUID>
credentials-file: /data/data/com.termux/files/home/.cloudflared/<TUNNEL_UUID>.json

ingress:
  - hostname: backup-origin.sentineldr.in
    service: http://localhost:8001
  - service: http_status:404

# 5. Run the tunnel
cloudflared tunnel run sentineldr-phone
```

---

### Step 3: Deploy the Cloudflare Worker

From the repository root on your laptop:

```bash
# 1. Install Wrangler (if not already installed)
npm install -g wrangler

# 2. Authenticate with Cloudflare
wrangler login

# 3. Deploy the worker from the cloudflare directory
cd cloudflare
wrangler deploy
```

#### Configuring Worker Environment Variables (Optional Edge Secret):
If you wish to inject an edge routing secret so origins verify requests passed through the Worker:
```bash
wrangler secret put EDGE_ROUTING_SECRET
# Enter a secure 32-character string when prompted
```

---

### Step 4: Defense-in-Depth Cloudflare WAF Rule (Optional but Recommended)
In Cloudflare Dashboard $\rightarrow$ `sentineldr.in` $\rightarrow$ **Security** $\rightarrow$ **WAF** $\rightarrow$ **Custom Rules**:
- **Rule Name**: `Block Peer Replication Endpoints on Public Host`
- **Expression**:
  `(http.host eq "portfolio.sentineldr.in" and http.request.uri.path contains "/api/v1/peer/")`
- **Action**: `Block` (HTTP 403)

---

## 5. Verification & Telemetry Testing

Once the tunnels and Worker are active, verify the routing behavior:

```bash
# 1. Verify Active Origin on Laptop
curl -s https://primary-origin.sentineldr.in/api/v1/active-origin | jq .

# 2. Verify Active Origin on Phone
curl -s https://backup-origin.sentineldr.in/api/v1/active-origin | jq .

# 3. Verify Public Hostname routes to Laptop Primary
curl -s -i https://portfolio.sentineldr.in/api/v1/status | grep "X-SDR-Node"

# 4. Verify Peer Endpoints are blocked with 403 Forbidden
curl -s -o /dev/null -w "%{http_code}\n" https://portfolio.sentineldr.in/api/v1/peer/heartbeat
# Output must be: 403
```
