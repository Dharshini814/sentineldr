"""
SentinelDR — Laptop FastAPI Application
Primary node entry point. Wires all services and mounts all routers.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from starlette.middleware.base import BaseHTTPMiddleware
import os

from laptop.config import settings, runtime
from laptop.database import init_db
from laptop.services.alert_service import AlertService
from laptop.services.discovery_service import DiscoveryService, get_local_ip
from laptop.services.heartbeat_service import HeartbeatService
from laptop.services.sync_service import SyncService
from laptop.services.failover_service import FailoverService

# Import network utilities
try:
    from shared.network_utils import update_frontend_env_if_needed
except ImportError:
    def update_frontend_env_if_needed():
        pass

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL, logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ── API Key middleware ────────────────────────────────────────────────────────

_PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/favicon.ico", "/"}


class APIKeyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Allow public paths unconditionally
        if request.url.path in _PUBLIC_PATHS or request.url.path.startswith("/docs"):
            return await call_next(request)
        
        # IMPORTANT: Allow ALL CORS preflight requests (OPTIONS) without API key
        # This must be before any API key validation
        if request.method == "OPTIONS":
            return await call_next(request)

        # Only check API key for actual requests (GET, POST, PUT, DELETE)
        api_key = request.headers.get("X-API-Key", "")
        if api_key != settings.API_KEY:
            from fastapi.responses import JSONResponse
            return JSONResponse(
                status_code=401,
                content={"detail": "Invalid or missing API key"},
            )
        return await call_next(request)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup sequence — services launched in dependency order."""

    # 1. Init database tables
    init_db()

    # 2. Instantiate alert service first — all others depend on it
    alert_svc = AlertService(settings=settings, runtime=runtime)

    # 3. Discovery
    discovery_svc = DiscoveryService(
        settings=settings, runtime=runtime, alert_service=alert_svc
    )
    discovery_svc.start()

    # 4. Heartbeat
    heartbeat_svc = HeartbeatService(
        settings=settings, runtime=runtime, alert_service=alert_svc
    )
    heartbeat_svc.start()

    # 5. Sync
    sync_svc = SyncService(
        settings=settings, runtime=runtime, alert_service=alert_svc
    )
    sync_svc.start()

    # 6. Failover
    failover_svc = FailoverService(
        settings=settings, runtime=runtime, alert_service=alert_svc
    )
    failover_svc.start()

    # 7. Startup event
    alert_svc.start()   # emits startup event + logs "Alert service ready"

    # 8. Store services in app state for router access
    local_ip = get_local_ip()
    app.state.settings = settings
    app.state.runtime = runtime
    app.state.local_ip = local_ip
    app.state.alert_service = alert_svc
    app.state.discovery_service = discovery_svc
    app.state.heartbeat_service = heartbeat_svc
    app.state.sync_service = sync_svc
    app.state.failover_service = failover_svc

    # Auto-update frontend .env with current IP
    try:
        update_frontend_env_if_needed()
        logger.info(f"[STARTUP] Auto-updated frontend .env with IP: {local_ip}")
    except Exception as e:
        logger.debug(f"[STARTUP] Could not update frontend .env: {e}")

    logger.info(
        "[STARTUP] SentinelDR laptop node ready on port %d", settings.NODE_PORT
    )

    yield

    # Shutdown — stop background services gracefully
    discovery_svc.stop()
    heartbeat_svc.stop()
    sync_svc.stop()
    failover_svc.stop()
    logger.info("[SHUTDOWN] SentinelDR laptop node stopped")


# ── Application ───────────────────────────────────────────────────────────────

app = FastAPI(
    title="SentinelDR",
    description="Disaster Recovery Platform — Primary Node",
    version="1.0.0",
    lifespan=lifespan,
)

# ── CORS ──────────────────────────────────────────────────────────────────────
_cors_origins = list(settings.CORS_ORIGINS)

# Add common frontend development ports
for _origin in (
    "http://localhost:5173",
    "http://127.0.0.1:5173", 
    "http://localhost:5174",
    "http://127.0.0.1:5174",
    "http://localhost:3000",  # React default
    "http://127.0.0.1:3000",
):
    if _origin not in _cors_origins:
        _cors_origins.append(_origin)

# Add local network IPs
try:
    _local_ip = get_local_ip()
    for port in (5173, 5174, 3000):
        _lan_origin = f"http://{_local_ip}:{port}"
        if _lan_origin not in _cors_origins:
            _cors_origins.append(_lan_origin)
except Exception:
    pass

logger.info(f"[CORS] Allowed origins: {_cors_origins}")

# Configure CORS middleware with permissive settings for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS", "HEAD", "PATCH"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Debug middleware to log requests
class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        if request.method == "OPTIONS":
            logger.info(f"[CORS DEBUG] OPTIONS request to {request.url.path} from origin: {request.headers.get('origin', 'NO-ORIGIN')}")
        response = await call_next(request)
        if request.method == "OPTIONS" and response.status_code >= 400:
            logger.error(f"[CORS ERROR] OPTIONS failed with {response.status_code} for {request.url.path}")
        return response

app.add_middleware(RequestLoggingMiddleware)

# ── API Key middleware (after CORS) ───────────────────────────────────────────
app.add_middleware(APIKeyMiddleware)

# ── Root route for portfolio ──────────────────────────────────────────────────
@app.get("/")
async def serve_portfolio():
    """Serve the portfolio HTML from the frontend directory"""
    portfolio_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))), 
        "frontend", "portfolio", "index.html"
    )
    
    if os.path.exists(portfolio_path):
        return FileResponse(portfolio_path, media_type="text/html")
    else:
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=404, 
            content={"detail": f"Portfolio not found at {portfolio_path}. Please ensure the portfolio files are properly deployed."}
        )

# ── Routers ───────────────────────────────────────────────────────────────────
from laptop.api.health import router as health_router
from laptop.api.nodes import router as nodes_router
from laptop.api.heartbeat import router as heartbeat_router
from laptop.api.portfolio import router as portfolio_router
from laptop.api.events import router as events_router
from laptop.api.sync import router as sync_router

app.include_router(health_router)
app.include_router(nodes_router)
app.include_router(heartbeat_router)
app.include_router(portfolio_router)
app.include_router(events_router)
app.include_router(sync_router)
