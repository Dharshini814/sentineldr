# SentinelDR — Enterprise Disaster Recovery Platform

**Autonomous failover protection for mission-critical applications**

SentinelDR is an enterprise-grade disaster recovery platform that provides automatic failover protection between primary and secondary nodes. When your primary system fails, SentinelDR seamlessly transfers operations to a backup node with zero manual intervention, ensuring continuous availability of critical business applications.

```
+------------------+    UDP Discovery    +------------------+
|   LAPTOP NODE    |<------------------->|   PHONE NODE     |
|   (PRIMARY)      |                     |  (SECONDARY)     |
|                  |                     |                  |
| +--------------+ |    Heartbeat        | +--------------+ |
| |   FastAPI    | |<------------------->| | HTTP Server  | |
| | PostgreSQL   | |                     | |   SQLite     | |
| |   Python     | |    Data Sync        | |   Python     | |
| +--------------+ |<------------------->| +--------------+ |
+------------------+                     +------------------+
         ^                                       ^
         | HTTP API                              | HTTP API
         v                                       v
+------------------+                     +------------------+
| ADMIN FRONTEND   |                     | ADMIN FRONTEND   |
|   (React SPA)    |                     |   (React SPA)    |
|                  |                     |                  |
| +--------------+ |                     | +--------------+ |
| | Portfolio    | |                     | | Portfolio    | |
| | Projects     | |                     | | Projects     | |
| | Monitoring   | |                     | | Monitoring   | |
| | Alerts       | |                     | | Alerts       | |
| +--------------+ |                     | +--------------+ |
+------------------+                     +------------------+
    Normal Mode                           Failover Mode
```

## Architecture

### Laptop PRIMARY Node
- **FastAPI** REST API with automatic OpenAPI documentation
- **PostgreSQL** persistent storage with ACID compliance
- **SQLAlchemy** async ORM with connection pooling
- **Discovery Service** UDP broadcast for automatic peer detection
- **Heartbeat Service** peer health monitoring every 3 seconds
- **Sync Service** real-time data replication to secondary
- **Alert Service** system event notification and logging

### Phone SECONDARY Node
- **HTTP Server** standard library implementation (zero dependencies)
- **SQLite** embedded storage for recovery data
- **UDP Discovery** automatic network peer detection
- **Background Services** heartbeat monitoring and sync reception
- **Failover Detection** activates after 3 missed heartbeats (9 seconds)
- **Recovery Mode** serves synchronized data during primary outage

### Admin Frontend
- **React SPA** responsive web application
- **Real-time Monitoring** live system status and health checks
- **Portfolio Management** demonstration workload with CRUD operations
- **Alert Dashboard** system events and failover notifications
- **Network Topology** visual representation of node status

### Communication
- **UDP Broadcast** automatic IP discovery on port 47777
- **HTTP/REST** API communication between nodes
- **JSON** structured data serialization
- **Checksum Validation** tamper-proof sync integrity
- **API Key Authentication** secure inter-node communication

## Key Features

### Automatic IP Discovery
No manual IP configuration required. When both nodes are on the same local network, they discover each other automatically within 10 seconds using UDP broadcast. This works across network changes — discovery runs again automatically when moving to different Wi-Fi networks.

### Heartbeat Monitoring
Primary node sends heartbeat to secondary every 3 seconds. Secondary monitors for missed heartbeats and triggers failover after 9 seconds of silence. Heartbeat includes node status, sync version, and timestamp.

### Automatic Failover
When primary becomes unavailable, secondary automatically activates recovery mode. No human intervention required. Portfolio data remains accessible through secondary node API. Frontend displays critical failover alerts.

### Data Synchronization
Primary pushes complete data snapshots to secondary every 5 seconds and immediately after every portfolio change. Secondary validates checksum and version before accepting sync. Stale or tampered snapshots are rejected.

### Recovery and Failback
When primary returns online, UDP discovery finds it within 10 seconds. Primary announces return to secondary. Secondary verifies primary health and resumes normal operations. Frontend shows system restoration status.

### Alert System
Comprehensive event logging for all system state changes. Events include discovery, heartbeat, sync, failover, and recovery. Each event has severity level, timestamp, and detailed metadata. Alerts displayed in real-time frontend dashboard.

### Portfolio Demonstration Workload
Complete CRUD application demonstrating disaster recovery capabilities. Create, read, update, delete portfolio projects. All changes synchronized to secondary node. Data remains accessible during primary outage.

## Prerequisites

### Laptop Requirements
```
Python 3.11+
PostgreSQL 14+
Node.js 18+ (for frontend, Module 14)
Git
```

### Phone Requirements
```
Android with Termux installed
Python 3.9+ (installed via Termux)
Same Wi-Fi network as laptop
```

## Laptop Setup — Step by Step

### 1. Clone Repository
```bash
git clone <repository-url>
cd SentinelDR
```

### 2. Create Virtual Environment
```bash
# Create virtual environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (Linux/Mac)
source venv/bin/activate
```

### 3. Install Dependencies
```bash
pip install -r backend/requirements-laptop.txt
```

### 4. Setup PostgreSQL
```bash
# Run PostgreSQL setup script
psql -U postgres -f scripts/setup-postgres.sql
```

### 5. Configure Environment
```bash
# Copy example configuration
cp backend/laptop/.env.laptop.example backend/laptop/.env.laptop

# Edit .env.laptop — set API_KEY and DATABASE_URL
# API_KEY=your-secret-key-here
# DATABASE_URL=postgresql://sentineldr:sentineldr_secure_pass_2024@localhost:5432/sentineldr
```

### 6. Start Laptop Node
```bash
# Windows
scripts\start-laptop.bat

# Linux/Mac (run chmod +x scripts/start-laptop.sh first)
chmod +x scripts/start-laptop.sh
bash scripts/start-laptop.sh
```

The laptop node will be available at http://localhost:8000 with automatic API documentation at http://localhost:8000/docs.

## Phone Setup — Step by Step

### 1. Install Python in Termux
```bash
# Update Termux packages
pkg update && pkg upgrade

# Install Python and Git
pkg install python git
```

### 2. Clone Repository
```bash
# Clone the same repository
git clone <repository-url>
cd SentinelDR
```

### 3. No Dependencies Needed
```bash
# No pip installs required
# Phone server uses Python standard library only
# Verify with: ls backend/requirements-phone.txt
```

### 4. Configure Environment
```bash
# Copy example configuration
cp backend/phone/.env.phone.example backend/phone/.env.phone

# Edit .env.phone — set API_KEY (must match laptop)
# API_KEY=your-secret-key-here
```

### 5. Start Phone Node
```bash
# Set executable permissions first
chmod +x scripts/start-phone.sh
bash scripts/start-phone.sh
```

The phone node will be available at http://localhost:8001 within Termux.

## Frontend Setup — Step by Step

### 1. Navigate to Frontend Directory
```bash
cd frontend
```

### 2. Install Dependencies
```bash
npm install
```

### 3. Configure Environment
```bash
# Copy environment template
cp .env.example .env

# Edit .env file - set VITE_API_KEY to match your backend API_KEY
```

### 4. Start Development Server
```bash
npm run dev
```

The frontend will be available at http://localhost:5173

### 5. Build for Production
```bash
npm run build
```

## Automatic IP Discovery

**IP addresses do not need to be manually configured.**

When both nodes are on the same local network, they discover each other automatically within 10 seconds using UDP broadcast on port 47777.

This works across network changes — if you move to a different Wi-Fi network, discovery runs again automatically. You never need to edit .env files when changing networks.

The discovery protocol:
1. Each node broadcasts presence every 5 seconds
2. Nodes listen for peer broadcasts on UDP port 47777
3. When peer discovered, HTTP connection established
4. Discovery continues running for network change detection

## How Synchronization Works

### Sync Protocol
1. **Laptop pushes snapshots every 5 seconds** — regular interval sync
2. **Immediately after every portfolio change** — real-time sync
3. **Phone validates checksum and version** — integrity verification
4. **Stale or tampered snapshots are rejected** — security protection
5. **Phone stores recovery copy in SQLite** — local persistence

### Sync Payload Structure
```json
{
  "version": 42,
  "timestamp": "2024-01-01T12:00:00Z",
  "checksum": "sha256-hash-of-projects",
  "payload": {
    "projects": [...],
    "events": [...]
  }
}
```

### Version Control
- Each sync has incrementing version number
- Phone rejects syncs with version ≤ current version
- Prevents replay attacks and data corruption
- Version resets only when laptop restarts

## How Failover Works

**Failover Sequence (9 seconds total):**

```
1. Laptop stops responding (network failure, crash, power loss)
2. Phone misses 3 consecutive heartbeats (9 seconds)
3. Phone activates recovery mode
4. Phone serves synchronized data from SQLite
5. Frontend displays CRITICAL alert
6. Portfolio remains accessible through phone API
```

### Failover Detection Logic
- Heartbeat expected every 3 seconds
- Missed heartbeat increments counter
- After 3 missed heartbeats (9 seconds), failover triggers
- Phone role changes from "secondary" to "active_secondary"
- All API endpoints remain functional during failover

### Data Availability During Failover
- Complete portfolio data available from phone SQLite
- Last successful sync version served
- No data loss (sync occurs every 5 seconds maximum)
- Frontend automatically redirects API calls to phone

## How Recovery Works

**Recovery Sequence (10 seconds total):**

```
1. Laptop restarts and becomes available
2. UDP discovery finds laptop within 10 seconds
3. Laptop announces return to phone via /recovery-announcement
4. Phone verifies laptop health via /health endpoint
5. Sync resumes from laptop to phone
6. Phone returns to secondary role
7. Frontend shows system restored status
```

### Recovery Verification
- Phone validates laptop health before accepting recovery
- Laptop must pass health check with role="primary"
- Sync version comparison ensures data consistency
- Recovery announcement includes timestamp and node ID

### Automatic Failback
- No manual intervention required for recovery
- System automatically returns to normal dual-node operation
- Frontend updates in real-time during recovery process
- Alert system logs complete recovery sequence

## Failover Demonstration

**Complete End-to-End Demo Script:**

### Step 1: Start Laptop Node
```bash
# Windows
scripts\start-laptop.bat

# Linux/Mac  
bash scripts/start-laptop.sh
```
Wait for "Server started" message and verify http://localhost:8000/health returns 200.

### Step 2: Start Phone Node
```bash
# In Termux
bash scripts/start-phone.sh
```
Wait for startup banner and verify http://localhost:8001/health returns 200.

### Step 3: Verify Both Nodes Online
- Frontend shows both nodes online
- Laptop status: PRIMARY ONLINE
- Phone status: SECONDARY ONLINE
- Network topology displays green connections

### Step 4: Create Portfolio Project
```bash
curl -X POST http://localhost:8000/portfolio/projects \
  -H "X-API-Key: your-api-key" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Disaster Recovery Test",
    "description": "Testing failover capabilities",
    "tech_stack": "SentinelDR",
    "status": "active"
  }'
```

### Step 5: Verify Project Synced to Phone
```bash
curl -H "X-API-Key: your-api-key" http://localhost:8001/portfolio/projects
```
Project should appear in phone's response within 5 seconds.

### Step 6: Stop Laptop (Simulate Failure)
Press `Ctrl+C` in laptop terminal to stop the primary node.

### Step 7: Wait 9 Seconds — Phone Detects Failure
- Phone logs: "Heartbeat missed 3 times, activating failover"
- Phone role changes to "active_secondary"
- Phone status API shows failover_active: true

### Step 8: Check Frontend — FAILOVER ACTIVE Alert
- Frontend displays red "CRITICAL: PRIMARY NODE FAILED"
- Network topology shows laptop offline, phone active
- Portfolio projects remain accessible through phone

### Step 9: Access Portfolio Through Phone
```bash
curl -H "X-API-Key: your-api-key" http://localhost:8001/portfolio/projects
```
Data remains available — disaster recovery successful!

### Step 10: Restart Laptop
```bash
# Restart laptop node
scripts\start-laptop.bat  # or start-laptop.sh
```

### Step 11: Wait 10 Seconds — Automatic Recovery
- UDP discovery detects laptop return
- Laptop sends recovery announcement
- Phone verifies laptop health
- Sync resumes automatically

### Step 12: Frontend Shows PRIMARY ONLINE
- Frontend displays green "PRIMARY RESTORED"
- Network topology returns to dual-node configuration  
- System back to normal operation

## API Reference

### Authentication
All protected endpoints require `X-API-Key` header with valid API key.

### Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | /health | No | Node health status and basic info |
| GET | /status | Yes | Complete system status with runtime details |
| GET | /nodes | Yes | All discovered nodes and their status |
| GET | /heartbeat | Yes | Send/receive heartbeat from peer node |
| GET | /portfolio/projects | Yes | List all portfolio projects |
| POST | /portfolio/projects | Yes | Create new portfolio project |
| GET | /portfolio/projects/{id} | Yes | Get specific project by ID |
| PUT | /portfolio/projects/{id} | Yes | Update existing project |
| DELETE | /portfolio/projects/{id} | Yes | Delete project by ID |
| GET | /events | Yes | List system events with optional limit |
| POST | /events/{id}/acknowledge | Yes | Mark event as acknowledged |
| GET | /sync/status | Yes | Current synchronization status |
| POST | /sync/now | Yes | Force immediate sync to peer |

### Response Formats

#### Health Response (GET /health)
```json
{
  "node_id": "laptop-node-01",
  "role": "primary",
  "status": "healthy",
  "peer_reachable": true,
  "peer_node_id": "phone-node-02", 
  "peer_host": "192.168.1.100",
  "failover_active": false,
  "local_ip": "192.168.1.50",
  "uptime_seconds": 3600.5,
  "timestamp": "2024-01-01T12:00:00Z",
  "sync_version": 42,
  "project_count": 5
}
```

#### Portfolio Project
```json
{
  "id": "proj_123",
  "title": "Enterprise Web Portal",
  "description": "Customer-facing web application",
  "tech_stack": "React, Node.js, PostgreSQL",
  "status": "active",
  "created_at": "2024-01-01T10:00:00Z",
  "updated_at": "2024-01-01T11:30:00Z"
}
```

#### System Event
```json
{
  "id": "evt_456", 
  "event_type": "failover_triggered",
  "severity": "critical",
  "source": "phone-node-02",
  "message": "Primary node failed, activating recovery mode",
  "timestamp": "2024-01-01T12:00:00Z",
  "acknowledged": false,
  "metadata": {
    "missed_heartbeats": 3,
    "last_seen": "2024-01-01T11:59:51Z"
  }
}
```

## Troubleshooting

### Phone Cannot Discover Laptop

**Symptoms:** Phone logs show "No peers discovered" after 30+ seconds

**Solutions:**
1. Verify both nodes on same Wi-Fi network
2. Check firewall allows UDP port 47777
3. Verify laptop node started successfully (check http://localhost:8000/health)
4. Restart both nodes if network recently changed
5. Check laptop .env.laptop has correct NODE_PORT=8000

### Heartbeat Not Working

**Symptoms:** Frequent failover alerts, inconsistent peer status

**Solutions:**
1. Verify API keys match in both .env files
2. Check network stability (ping between devices)
3. Verify both nodes using same discovery port (47777)
4. Check system clocks synchronized
5. Restart heartbeat services if timing drift detected

### Sync Not Working  

**Symptoms:** Phone shows old data, sync_version not incrementing

**Solutions:**
1. Verify API authentication (X-API-Key headers)
2. Check PostgreSQL connection on laptop node
3. Verify SQLite database writable on phone
4. Check laptop logs for sync service errors
5. Force sync via POST /sync/now endpoint

### PostgreSQL Connection Failed

**Symptoms:** Laptop startup fails with database connection error

**Solutions:**
1. Verify PostgreSQL service running: `sudo systemctl status postgresql`
2. Check DATABASE_URL in .env.laptop matches setup-postgres.sql
3. Verify user credentials: `psql -U sentineldr -d sentineldr`
4. Check PostgreSQL logs: `/var/log/postgresql/postgresql-*.log`
5. Re-run setup-postgres.sql if needed

### API Key Mismatch

**Symptoms:** 401 Unauthorized errors, authentication failures

**Solutions:**
1. Compare API_KEY values in both .env files (must be identical)
2. Verify no whitespace/special characters in API key
3. Check .env files loaded correctly (print config on startup)
4. Use same API key in all HTTP requests
5. Restart both nodes after changing API keys

### Phone Server Crashes on Start

**Symptoms:** Python import errors, module not found

**Solutions:**
1. Verify Python 3.9+ installed: `python --version`
2. Check all phone modules present in backend/phone/
3. Verify file permissions allow Python execution
4. Run phone_server.py directly: `python backend/phone/phone_server.py`
5. Check Termux app has storage permissions

### Failover Not Triggering

**Symptoms:** Laptop stopped but phone remains secondary

**Solutions:**
1. Verify heartbeat service running on phone
2. Check heartbeat timeout configuration (should be 9 seconds)
3. Verify phone can reach laptop HTTP port during normal operation  
4. Check phone system clock not significantly skewed
5. Restart phone node to reset heartbeat detection

### Recovery Not Working

**Symptoms:** Laptop restarted but phone stays in recovery mode

**Solutions:**
1. Verify laptop sends recovery announcement on startup
2. Check phone receives and processes /recovery-announcement
3. Verify laptop passes health check after restart
4. Check UDP discovery working in both directions
5. Manually call laptop /health to verify operational

## Complete System Startup Commands

```bash
# ══════════════════════════════════════════════════
# SENTINELDR — COMPLETE STARTUP SEQUENCE  
# ══════════════════════════════════════════════════

# 1. POSTGRESQL SETUP (run once)
psql -U postgres -f scripts/setup-postgres.sql

# 2. LAPTOP NODE
cd SentinelDR
python -m venv venv
venv\Scripts\activate              # Windows
# source venv/bin/activate         # Linux/Mac
pip install -r backend/requirements-laptop.txt
cp backend/laptop/.env.laptop.example backend/laptop/.env.laptop
# Edit .env.laptop — set API_KEY and DATABASE_URL
scripts\start-laptop.bat           # Windows  
# bash scripts/start-laptop.sh     # Linux/Mac

# 3. PHONE NODE (in Termux)
cd SentinelDR  
cp backend/phone/.env.phone.example backend/phone/.env.phone
# Edit .env.phone — set API_KEY (must match laptop)
bash scripts/start-phone.sh

# 4. FRONTEND
cd SentinelDR/frontend
npm install
cp .env.example .env
# Edit .env — set VITE_API_KEY (must match backend API_KEY)
npm run dev

# 5. VERIFY SYSTEM
curl http://localhost:8000/health        # laptop backend
curl http://localhost:8001/health        # phone backend  
# Open http://localhost:5173             # frontend dashboard
```

## Project Structure

```
SentinelDR/
├── README.md                          # This documentation
├── backend/
│   ├── requirements-laptop.txt        # Laptop node dependencies  
│   ├── requirements-phone.txt         # Phone node (no packages)
│   ├── verify_module13.py            # Module 13 verification
│   ├── shared/                       # Cross-platform shared code
│   │   ├── constants.py              # System constants and enums
│   │   ├── protocol.py               # Network protocol definitions
│   │   └── messages.py               # Message format specifications
│   ├── laptop/                       # Primary node (FastAPI + PostgreSQL)
│   │   ├── .env.laptop.example       # Environment template
│   │   ├── config.py                 # Configuration and settings
│   │   ├── database.py               # PostgreSQL connection
│   │   ├── main.py                   # FastAPI application entry point
│   │   ├── models/                   # SQLAlchemy ORM models
│   │   │   ├── portfolio.py          # Portfolio project model
│   │   │   └── events.py             # System event model
│   │   ├── schemas/                  # Pydantic validation schemas
│   │   │   ├── portfolio.py          # Portfolio request/response schemas
│   │   │   └── events.py             # Event request/response schemas
│   │   ├── services/                 # Background services
│   │   │   ├── discovery_service.py  # UDP peer discovery
│   │   │   ├── heartbeat_service.py  # Peer health monitoring
│   │   │   ├── failover_service.py   # Failover detection and management
│   │   │   ├── sync_service.py       # Data synchronization to phone
│   │   │   └── alert_service.py      # Event logging and notifications
│   │   └── api/                      # FastAPI route handlers
│   │       ├── health.py             # Health and status endpoints
│   │       ├── nodes.py              # Node management endpoints
│   │       ├── heartbeat.py          # Heartbeat endpoints  
│   │       ├── portfolio.py          # Portfolio CRUD endpoints
│   │       ├── events.py             # Event management endpoints
│   │       └── sync.py               # Synchronization endpoints
│   └── phone/                        # Secondary node (stdlib only)
│       ├── .env.phone.example        # Environment template
│       ├── config.py                 # Configuration (no dependencies)
│       ├── storage.py                # SQLite storage layer
│       ├── discovery.py              # UDP peer discovery
│       ├── heartbeat.py              # Heartbeat monitoring
│       ├── failover.py               # Failover detection
│       ├── sync.py                   # Sync data reception
│       └── phone_server.py           # HTTP server (single file)
├── scripts/                          # Setup and startup scripts
│   ├── setup-postgres.sql            # PostgreSQL database setup
│   ├── start-laptop.bat             # Windows laptop startup
│   ├── start-laptop.sh              # Linux/Mac laptop startup  
│   └── start-phone.sh               # Termux phone startup
└── frontend/                         # React Admin Dashboard
    ├── src/
    │   ├── api/                      # API client layer
    │   ├── components/               # React components  
    │   ├── pages/                    # Page components
    │   ├── hooks/                    # Custom React hooks
    │   ├── utils/                    # Utility functions
    │   ├── App.jsx                   # Main app component
    │   └── main.jsx                  # React entry point
    ├── index.html                    # HTML template
    ├── package.json                  # Node.js dependencies
    ├── vite.config.js               # Vite configuration
    └── tailwind.config.js           # Tailwind CSS config
```

---

*SentinelDR — Autonomous disaster recovery for the modern enterprise*