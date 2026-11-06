"""
SentinelDR Laptop Node - Base FastAPI Server & Peer Replication
FastAPI, Pydantic, PostgreSQL.
Runs on Port 8000.
"""

import json
import os
import sys
import time
import uuid
from typing import Any, Dict, List, Optional

# Ensure repository root is on sys.path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
import uvicorn

from laptop.db import LaptopDatabase
from shared.api_contract import (
    ALLOWED_ORIGINS,
    ROUTE_ACTIVE_ORIGIN,
    ROUTE_DASHBOARD_EVENTS,
    ROUTE_DASHBOARD_STATUS,
    ROUTE_EVENTS,
    ROUTE_HEALTH,
    ROUTE_READY,
    ROUTE_METRICS,
    ROUTE_PEER_CHANGES,
    ROUTE_PEER_FAILBACK,
    ROUTE_PEER_FAILOVER,
    ROUTE_PEER_HEARTBEAT,
    ROUTE_PEER_LEASE_REQUEST,
    ROUTE_PEER_RECOVERY_COMPLETE,
    ROUTE_PEER_RECOVERY_START,
    ROUTE_PEER_REPLICATE,
    ROUTE_STATUS,
    STATE_FAILBACK_PENDING,
    STATE_PRIMARY_ACTIVE,
    STATE_RECONCILING,
    STATE_RECOVERING,
    STATE_SECONDARY_ACTIVE,
    STATE_SECONDARY_STANDBY,
)
from shared.config import NodeConfig
from shared.failover import FailoverCoordinator
from shared.recovery import RecoveryCoordinator
from shared.heartbeat import HeartbeatTracker, validate_heartbeat_payload
from shared.logger import setup_logger
from shared.ownership import (
    OwnershipRecord,
    sign_ownership_record,
    validate_lease,
)
from shared.protocol import (
    ERR_BAD_REQUEST,
    ERR_CONFLICT,
    ERR_FORBIDDEN,
    ERR_INTERNAL_ERROR,
    ERR_NOT_FOUND,
    ERR_UNAUTHORIZED,
    make_error,
    make_success,
    serialize_envelope,
)
from shared.replication import MAX_BODY_BYTES, validate_batch_request
from shared.security import (
    PersistentNonceCache,
    sanitize_for_audit_stream,
    verify_admin_key,
    verify_peer_request,
)
from shared.state_machine import ClusterStateMachine
from shared.replication_worker import ReplicationClient
from shared.discovery import PeerDiscoveryListener
import threading


config = NodeConfig(node_type="laptop")
logger = setup_logger("laptop_server", node_id=config.node_id, epoch=config.epoch)
db = LaptopDatabase(config.database_url, dev_fallback_sqlite=config.dev_db_fallback)
nonce_cache = PersistentNonceCache(config.nonce_cache_db)
heartbeat_tracker = HeartbeatTracker()

# Synchronize initial epoch & ensure valid lease if starting as PRIMARY_ACTIVE
init_ownership = db.get_ownership(config.cluster_id)
now_init = time.time()
if config.initial_role == STATE_PRIMARY_ACTIVE:
    if not init_ownership or (init_ownership.owner_node_id == config.node_id and init_ownership.lease_expires_at < now_init):
        expires_at = now_init + 86400.0
        active_epoch = init_ownership.epoch if init_ownership else config.epoch
        boot_sig = sign_ownership_record(
            cluster_id=config.cluster_id,
            owner_node_id=config.node_id,
            epoch=active_epoch,
            lease_id=f"active-lease-{config.node_id}-{active_epoch}",
            lease_expires_at=expires_at,
            granted_by="bootstrap",
            secret=config.hmac_secret
        )
        db.set_ownership(OwnershipRecord(
            cluster_id=config.cluster_id,
            owner_node_id=config.node_id,
            epoch=active_epoch,
            lease_id=f"active-lease-{config.node_id}-{active_epoch}",
            lease_expires_at=expires_at,
            granted_by="bootstrap",
            signature=boot_sig,
            updated_at=now_init
        ))
        init_ownership = db.get_ownership(config.cluster_id)

initial_epoch = init_ownership.epoch if init_ownership else config.epoch
state_machine = ClusterStateMachine(
    initial_state=config.initial_role,
    node_id=config.node_id,
    initial_epoch=initial_epoch,
    audit_callback=db.log_audit_event
)
failover_coordinator = FailoverCoordinator(
    node_id=config.node_id,
    cluster_id=config.cluster_id,
    state_machine=state_machine,
    heartbeat_tracker=heartbeat_tracker,
    db=db,
    witness_url=config.witness_url,
    witness_secret=config.witness_secret,
    max_clock_skew=config.max_clock_skew,
)
recovery_coordinator = RecoveryCoordinator(
    node_id=config.node_id,
    cluster_id=config.cluster_id,
    state_machine=state_machine,
    db=db,
    witness_url=config.witness_url,
    witness_secret=config.witness_secret,
    hmac_secret=config.hmac_secret,
    admin_key=config.admin_key,
    max_clock_skew=config.max_clock_skew,
)

repl_client = ReplicationClient(secret=config.hmac_secret)
discovery = PeerDiscoveryListener(expected_cluster_id=config.cluster_id)
discovery.start()

def _on_peer_found(url):
    config.peer_url = url
discovery.add_on_discovered_callback(_on_peer_found)

def _laptop_background_worker():
    """Periodically sends heartbeats every 3 seconds to Phone and handles auto-failback."""
    while True:
        time.sleep(3.0)
        try:
            # 1. Heartbeat to Phone when Laptop is PRIMARY_ACTIVE
            if state_machine.current_state == STATE_PRIMARY_ACTIVE:
                ownership = db.get_ownership(config.cluster_id)
                lease_id = ownership.lease_id if ownership else "laptop-lease"
                chk = db.get_replication_checkpoint(config.node_id)
                last_seq = chk.get("last_applied_sequence", 0) if chk else 0
                repl_client.send_heartbeat(
                    peer_url=config.peer_url,
                    sender_node_id=config.node_id,
                    sender_state=state_machine.current_state,
                    epoch=state_machine.current_epoch,
                    lease_id=lease_id,
                    last_committed_sequence=last_seq,
                    database_health="HEALTHY"
                )

            # 2. Check if Phone was promoted during downtime and trigger recovery/failback
            elif state_machine.current_state in (STATE_RECOVERING, STATE_SECONDARY_STANDBY):
                ok, _, peer_data, _ = recovery_coordinator._send_peer_request(config.peer_url, "GET", ROUTE_STATUS)
                if ok and peer_data and peer_data.get("ok"):
                    role = peer_data.get("data", {}).get("role")
                    if role == STATE_SECONDARY_ACTIVE:
                        print("[Laptop Node] Detected Phone is currently SECONDARY_ACTIVE. Initiating automatic recovery & failback...", flush=True)
                        rec_ok, rec_msg, _ = recovery_coordinator.start_recovery(config.peer_url)
                        if rec_ok:
                            recovery_coordinator.reconcile_from_peer(config.peer_url)
                            val_ok, _, _ = recovery_coordinator.validate_integrity_before_failback(config.peer_url)
                            if val_ok:
                                fb_ok, fb_msg, _ = recovery_coordinator.initiate_failback(config.peer_url)
                                if fb_ok:
                                    print("[Laptop Node] Failback completed! Laptop resumed PRIMARY_ACTIVE.", flush=True)
        except Exception:
            pass

_hb_thread = threading.Thread(target=_laptop_background_worker, daemon=True)
_hb_thread.start()

PORTFOLIO_HTML_PATH = os.path.join(BASE_DIR, "frontend", "portfolio.html")
DASHBOARD_HTML_PATH = os.path.join(BASE_DIR, "frontend", "dashboard.html")

app = FastAPI(title="SentinelDR Laptop Node", version="1.0.0", docs_url=None, redoc_url=None)

# Restrict CORS to real frontend origins (no wildcard with credentials)
app.add_middleware(
    CORSMiddleware,
    allow_origins=list(ALLOWED_ORIGINS),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


server_start_time = time.time()
request_counter = 0

# Log startup event
db.log_audit_event(
    event_id=uuid.uuid4().hex,
    node_id=config.node_id,
    epoch=config.epoch,
    event_type="NODE_STARTED",
    severity="INFO",
    details={"port": config.port, "role": config.initial_role}
)


@app.exception_handler(404)
async def custom_404_handler(request: Request, exc):
    err = make_error(
        code=ERR_NOT_FOUND,
        message=f"Path not found: {request.url.path}",
        node_id=config.node_id,
        epoch=config.epoch
    )
    return JSONResponse(status_code=404, content=err)


@app.middleware("http")
async def count_requests_and_format_errors(request: Request, call_next):
    global request_counter
    request_counter += 1
    try:
        response = await call_next(request)
        response.headers["X-SDR-Node"] = config.node_id
        response.headers["X-SDR-Epoch"] = str(config.epoch)
        return response
    except Exception as exc:
        err = make_error(
            code=ERR_INTERNAL_ERROR,
            message="An internal server error occurred",
            node_id=config.node_id,
            epoch=config.epoch
        )
        return JSONResponse(status_code=500, content=err)


# --- 1. Portfolio HTML Serving ---

@app.get("/", response_class=HTMLResponse)
@app.get("/index.html", response_class=HTMLResponse)
@app.get("/portfolio.html", response_class=HTMLResponse)
async def serve_portfolio():
    if not os.path.exists(PORTFOLIO_HTML_PATH):
        raise HTTPException(status_code=404, detail="portfolio.html not found")
    with open(PORTFOLIO_HTML_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content, status_code=200)


@app.get("/dashboard", response_class=HTMLResponse)
@app.get("/dashboard.html", response_class=HTMLResponse)
async def serve_dashboard():
    if not os.path.exists(DASHBOARD_HTML_PATH):
        raise HTTPException(status_code=404, detail="dashboard.html not found")
    with open(DASHBOARD_HTML_PATH, "r", encoding="utf-8") as f:
        content = f.read()
    return HTMLResponse(content=content, status_code=200)



# --- 2. Base API Endpoints ---

@app.get(ROUTE_HEALTH)
async def get_health():
    db_ready, err = db.is_healthy()
    data = {
        "status": "HEALTHY" if db_ready else "DEGRADED",
        "db_ready": db_ready,
        "node_id": config.node_id,
        "version": "1.0.0"
    }
    status_code = 200 if db_ready else 503
    resp = make_success(data=data, node_id=config.node_id, epoch=config.epoch)
    return JSONResponse(status_code=status_code, content=resp)


@app.get(ROUTE_READY)
async def get_ready():
    """
    GET /ready
    Readiness probe: Returns 200 OK only if database is connected,
    schema is initialized, and node is ready to process traffic.
    """
    db_ready, err = db.is_healthy()
    is_ready = bool(db_ready)
    data = {
        "ready": is_ready,
        "status": "READY" if is_ready else "NOT_READY",
        "db_healthy": db_ready,
        "role": state_machine.current_state,
        "epoch": state_machine.current_epoch,
        "node_id": config.node_id,
        "details": err if not is_ready else "Node is initialized and ready",
    }
    status_code = 200 if is_ready else 503
    resp = make_success(data=data, node_id=config.node_id, epoch=state_machine.current_epoch)
    return JSONResponse(status_code=status_code, content=resp)



@app.get(ROUTE_STATUS)
async def get_status():
    db_ready, _ = db.is_healthy()
    uptime = time.time() - server_start_time
    hb_status = heartbeat_tracker.get_status()
    now = time.time()
    ownership = db.get_ownership(config.cluster_id)
    valid, _ = validate_lease(
        record=ownership,
        node_id=config.node_id,
        expected_epoch=state_machine.current_epoch,
        expected_cluster_id=config.cluster_id,
        secret=config.hmac_secret,
        now=now,
        max_clock_skew=1.0
    )
    remaining = max(0.0, round(ownership.lease_expires_at - now, 2)) if ownership else 0.0

    data = {
        "cluster_id": config.cluster_id,
        "node_id": config.node_id,
        "node_type": "laptop",
        "role": state_machine.current_state,
        "epoch": state_machine.current_epoch,
        "db_ready": db_ready,
        "uptime_seconds": round(uptime, 2),
        "heartbeat": hb_status,
        "lease": {
            "valid": valid,
            "owner": ownership.owner_node_id if ownership else "none",
            "expires_at": ownership.lease_expires_at if ownership else 0.0,
            "remaining_seconds": remaining,
            "granted_by": ownership.granted_by if ownership else "none"
        },
        "split_brain_protection": {
            "mechanism": "INDEPENDENT_WITNESS_QUORUM",
            "witness_url": config.witness_url,
            "max_clock_skew_seconds": config.max_clock_skew,
            "fail_closed_mode": "SAFE_MODE_ENABLED"
        }
    }
    resp = make_success(data=data, node_id=config.node_id, epoch=state_machine.current_epoch)
    return JSONResponse(status_code=200, content=resp)


@app.get(ROUTE_METRICS)
async def get_metrics():
    uptime = time.time() - server_start_time
    db_ready, _ = db.is_healthy()
    checkpoint = db.get_replication_checkpoint("phone")
    hb_status = heartbeat_tracker.get_status()
    data = {
        "uptime_seconds": round(uptime, 2),
        "requests_total": request_counter,
        "db_healthy": db_ready,
        "last_applied_sequence": checkpoint["last_applied_sequence"],
        "heartbeat_misses": hb_status["consecutive_misses"],
        "suspected_offline": hb_status["suspected_offline"],
        "audit_events_count": len(db.get_recent_audit_events(limit=100))
    }
    resp = make_success(data=data, node_id=config.node_id, epoch=config.epoch)
    return JSONResponse(status_code=200, content=resp)


@app.get(ROUTE_EVENTS)
async def get_events(request: Request):
    headers_dict = dict(request.headers)
    body = await request.body()

    is_admin = verify_admin_key(headers_dict, config.admin_key)
    is_peer = False
    err_code = ERR_UNAUTHORIZED

    if not is_admin:
        is_valid, err, _ = verify_peer_request(
            headers=headers_dict,
            method="GET",
            path=request.url.path,
            body=body,
            secret=config.hmac_secret,
            nonce_cache=nonce_cache,
            window_seconds=config.timestamp_window_seconds
        )
        if is_valid:
            is_peer = True
        else:
            err_code = err or ERR_UNAUTHORIZED

    if not (is_admin or is_peer):
        err_resp = make_error(
            code=err_code,
            message=f"Authentication failed: {err_code}",
            node_id=config.node_id,
            epoch=config.epoch
        )
        return JSONResponse(status_code=401, content=err_resp)

    events = db.get_recent_audit_events(limit=50)
    resp = make_success(
        data={"events": events, "count": len(events)},
        node_id=config.node_id,
        epoch=config.epoch
    )
    return JSONResponse(status_code=200, content=resp)


@app.get(ROUTE_DASHBOARD_STATUS)
async def get_dashboard_status():
    """GET /api/v1/dashboard/status - Unprivileged operational telemetry for dashboard."""
    db_ready, _ = db.is_healthy()
    uptime = time.time() - server_start_time
    now = time.time()
    ownership = db.get_ownership(config.cluster_id)

    # Ownership safety
    if ownership:
        valid, lease_err = validate_lease(
            record=ownership,
            node_id=ownership.owner_node_id,
            expected_epoch=ownership.epoch,
            expected_cluster_id=config.cluster_id,
            secret=config.hmac_secret,
            now=now,
            max_clock_skew=config.max_clock_skew,
            witness_secret=config.witness_secret,
        )
        remaining = max(0.0, round(ownership.lease_expires_at - now, 2))
        if state_machine.current_state == "SAFE_MODE":
            safety_status = "SAFE_MODE_FENCED"
        elif valid and remaining > 0:
            safety_status = "VALID"
        elif remaining == 0:
            safety_status = "EXPIRED"
        else:
            safety_status = f"INVALID: {lease_err}"

        ownership_data = {
            "owner_node_id": ownership.owner_node_id,
            "epoch": ownership.epoch,
            "safety_status": safety_status,
            "remaining_seconds": remaining,
            "granted_by": ownership.granted_by,
        }
    else:
        ownership_data = {
            "owner_node_id": "none",
            "epoch": 0,
            "safety_status": "NO_LEASE",
            "remaining_seconds": 0.0,
            "granted_by": "none",
        }

    # Heartbeat
    hb_status = heartbeat_tracker.get_status()
    hb_data = {
        "elapsed_seconds": hb_status.get("elapsed_seconds"),
        "consecutive_misses": hb_status.get("consecutive_misses", 0),
        "suspected_offline": hb_status.get("suspected_offline", False),
    }

    # Replication
    phone_applied_checkpoint = db.get_replication_checkpoint("ack_phone")
    highest_local = db.get_highest_local_sequence("laptop")
    phone_applied_seq = phone_applied_checkpoint.get("last_applied_sequence", 0)
    pending_outbox = len(db.get_unreplicated_changes("phone", limit=1000))
    rep_data = {
        "highest_local_sequence": highest_local,
        "peer_applied_sequence": phone_applied_seq,
        "lag": max(0, highest_local - phone_applied_seq),
        "pending_outbox_count": pending_outbox,
    }

    # Recovery & Integrity
    conflicts = db.get_conflicts(resolved=False)
    integrity = "POSTGRES_OK" if (db.is_postgres and not db.using_sqlite_fallback) else ("SQLITE_DEV_OK" if db_ready else "DEGRADED")
    rec_data = {
        "phase": state_machine.current_state,
        "unresolved_conflicts": len(conflicts),
        "integrity_status": integrity,
    }

    # Direct Peer API Connectivity
    if hb_status.get("suspected_offline"):
        peer_api_reachability = "OFFLINE"
    elif hb_status.get("elapsed_seconds") is not None and hb_status["elapsed_seconds"] <= 10.0:
        peer_api_reachability = "ONLINE"
    else:
        peer_api_reachability = "STANDBY" if state_machine.current_state == "SECONDARY_STANDBY" else "UNKNOWN"

    conn_data = {
        "peer_api_reachability": peer_api_reachability,
    }

    data = {
        "cluster_id": config.cluster_id,
        "node_id": config.node_id,
        "node_type": "laptop",
        "role": state_machine.current_state,
        "epoch": state_machine.current_epoch,
        "db_ready": db_ready,
        "db_healthy": db_ready,
        "uptime_seconds": round(uptime, 2),
        "ownership": ownership_data,
        "heartbeat": hb_data,
        "replication": rep_data,
        "recovery": rec_data,
        "connectivity": conn_data,
    }
    resp = make_success(data=data, node_id=config.node_id, epoch=state_machine.current_epoch)
    return JSONResponse(status_code=200, content=resp)


@app.get(ROUTE_DASHBOARD_EVENTS)
async def get_dashboard_events():
    """GET /api/v1/dashboard/events - Public sanitized audit stream for dashboard."""
    raw_events = db.get_recent_audit_events(limit=50)
    secrets_to_redact = [
        config.hmac_secret,
        config.admin_key,
        config.witness_secret,
    ]
    sanitized_events = []
    for ev in raw_events:
        sanitized = {
            "event_id": ev.get("event_id"),
            "timestamp": ev.get("timestamp"),
            "node_id": ev.get("node_id"),
            "epoch": ev.get("epoch"),
            "event_type": ev.get("event_type"),
            "severity": ev.get("severity", "INFO"),
            "details": sanitize_for_audit_stream(ev.get("details"), secrets_to_redact),
        }
        sanitized_events.append(sanitized)
    resp = make_success(
        data={"events": sanitized_events, "count": len(sanitized_events)},
        node_id=config.node_id,
        epoch=state_machine.current_epoch,
    )
    return JSONResponse(status_code=200, content=resp)


@app.get("/api/v1/discovered-peer")
async def get_discovered_peer():
    """Returns the automatically discovered Phone IP and port."""
    return JSONResponse(status_code=200, content=make_success({
        "phone_url": discovery.phone_url,
        "discovered": discovery.discovered_phone_ip is not None,
        "phone_ip": discovery.discovered_phone_ip or "127.0.0.1",
        "phone_port": discovery.discovered_phone_port
    }, config.node_id, state_machine.current_epoch))


@app.get(ROUTE_ACTIVE_ORIGIN)
async def get_active_origin():
    """
    GET /api/v1/active-origin
    Lightweight active-origin status endpoint for Cloudflare edge routing.
    Exposes role, state, epoch, and lease validity without secrets.
    """
    db_ready, _ = db.is_healthy()
    now = time.time()
    ownership = db.get_ownership(config.cluster_id)
    valid = False
    remaining = 0.0
    if ownership:
        valid, _ = validate_lease(
            record=ownership,
            node_id=ownership.owner_node_id,
            expected_epoch=ownership.epoch,
            expected_cluster_id=config.cluster_id,
            secret=config.hmac_secret,
            now=now,
            max_clock_skew=config.max_clock_skew,
            witness_secret=config.witness_secret,
        )
        remaining = max(0.0, round(ownership.lease_expires_at - now, 2))

    is_owner = bool(ownership and ownership.owner_node_id == config.node_id)
    is_writable = bool(state_machine.is_writable() and valid and remaining > 0 and is_owner and db_ready)

    data = {
        "cluster_id": config.cluster_id,
        "node_id": config.node_id,
        "node_type": "laptop",
        "role": state_machine.current_state,
        "epoch": state_machine.current_epoch,
        "writable": is_writable,
        "lease_valid": valid and remaining > 0,
        "lease_remaining_seconds": remaining,
        "owner_node_id": ownership.owner_node_id if ownership else "none",
        "db_healthy": db_ready,
    }
    resp = make_success(data=data, node_id=config.node_id, epoch=state_machine.current_epoch)
    return JSONResponse(status_code=200, content=resp)




# --- 3. Peer Endpoints ---

@app.post(ROUTE_PEER_HEARTBEAT)
async def post_peer_heartbeat(request: Request):
    headers_dict = dict(request.headers)
    body = await request.body()

    is_valid, err_code, caller_meta = verify_peer_request(
        headers=headers_dict,
        method="POST",
        path=ROUTE_PEER_HEARTBEAT,
        body=body,
        secret=config.hmac_secret,
        nonce_cache=nonce_cache,
        window_seconds=config.timestamp_window_seconds
    )
    if not is_valid:
        return JSONResponse(
            status_code=401,
            content=make_error(err_code or ERR_UNAUTHORIZED, f"Heartbeat authentication failed: {err_code}", config.node_id, config.epoch)
        )

    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return JSONResponse(status_code=400, content=make_error(ERR_BAD_REQUEST, "Malformed JSON heartbeat payload", config.node_id, config.epoch))

    valid, val_err = validate_heartbeat_payload(payload)
    if not valid:
        return JSONResponse(status_code=400, content=make_error(ERR_BAD_REQUEST, val_err or "Invalid heartbeat structure", config.node_id, config.epoch))

    received_at = heartbeat_tracker.record_heartbeat(payload)
    peer_node_id = payload["sender_node_id"]
    checkpoint = db.get_replication_checkpoint(peer_node_id)
    highest_applied = checkpoint["last_applied_sequence"]

    data = {
        "status": "ACK",
        "receiver_node_id": config.node_id,
        "receiver_epoch": config.epoch,
        "highest_applied_sequence": highest_applied,
        "received_at": received_at
    }
    return JSONResponse(status_code=200, content=make_success(data, config.node_id, config.epoch))


@app.post(ROUTE_PEER_REPLICATE)
async def post_peer_replicate(request: Request):
    body = await request.body()
    if len(body) > MAX_BODY_BYTES:
        return JSONResponse(
            status_code=413,
            content=make_error("PAYLOAD_TOO_LARGE", f"Batch exceeds {MAX_BODY_BYTES} bytes", config.node_id, config.epoch)
        )

    headers_dict = dict(request.headers)
    is_valid, err_code, caller_meta = verify_peer_request(
        headers=headers_dict,
        method="POST",
        path=ROUTE_PEER_REPLICATE,
        body=body,
        secret=config.hmac_secret,
        nonce_cache=nonce_cache,
        window_seconds=config.timestamp_window_seconds
    )
    if not is_valid:
        return JSONResponse(
            status_code=401,
            content=make_error(err_code or ERR_UNAUTHORIZED, f"Replication authentication failed: {err_code}", config.node_id, config.epoch)
        )

    try:
        batch = json.loads(body.decode("utf-8"))
    except Exception:
        return JSONResponse(status_code=400, content=make_error(ERR_BAD_REQUEST, "Malformed JSON replication batch", config.node_id, config.epoch))

    valid, val_err = validate_batch_request(batch)
    if not valid:
        return JSONResponse(status_code=400, content=make_error(ERR_BAD_REQUEST, val_err or "Invalid batch format", config.node_id, config.epoch))

    origin_node = caller_meta["node_id"] if caller_meta else "phone"
    batch_id = batch["batch_id"]
    events = batch["events"]

    ok, last_seq, dups, missing, resync, err_detail = db.apply_replication_batch(
        origin_node_id=origin_node,
        batch_id=batch_id,
        events=events
    )

    resp_data = {
        "accepted": ok,
        "last_applied_sequence": last_seq,
        "duplicate_count": dups,
        "missing_sequences": missing,
        "requires_full_resync": resync
    }

    if not ok:
        status_code = 409 if missing else 500
        return JSONResponse(
            status_code=status_code,
            content=make_error(ERR_CONFLICT if missing else "APPLY_FAILED", err_detail or "Batch apply failed", config.node_id, config.epoch, details=resp_data)
        )

    return JSONResponse(status_code=200, content=make_success(resp_data, config.node_id, config.epoch))


@app.get("/api/v1/peer/snapshot")
async def get_peer_snapshot(request: Request):
    headers_dict = dict(request.headers)
    is_valid, err_code, _ = verify_peer_request(
        headers=headers_dict,
        method="GET",
        path="/api/v1/peer/snapshot",
        body=b"",
        secret=config.hmac_secret,
        nonce_cache=nonce_cache,
        window_seconds=config.timestamp_window_seconds
    )
    if not is_valid:
        return JSONResponse(status_code=401, content=make_error(err_code or ERR_UNAUTHORIZED, "Snapshot authentication failed", config.node_id, config.epoch))

    snapshot = db.get_full_snapshot()
    return JSONResponse(status_code=200, content=make_success(snapshot, config.node_id, config.epoch))


@app.post(ROUTE_PEER_LEASE_REQUEST)
async def post_peer_lease_request(request: Request):
    headers_dict = dict(request.headers)
    body = await request.body()

    is_valid, err_code, caller_meta = verify_peer_request(
        headers=headers_dict,
        method="POST",
        path=ROUTE_PEER_LEASE_REQUEST,
        body=body,
        secret=config.hmac_secret,
        nonce_cache=nonce_cache,
        window_seconds=config.timestamp_window_seconds
    )
    if not is_valid:
        return JSONResponse(status_code=401, content=make_error(err_code or ERR_UNAUTHORIZED, f"Peer authentication failed: {err_code}", config.node_id, state_machine.current_epoch))

    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception:
        return JSONResponse(status_code=400, content=make_error(ERR_BAD_REQUEST, "Malformed JSON in lease request", config.node_id, state_machine.current_epoch))

    # Bounded Clock Skew Policy
    sent_at = float(payload.get("sent_at", 0.0))
    now = time.time()
    skew = abs(now - sent_at)
    if skew > config.max_clock_skew:
        return JSONResponse(status_code=400, content=make_error("CLOCK_SKEW_EXCEEDED", f"Clock skew of {skew:.3f}s exceeds maximum threshold of {config.max_clock_skew}s", config.node_id, state_machine.current_epoch))

    # Evaluate local ownership & state
    record = db.get_ownership(config.cluster_id)
    valid, _ = validate_lease(
        record=record,
        node_id=config.node_id,
        expected_epoch=state_machine.current_epoch,
        expected_cluster_id=config.cluster_id,
        secret=config.hmac_secret,
        now=now,
        max_clock_skew=1.0
    )

    if state_machine.current_state == STATE_PRIMARY_ACTIVE and valid and record:
        remaining = round(record.lease_expires_at - now, 2)
        data = {
            "status": "DENIED",
            "reason": "LOCAL_PRIMARY_ACTIVE_WITH_VALID_LEASE",
            "current_owner": config.node_id,
            "current_epoch": state_machine.current_epoch,
            "remaining_lease_seconds": remaining
        }
        return JSONResponse(status_code=409, content=make_error(ERR_CONFLICT, "Lease denied: active primary holds valid lease", config.node_id, state_machine.current_epoch, details=data))

    # Yield ownership
    data = {
        "status": "YIELDED",
        "reason": "LOCAL_NODE_YIELDS_OWNERSHIP",
        "last_known_epoch": state_machine.current_epoch,
        "local_state": state_machine.current_state
    }
    return JSONResponse(status_code=200, content=make_success(data, config.node_id, state_machine.current_epoch))


@app.post(ROUTE_PEER_FAILOVER)
async def post_peer_failover(request: Request):
    headers_dict = dict(request.headers)
    body = await request.body()

    is_admin = verify_admin_key(headers_dict, config.admin_key)
    is_peer = False
    err_code = ERR_UNAUTHORIZED

    if not is_admin:
        is_valid, err, _ = verify_peer_request(
            headers=headers_dict,
            method="POST",
            path=ROUTE_PEER_FAILOVER,
            body=body,
            secret=config.hmac_secret,
            nonce_cache=nonce_cache,
            window_seconds=config.timestamp_window_seconds
        )
        if is_valid:
            is_peer = True
        else:
            err_code = err or ERR_UNAUTHORIZED

    if not (is_admin or is_peer):
        return JSONResponse(
            status_code=401,
            content=make_error(err_code, f"Failover authentication failed: {err_code}", config.node_id, state_machine.current_epoch)
        )

    reason = "Failover initiated via authenticated API"
    force_admin = False
    if body:
        try:
            payload = json.loads(body.decode("utf-8"))
            if isinstance(payload, dict):
                reason = payload.get("reason", reason)
                if "force_admin" in payload and is_admin:
                    force_admin = bool(payload["force_admin"])
        except Exception:
            pass

    ok, msg, lease_info = failover_coordinator.attempt_failover(reason=reason, force_admin=force_admin)
    if not ok:
        return JSONResponse(
            status_code=409,
            content=make_error("FAILOVER_REJECTED", msg, config.node_id, state_machine.current_epoch)
        )

    return JSONResponse(
        status_code=200,
        content=make_success({
            "status": "PROMOTED",
            "message": msg,
            "role": state_machine.current_state,
            "epoch": state_machine.current_epoch,
            "lease": lease_info
        }, config.node_id, state_machine.current_epoch)
    )


@app.post(ROUTE_PEER_RECOVERY_START)
async def post_peer_recovery_start(request: Request):
    headers_dict = dict(request.headers)
    body = await request.body()
    is_admin = verify_admin_key(headers_dict, config.admin_key)
    is_peer = False
    err_code = ERR_UNAUTHORIZED
    if not is_admin:
        is_valid, err, _ = verify_peer_request(
            headers=headers_dict, method="POST", path=ROUTE_PEER_RECOVERY_START,
            body=body, secret=config.hmac_secret, nonce_cache=nonce_cache,
            window_seconds=config.timestamp_window_seconds
        )
        if is_valid:
            is_peer = True
        else:
            err_code = err or ERR_UNAUTHORIZED

    if not (is_admin or is_peer):
        return JSONResponse(status_code=401, content=make_error(err_code, f"Authentication failed: {err_code}", config.node_id, state_machine.current_epoch))

    peer_url = config.peer_url
    auto_reconcile = True
    if body:
        try:
            payload = json.loads(body.decode("utf-8"))
            if isinstance(payload, dict):
                peer_url = payload.get("peer_url", peer_url)
                auto_reconcile = payload.get("auto_reconcile", auto_reconcile)
        except Exception:
            pass

    start_ok, start_msg, start_data = recovery_coordinator.start_recovery(peer_url)
    if not start_ok:
        return JSONResponse(status_code=500, content=make_error("RECOVERY_START_FAILED", start_msg, config.node_id, state_machine.current_epoch, details=start_data))

    if auto_reconcile:
        rec_ok, rec_msg, rec_data = recovery_coordinator.reconcile_from_peer(peer_url)
        if not rec_ok:
            status_code = 409 if rec_data and rec_data.get("status") == "CONFLICT_DETECTED" else 500
            return JSONResponse(status_code=status_code, content=make_error("RECONCILIATION_FAILED", rec_msg, config.node_id, state_machine.current_epoch, details=rec_data))
        return JSONResponse(status_code=200, content=make_success({"start": start_data, "reconciliation": rec_data}, config.node_id, state_machine.current_epoch))

    return JSONResponse(status_code=200, content=make_success(start_data, config.node_id, state_machine.current_epoch))


@app.post(ROUTE_PEER_RECOVERY_COMPLETE)
async def post_peer_recovery_complete(request: Request):
    headers_dict = dict(request.headers)
    body = await request.body()
    is_admin = verify_admin_key(headers_dict, config.admin_key)
    is_peer = False
    err_code = ERR_UNAUTHORIZED
    if not is_admin:
        is_valid, err, _ = verify_peer_request(
            headers=headers_dict, method="POST", path=ROUTE_PEER_RECOVERY_COMPLETE,
            body=body, secret=config.hmac_secret, nonce_cache=nonce_cache,
            window_seconds=config.timestamp_window_seconds
        )
        if is_valid:
            is_peer = True
        else:
            err_code = err or ERR_UNAUTHORIZED

    if not (is_admin or is_peer):
        return JSONResponse(status_code=401, content=make_error(err_code, f"Authentication failed: {err_code}", config.node_id, state_machine.current_epoch))

    ok, msg, data = recovery_coordinator.complete_recovery()
    return JSONResponse(status_code=200, content=make_success(data, config.node_id, state_machine.current_epoch))


@app.post(ROUTE_PEER_FAILBACK)
async def post_peer_failback(request: Request):
    headers_dict = dict(request.headers)
    body = await request.body()
    is_admin = verify_admin_key(headers_dict, config.admin_key)
    is_peer = False
    err_code = ERR_UNAUTHORIZED
    if not is_admin:
        is_valid, err, _ = verify_peer_request(
            headers=headers_dict, method="POST", path=ROUTE_PEER_FAILBACK,
            body=body, secret=config.hmac_secret, nonce_cache=nonce_cache,
            window_seconds=config.timestamp_window_seconds
        )
        if is_valid:
            is_peer = True
        else:
            err_code = err or ERR_UNAUTHORIZED

    if not (is_admin or is_peer):
        return JSONResponse(status_code=401, content=make_error(err_code, f"Authentication failed: {err_code}", config.node_id, state_machine.current_epoch))

    peer_url = config.peer_url
    if body:
        try:
            payload = json.loads(body.decode("utf-8"))
            if isinstance(payload, dict):
                peer_url = payload.get("peer_url", peer_url)
        except Exception:
            pass

    ok, msg, data = recovery_coordinator.initiate_failback(peer_url)
    if not ok:
        return JSONResponse(status_code=409, content=make_error("FAILBACK_FAILED", msg, config.node_id, state_machine.current_epoch, details=data))

    return JSONResponse(status_code=200, content=make_success(data, config.node_id, state_machine.current_epoch))


@app.get(ROUTE_PEER_CHANGES)
async def get_peer_changes(request: Request, from_sequence: int = 0, limit: int = 50):
    headers_dict = dict(request.headers)
    is_admin = verify_admin_key(headers_dict, config.admin_key)
    is_peer = False
    err_code = ERR_UNAUTHORIZED
    if not is_admin:
        is_valid, err, _ = verify_peer_request(
            headers=headers_dict, method="GET", path=ROUTE_PEER_CHANGES,
            body=b"", secret=config.hmac_secret, nonce_cache=nonce_cache,
            window_seconds=config.timestamp_window_seconds
        )
        if is_valid:
            is_peer = True
        else:
            err_code = err or ERR_UNAUTHORIZED

    if not (is_admin or is_peer):
        return JSONResponse(status_code=401, content=make_error(err_code, f"Authentication failed: {err_code}", config.node_id, state_machine.current_epoch))

    events = db.get_unreplicated_changes(peer_node_id="phone", from_sequence=from_sequence, limit=limit)
    highest_seq = db.get_highest_local_sequence("laptop")
    data = {
        "events": events,
        "count": len(events),
        "highest_sequence": highest_seq,
        "from_sequence": from_sequence
    }
    return JSONResponse(status_code=200, content=make_success(data, config.node_id, state_machine.current_epoch))


@app.get("/api/v1/peer/hash")
async def get_peer_hash(request: Request, table: str = "portfolio_inquiries"):
    headers_dict = dict(request.headers)
    is_admin = verify_admin_key(headers_dict, config.admin_key)
    is_peer = False
    err_code = ERR_UNAUTHORIZED
    if not is_admin:
        is_valid, err, _ = verify_peer_request(
            headers=headers_dict, method="GET", path="/api/v1/peer/hash",
            body=b"", secret=config.hmac_secret, nonce_cache=nonce_cache,
            window_seconds=config.timestamp_window_seconds
        )
        if is_valid:
            is_peer = True
        else:
            err_code = err or ERR_UNAUTHORIZED

    if not (is_admin or is_peer):
        return JSONResponse(status_code=401, content=make_error(err_code, f"Authentication failed: {err_code}", config.node_id, state_machine.current_epoch))

    h = db.get_canonical_hash(table)
    return JSONResponse(status_code=200, content=make_success({"table": table, "hash": h}, config.node_id, state_machine.current_epoch))


# --- 4. Portfolio Read Endpoints ---

@app.get("/api/v1/portfolio/profile")
@app.get("/api/v1/profile")
async def get_portfolio_profile():
    profile = db.get_profile()
    if not profile:
        return JSONResponse(status_code=404, content=make_error(ERR_NOT_FOUND, "Profile not found", config.node_id, config.epoch))
    return JSONResponse(status_code=200, content=make_success(profile, config.node_id, config.epoch))


@app.get("/api/v1/portfolio/skills")
@app.get("/api/v1/skills")
async def get_portfolio_skills():
    skills = db.get_skills()
    return JSONResponse(status_code=200, content=make_success({"skills": skills, "count": len(skills)}, config.node_id, config.epoch))


@app.get("/api/v1/portfolio/projects")
@app.get("/api/v1/projects")
async def get_portfolio_projects():
    projects = db.get_projects()
    return JSONResponse(status_code=200, content=make_success({"projects": projects, "count": len(projects)}, config.node_id, config.epoch))


@app.get("/api/v1/portfolio/experience")
@app.get("/api/v1/experience")
async def get_portfolio_experience():
    experience = db.get_experience()
    return JSONResponse(status_code=200, content=make_success({"experience": experience, "count": len(experience)}, config.node_id, config.epoch))


@app.get("/api/v1/portfolio/education")
@app.get("/api/v1/education")
async def get_portfolio_education():
    education = db.get_education()
    return JSONResponse(status_code=200, content=make_success({"education": education, "count": len(education)}, config.node_id, config.epoch))


@app.get("/api/v1/portfolio/certifications")
@app.get("/api/v1/certifications")
async def get_portfolio_certifications():
    certifications = db.get_certifications()
    return JSONResponse(status_code=200, content=make_success({"certifications": certifications, "count": len(certifications)}, config.node_id, config.epoch))


@app.get("/api/v1/portfolio/contact")
@app.get("/api/v1/contact")
async def get_portfolio_contact():
    contact = db.get_contact()
    if not contact:
        return JSONResponse(status_code=404, content=make_error(ERR_NOT_FOUND, "Contact details not found", config.node_id, config.epoch))
    return JSONResponse(status_code=200, content=make_success(contact, config.node_id, config.epoch))


@app.get("/api/v1/portfolio/inquiries")
@app.get("/api/v1/inquiries")
async def get_portfolio_inquiries():
    inquiries = db.get_inquiries()
    return JSONResponse(status_code=200, content=make_success({"inquiries": inquiries, "count": len(inquiries)}, config.node_id, config.epoch))


# --- 5. Portfolio Protected Write Endpoint ---

class InquiryModel(BaseModel):
    name: str
    email: str
    subject: Optional[str] = "General Inquiry"
    message: str


@app.post("/api/v1/portfolio/contact", status_code=201)
@app.post("/api/v1/portfolio/inquiry", status_code=201)
@app.post("/api/v1/contact", status_code=201)
async def post_portfolio_inquiry(inquiry: InquiryModel):
    is_primary = state_machine.is_writable()
    current_epoch = state_machine.current_epoch

    ok, err_code, err_msg, op_id = db.submit_inquiry(
        origin_node_id=config.node_id,
        origin_epoch=current_epoch,
        name=inquiry.name,
        email=inquiry.email,
        subject=inquiry.subject or "General Inquiry",
        message=inquiry.message,
        is_primary=is_primary,
        cluster_id=config.cluster_id,
        secret=config.hmac_secret
    )

    if not ok:
        status_code = 403 if err_code == "FORBIDDEN" else 500
        return JSONResponse(
            status_code=status_code,
            content=make_error(err_code or "WRITE_FAILED", err_msg or "Write rejected", config.node_id, current_epoch)
        )

    return JSONResponse(status_code=201, content=make_success({
        "operation_id": op_id,
        "status": "PERSISTED_IN_OUTBOX",
        "message": "Inquiry accepted and queued for replication"
    }, config.node_id, current_epoch))


# --- 6. Unsupported Features Handlers ---

@app.post("/api/v1/portfolio/upload")
@app.post("/api/v1/upload")
async def post_unsupported_upload():
    err = make_error(
        code="FEATURE_UNSUPPORTED_DURING_FAILOVER",
        message="File uploads are strictly unsupported during failover and safe mode.",
        node_id=config.node_id,
        epoch=config.epoch
    )
    return JSONResponse(status_code=400, content=err)


@app.get("/ws")
async def get_unsupported_websocket():
    err = make_error(
        code="FEATURE_UNSUPPORTED_DURING_FAILOVER",
        message="WebSockets are strictly unsupported during failover and safe mode.",
        node_id=config.node_id,
        epoch=config.epoch
    )
    return JSONResponse(status_code=400, content=err)


def main():
    print(f"Laptop node listening on http://{config.host}:{config.port} (Role: {config.initial_role})")
    uvicorn.run(app, host=config.host, port=config.port, log_config=None)


if __name__ == "__main__":
    main()
