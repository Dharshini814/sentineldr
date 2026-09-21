# SentinelDR — Shared Constants
# No logic, only values. Standard library only.

# ── Network ───────────────────────────────────────
DISCOVERY_PORT = 47777
DISCOVERY_INTERVAL = 5          # seconds between broadcasts

# ── Heartbeat ─────────────────────────────────────
HEARTBEAT_INTERVAL = 3          # seconds between heartbeat sends
HEARTBEAT_TIMEOUT = 3           # seconds before a single heartbeat times out
MISSED_HEARTBEAT_THRESHOLD = 3  # consecutive misses before failure declared (~9s failover)

# ── Sync ──────────────────────────────────────────
SYNC_INTERVAL = 5               # seconds between sync pushes

# ── Failover ──────────────────────────────────────
FAILOVER_COOLDOWN = 30          # seconds before failover can re-trigger

# ── Node roles ────────────────────────────────────
ROLE_PRIMARY = "primary"
ROLE_SECONDARY = "secondary"
ROLE_ACTIVE_SECONDARY = "active_secondary"

# ── Node statuses ─────────────────────────────────
STATUS_HEALTHY = "healthy"
STATUS_DEGRADED = "degraded"
STATUS_OFFLINE = "offline"
STATUS_FAILOVER = "failover"
STATUS_RECOVERING = "recovering"

# ── Event severities ──────────────────────────────
SEV_INFO = "INFO"
SEV_WARNING = "WARNING"
SEV_CRITICAL = "CRITICAL"
SEV_SUCCESS = "SUCCESS"

# ── Event types ───────────────────────────────────
EVT_HEARTBEAT = "HEARTBEAT"
EVT_SYNC = "SYNC"
EVT_FAILOVER = "FAILOVER"
EVT_RECOVERY = "RECOVERY"
EVT_DISCOVERY = "DISCOVERY"
EVT_ALERT = "ALERT"
EVT_STARTUP = "STARTUP"
EVT_SHUTDOWN = "SHUTDOWN"

# ── Protocol ──────────────────────────────────────
PROTOCOL_VERSION = 1
SERVICE_NAME = "sentineldr"
