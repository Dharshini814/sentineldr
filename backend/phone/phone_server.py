"""
SentinelDR — Phone HTTP Server
Standard library ONLY. Runs on Android Termux.
Single-file HTTP server using http.server, threading, json, sqlite3.
"""

import json
import logging
import re
import socket
import threading
import time
import urllib.parse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# ── Phone modules (standard library only) ────────────────────────────────────
import phone.config as config
import phone.storage as storage
import phone.discovery as discovery
import phone.heartbeat as heartbeat
import phone.failover as failover
import phone.sync as sync
from phone.discovery import get_local_ip

logger = logging.getLogger(__name__)


# ── HTTP Handler ──────────────────────────────────────────────────────────────

class SentinelDRHandler(BaseHTTPRequestHandler):
    """
    Phone HTTP request handler.
    Serves all REST endpoints with authentication, JSON responses,
    and zero third-party dependencies.
    """

    def log_message(self, format, *args):
        """Route access logs through Python logging instead of stderr."""
        logger.info("[HTTP] %s", format % args)

    # ── Authentication ────────────────────────────────────────────────────────

    def _check_auth(self) -> bool:
        """Check X-API-Key header against config.API_KEY."""
        api_key = self.headers.get("X-API-Key", "")
        return api_key == config.API_KEY

    # ── Response helpers ──────────────────────────────────────────────────────

    def _send_json(self, data: dict, status: int = 200) -> None:
        """Send a JSON response with correct headers."""
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "X-API-Key, Content-Type")
        self.end_headers()
        self.wfile.write(body)

    def _send_error(self, status: int, message: str) -> None:
        """Send an error response."""
        self._send_json({"error": message}, status)

    def _read_body(self) -> dict:
        """Read and parse JSON request body."""
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length == 0:
                return {}
            body = self.rfile.read(length).decode("utf-8")
            return json.loads(body)
        except (ValueError, json.JSONDecodeError):
            return {}

    # ── Path parsing ──────────────────────────────────────────────────────────

    def _parse_path(self) -> tuple[str, dict]:
        """Parse self.path into (clean_path, query_params_dict)."""
        parts = self.path.split("?", 1)
        clean_path = parts[0]
        query_params = {}
        if len(parts) > 1:
            query_params = urllib.parse.parse_qs(parts[1])
            # Flatten single-value params
            for k, v in query_params.items():
                if isinstance(v, list) and len(v) == 1:
                    query_params[k] = v[0]
        return clean_path, query_params

    def _match_path(self, pattern: str) -> dict | None:
        """
        Match paths with {id} style parameters.
        Returns dict of extracted params or None if no match.
        """
        clean_path, _ = self._parse_path()
        
        # Convert pattern like "/portfolio/projects/{id}" to regex
        regex_pattern = re.escape(pattern).replace(r"\{id\}", r"([^/]+)")
        match = re.fullmatch(regex_pattern, clean_path)
        
        if match:
            return {"id": match.group(1)}
        return None

    # ── Route handlers ────────────────────────────────────────────────────────

    def do_OPTIONS(self):
        """Handle CORS preflight requests."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "X-API-Key, Content-Type")
        self.end_headers()

    def do_GET(self):
        """Handle GET requests."""
        try:
            clean_path, query_params = self._parse_path()
            print(f"[DEBUG] GET request to: {clean_path}")  # Debug line
            logger.info("[HTTP] GET request to: %s", clean_path)

            if clean_path == "/":
                print("[DEBUG] Calling portfolio handler")  # Debug line
                self._handle_get_portfolio()
            elif clean_path == "/health":
                self._handle_get_health()
            elif clean_path == "/heartbeat":
                self._handle_get_heartbeat()
            elif clean_path == "/portfolio/projects":
                self._handle_get_projects()
            elif self._match_path("/portfolio/projects/{id}"):
                params = self._match_path("/portfolio/projects/{id}")
                self._handle_get_project(params["id"])
            elif clean_path == "/events":
                limit = int(query_params.get("limit", 50))
                self._handle_get_events(limit)
            elif clean_path == "/status":
                self._handle_get_status()
            else:
                print(f"[DEBUG] No route matched for: {clean_path}")  # Debug line
                self._send_error(404, "Not found")

        except Exception as exc:
            logger.error("[HTTP] GET %s failed: %s", self.path, exc)
            self._send_error(500, "Internal server error")

    def do_POST(self):
        """Handle POST requests."""
        try:
            clean_path, _ = self._parse_path()

            if clean_path == "/sync/snapshot":
                self._handle_post_sync_snapshot()
            elif clean_path == "/recovery-announcement":
                self._handle_post_recovery_announcement()
            elif self._match_path("/events/{id}/acknowledge"):
                params = self._match_path("/events/{id}/acknowledge")
                self._handle_post_acknowledge_event(params["id"])
            else:
                self._send_error(404, "Not found")

        except Exception as exc:
            logger.error("[HTTP] POST %s failed: %s", self.path, exc)
            self._send_error(500, "Internal server error")

    # ── GET handlers ──────────────────────────────────────────────────────────

    def _handle_get_portfolio(self):
        """GET / — Serve portfolio HTML during failover or when primary is unreachable.
        
        ENTERPRISE APPROACH: Content served from embedded data, not file system.
        This simulates how enterprise systems use CDNs, object storage, or databases
        rather than local file dependencies.
        """
        try:
            # Check if we're in active failover mode
            in_failover = config.runtime.get("failover_active", False)
            peer_status = config.runtime.get("peer_status", "unknown")
            
            logger.info("[PORTFOLIO] Request received - failover_active: %s, peer_status: %s", in_failover, peer_status)
            
            # Try to determine if primary is available
            primary_available = (peer_status == "healthy")
            
            if not in_failover and primary_available:
                # Primary is healthy - redirect to primary
                peer_host = config.runtime.get("peer_host")
                if peer_host:
                    redirect_url = f"http://{peer_host}:{config.PEER_PORT}/"
                    logger.info("[PORTFOLIO] Redirecting to primary: %s", redirect_url)
                    self.send_response(302)
                    self.send_header("Location", redirect_url)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    return
            
            # Either we're in failover OR primary is not available - serve portfolio
            logger.info("[PORTFOLIO] Serving failover portfolio (failover: %s, primary_available: %s)", in_failover, primary_available)
            
            # ENTERPRISE APPROACH: Serve from embedded content (simulates CDN/object storage)
            # No file system dependencies - content is embedded in the application
            logger.info("[PORTFOLIO] Serving from embedded content (enterprise-style)")
            content = self._get_embedded_portfolio()
            
            # Send HTML response
            body = content.encode('utf-8')
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
            logger.info("[PORTFOLIO] Portfolio served successfully via embedded content")
                
        except Exception as exc:
            logger.error("[PORTFOLIO] Error serving portfolio: %s", exc)
            self._send_error(500, "Failed to serve portfolio")
    
    def _get_embedded_portfolio(self):
        """Return enterprise-style portfolio HTML served from embedded content.
        
        ENTERPRISE PATTERN: Content embedded in application (simulates CDN/object storage)
        - No file system dependencies
        - Content served from memory
        - Includes disaster recovery information
        - Self-contained HTML with embedded CSS/styling
        """
        # Get real-time system statistics for display
        stats = storage.get_storage_stats()
        local_ip = get_local_ip()
        uptime = int(time.time() - config.runtime.get("start_time", time.time()))
        failover_status = "Active" if config.runtime.get("failover_active", False) else "Standby"
        
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dharshini J - Portfolio</title>
    <style>
        /* Enterprise-grade responsive design */
        * {{ margin: 0; padding: 0; box-sizing: border-box; }}
        
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #2C3E50 0%, #34495E 50%, #2C3E50 100%);
            color: #ECF0F1;
            min-height: 100vh;
            line-height: 1.6;
        }}
        
        .enterprise-header {{
            background: rgba(52, 73, 94, 0.95);
            padding: 15px 0;
            border-bottom: 2px solid #3498DB;
            backdrop-filter: blur(10px);
        }}
        
        .container {{ 
            max-width: 1200px; 
            margin: 0 auto; 
            padding: 0 20px;
        }}
        
        .dr-status {{
            background: linear-gradient(135deg, #3498DB, #2980B9);
            color: white;
            padding: 20px;
            text-align: center;
            margin: 20px 0;
            border-radius: 8px;
            box-shadow: 0 4px 15px rgba(52, 152, 219, 0.3);
        }}
        
        .portfolio-main {{
            display: grid;
            grid-template-columns: 2fr 1fr;
            gap: 30px;
            margin: 30px 0;
        }}
        
        .content-section {{
            background: rgba(44, 62, 80, 0.8);
            padding: 30px;
            border-radius: 10px;
            border: 1px solid rgba(52, 152, 219, 0.3);
        }}
        
        .system-metrics {{
            background: rgba(39, 174, 96, 0.1);
            border: 1px solid rgba(39, 174, 96, 0.3);
        }}
        
        .metric-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
            margin: 20px 0;
        }}
        
        .metric-card {{
            background: rgba(44, 62, 80, 0.6);
            padding: 15px;
            border-radius: 6px;
            text-align: center;
            border: 1px solid rgba(52, 152, 219, 0.2);
        }}
        
        .metric-value {{
            font-size: 1.8em;
            font-weight: bold;
            color: #3498DB;
            display: block;
        }}
        
        .metric-label {{
            font-size: 0.9em;
            color: #BDC3C7;
            margin-top: 5px;
        }}
        
        h1 {{ 
            text-align: center; 
            color: #3498DB; 
            font-size: 2.5em;
            margin: 20px 0;
            text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
        }}
        
        h2 {{ color: #E74C3C; margin: 25px 0 15px 0; }}
        h3 {{ color: #F39C12; margin: 20px 0 10px 0; }}
        
        .enterprise-badge {{
            display: inline-block;
            background: linear-gradient(45deg, #E74C3C, #C0392B);
            color: white;
            padding: 8px 15px;
            border-radius: 20px;
            font-size: 0.9em;
            font-weight: bold;
            margin: 10px 5px;
        }}
        
        .status-indicator {{
            display: inline-block;
            width: 12px;
            height: 12px;
            background: #27AE60;
            border-radius: 50%;
            margin-right: 8px;
            animation: pulse 2s infinite;
        }}
        
        @keyframes pulse {{
            0% {{ opacity: 1; }}
            50% {{ opacity: 0.5; }}
            100% {{ opacity: 1; }}
        }}
        
        .footer {{
            text-align: center;
            padding: 30px;
            background: rgba(44, 62, 80, 0.6);
            margin-top: 40px;
            border-top: 1px solid rgba(52, 152, 219, 0.3);
        }}
        
        @media (max-width: 768px) {{
            .portfolio-main {{ grid-template-columns: 1fr; }}
            .metric-grid {{ grid-template-columns: 1fr; }}
        }}
    </style>
</head>
<body>
    <div class="enterprise-header">
        <div class="container">
            <h1><span class="status-indicator"></span>Dharshini J - Portfolio</h1>
        </div>
    </div>

    <div class="container">
        <div class="dr-status">
            <h2>🛡️ Enterprise Disaster Recovery System Active</h2>
            <p><strong>SentinelDR Secondary Server</strong> — Providing continuous service during primary server maintenance</p>
            <span class="enterprise-badge">Zero Downtime Architecture</span>
            <span class="enterprise-badge">Auto-Failover Enabled</span>
            <span class="enterprise-badge">Real-time Monitoring</span>
        </div>
        
        <div class="portfolio-main">
            <div class="content-section">
                <h2>💼 Professional Portfolio</h2>
                <p>Welcome to my professional portfolio. This application demonstrates enterprise-level disaster recovery capabilities.</p>
                
                <h3>🏗️ Enterprise Architecture Principles</h3>
                <ul>
                    <li><strong>High Availability:</strong> 99.9%+ uptime through redundant servers</li>
                    <li><strong>Automatic Failover:</strong> Sub-10-second recovery times</li>
                    <li><strong>Content Delivery:</strong> Embedded content delivery (CDN-style)</li>
                    <li><strong>Real-time Monitoring:</strong> Continuous health checks and alerts</li>
                    <li><strong>Geographic Distribution:</strong> Multi-location server deployment</li>
                </ul>
                
                <h3>🔧 Technical Implementation</h3>
                <p>This portfolio is served using enterprise disaster recovery patterns:</p>
                <ul>
                    <li><strong>Smart Proxy:</strong> Intelligent traffic routing and health monitoring</li>
                    <li><strong>Service Discovery:</strong> Automatic secondary server detection</li>
                    <li><strong>Content Embedding:</strong> No file system dependencies (enterprise-style)</li>
                    <li><strong>Real-time Sync:</strong> Data consistency across all servers</li>
                </ul>
            </div>
            
            <div class="content-section system-metrics">
                <h3>📊 Live System Metrics</h3>
                
                <div class="metric-grid">
                    <div class="metric-card">
                        <span class="metric-value">{failover_status}</span>
                        <div class="metric-label">DR Status</div>
                    </div>
                    <div class="metric-card">
                        <span class="metric-value">{uptime}s</span>
                        <div class="metric-label">Uptime</div>
                    </div>
                    <div class="metric-card">
                        <span class="metric-value">{local_ip}</span>
                        <div class="metric-label">Server IP</div>
                    </div>
                    <div class="metric-card">
                        <span class="metric-value">v{stats.get('sync_version', 0)}</span>
                        <div class="metric-label">Sync Version</div>
                    </div>
                    <div class="metric-card">
                        <span class="metric-value">{stats.get('project_count', 0)}</span>
                        <div class="metric-label">Projects</div>
                    </div>
                    <div class="metric-card">
                        <span class="metric-value">{config.NODE_ID}</span>
                        <div class="metric-label">Node ID</div>
                    </div>
                </div>
                
                <h3>🌐 Network Information</h3>
                <p><strong>Current Server:</strong> {config.NODE_ROLE.title()} ({local_ip}:8001)</p>
                <p><strong>Content Source:</strong> Embedded (Enterprise CDN-style)</p>
                <p><strong>Last Sync:</strong> {stats.get('last_sync_time', 'Never')}</p>
            </div>
        </div>
    </div>
    
    <div class="footer">
        <p><strong>SentinelDR Enterprise Disaster Recovery System</strong></p>
        <p>Demonstrating enterprise-grade high availability and automatic failover capabilities</p>
        <p style="font-size: 0.9em; color: #95A5A6; margin-top: 10px;">
            Content served via embedded delivery • No file system dependencies • Enterprise architecture patterns
        </p>
    </div>
</body>
</html>'''

    def _handle_get_health(self):
        """GET /health — Public health endpoint."""
        try:
            # Determine role based on current failover state
            in_failover = config.runtime.get("failover_active", False)
            role = "active_secondary" if in_failover else "secondary"
            
            local_ip = get_local_ip()
            
            # Get storage stats
            stats = storage.get_storage_stats()
            
            # peer_host should be the LAPTOP's IP, not phone's IP
            peer_host = config.runtime.get("peer_host")  # This should be laptop IP from discovery
            peer_reachable = peer_host is not None and config.runtime.get("peer_status") == "healthy"
            
            response = {
                "node_id": config.NODE_ID,
                "role": role,
                "status": "healthy",
                "peer_reachable": peer_reachable,
                "peer_node_id": config.runtime.get("peer_node_id"),
                "peer_host": peer_host,  # Laptop IP, not phone IP
                "failover_active": in_failover,
                "local_ip": local_ip,  # Phone IP
                "uptime_seconds": time.time() - config.runtime.get("start_time", time.time()),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sync_version": stats["sync_version"],
                "last_sync_time": stats["last_sync_time"],   # ISO string from storage
                "project_count": stats["project_count"],
            }
            self._send_json(response)
        except Exception as exc:
            logger.error("[HEALTH] Error: %s", exc)
            self._send_error(500, "Health check failed")

    def _handle_get_heartbeat(self):
        """GET /heartbeat — Receive heartbeat from laptop."""
        if not self._check_auth():
            self._send_error(401, "Unauthorized")
            return

        try:
            # Reset heartbeat state
            config.runtime["missed_heartbeats"] = 0
            config.runtime["peer_status"] = "healthy"
            config.runtime["peer_last_seen"] = time.time()
            config.runtime["heartbeat_sequence"] = config.runtime.get("heartbeat_sequence", 0) + 1

            response = {
                "node_id": config.NODE_ID,
                "role": config.NODE_ROLE,
                "status": "healthy",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "sequence": config.runtime["heartbeat_sequence"],
                "uptime_seconds": time.time() - config.runtime.get("start_time", time.time()),
            }
            self._send_json(response)
        except Exception as exc:
            logger.error("[HEARTBEAT] Error: %s", exc)
            self._send_error(500, "Heartbeat failed")

    def _handle_get_projects(self):
        """GET /portfolio/projects — List all projects."""
        if not self._check_auth():
            self._send_error(401, "Unauthorized")
            return

        try:
            projects = storage.get_all_projects()
            self._send_json(projects)
        except Exception as exc:
            logger.error("[PROJECTS] List error: %s", exc)
            self._send_error(503, "Storage unavailable")

    def _handle_get_project(self, project_id: str):
        """GET /portfolio/projects/{id} — Get single project."""
        if not self._check_auth():
            self._send_error(401, "Unauthorized")
            return

        try:
            project = storage.get_project(project_id)
            if project is None:
                self._send_error(404, "Project not found")
            else:
                self._send_json(project)
        except Exception as exc:
            logger.error("[PROJECTS] Get error: %s", exc)
            self._send_error(503, "Storage unavailable")

    def _handle_get_events(self, limit: int):
        """GET /events — List recent events."""
        if not self._check_auth():
            self._send_error(401, "Unauthorized")
            return

        try:
            events = storage.get_events(limit)
            self._send_json(events)
        except Exception as exc:
            logger.error("[EVENTS] List error: %s", exc)
            self._send_error(503, "Storage unavailable")

    def _handle_get_status(self):
        """GET /status — Full status information."""
        if not self._check_auth():
            self._send_error(401, "Unauthorized")
            return

        try:
            stats = storage.get_storage_stats()
            
            response = {
                "node_id": config.NODE_ID,
                "role": config.NODE_ROLE,
                "failover_active": config.runtime.get("failover_active", False),
                "peer_status": config.runtime.get("peer_status", "offline"),
                "peer_host": config.runtime.get("peer_host"),
                "sync_version": stats["sync_version"],
                "last_sync_time": stats["last_sync_time"],
                "missed_heartbeats": config.runtime.get("missed_heartbeats", 0),
                "missed_heartbeat_threshold": getattr(config, "MISSED_HEARTBEAT_THRESHOLD", 1),
                "heartbeat_interval": getattr(config, "HEARTBEAT_INTERVAL", 3),
                "sync_interval": getattr(config, "SYNC_INTERVAL", 3),
                "uptime_seconds": time.time() - config.runtime.get("start_time", time.time()),
                "storage": {
                    "project_count": stats["project_count"],
                    "event_count": stats["event_count"],
                },
            }
            self._send_json(response)
        except Exception as exc:
            logger.error("[STATUS] Error: %s", exc)
            self._send_error(500, "Status check failed")

    # ── POST handlers ─────────────────────────────────────────────────────────

    def _handle_post_sync_snapshot(self):
        """POST /sync/snapshot — Receive sync data from laptop."""
        if not self._check_auth():
            self._send_error(401, "Unauthorized")
            return

        try:
            data = self._read_body()
            if not data:
                self._send_error(400, "Invalid JSON body")
                return

            # Auth already verified by _check_auth() above; pass a sentinel
            # so sync.receive_snapshot skips its internal key re-check.
            result = sync.receive_snapshot(data, config.API_KEY)

            status_code = 200
            if result.get("status") == "error":
                status_code = 400

            self._send_json(result, status_code)
        except Exception as exc:
            logger.error("[SYNC] Snapshot error: %s", exc)
            self._send_error(500, "Sync failed")

    def _handle_post_recovery_announcement(self):
        """POST /recovery-announcement — Handle laptop recovery."""
        if not self._check_auth():
            self._send_error(401, "Unauthorized")
            return

        try:
            data = self._read_body()
            if not data or "node_id" not in data:
                self._send_error(400, "Invalid recovery announcement")
                return

            # Build peer URL from runtime
            peer_host = config.runtime.get("peer_host")
            if peer_host:
                peer_url = f"http://{peer_host}:{config.PEER_PORT}"
                failover.trigger_recovery(peer_url)

            response = {
                "status": "acknowledged",
                "failover_active": config.runtime.get("failover_active", False),
            }
            self._send_json(response)
        except Exception as exc:
            logger.error("[RECOVERY] Error: %s", exc)
            self._send_error(500, "Recovery failed")

    def _handle_post_acknowledge_event(self, event_id: str):
        """POST /events/{id}/acknowledge — Acknowledge an event."""
        if not self._check_auth():
            self._send_error(401, "Unauthorized")
            return

        try:
            found = storage.acknowledge_event(event_id)
            if not found:
                self._send_error(404, "Event not found")
            else:
                self._send_json({"status": "ok"})
        except Exception as exc:
            logger.error("[EVENTS] Acknowledge error: %s", exc)
            self._send_error(503, "Storage unavailable")


# ── Server startup ────────────────────────────────────────────────────────────

def start_server():
    """
    Start the phone HTTP server.
    
    Startup sequence:
    1. Load config and validate API_KEY
    2. Initialize storage  
    3. Start discovery service
    4. Start heartbeat service
    5. Start HTTP server
    """
    
    # 1. Validate API_KEY
    if not hasattr(config, "API_KEY") or not config.API_KEY:
        print("ERROR: API_KEY not set in phone configuration")
        print("Create backend/phone/.env.phone with:")
        print("API_KEY=your-secret-key")
        return

    # 2. Initialize storage
    try:
        storage.init_storage(config.DB_PATH)
    except Exception as exc:
        logger.error("Failed to initialize storage: %s", exc)
        return

    # 3. Start discovery service
    try:
        discovery_service = discovery.DiscoveryService()
        discovery_service.start()
    except Exception as exc:
        logger.error("Failed to start discovery service: %s", exc)
        return

    # 4. Start heartbeat service  
    try:
        heartbeat_service = heartbeat.HeartbeatService()
        heartbeat_service.start()
    except Exception as exc:
        logger.error("Failed to start heartbeat service: %s", exc)
        return

    # 5. Get local IP and start HTTP server
    try:
        local_ip = get_local_ip()
        
        # Print startup banner
        print("╔══════════════════════════════════════╗")
        print("║     SentinelDR — Phone Secondary    ║")
        print("╠══════════════════════════════════════╣")
        print(f"║  Node ID : {config.NODE_ID:<22} ║")
        print(f"║  Role    : {config.NODE_ROLE:<22} ║")
        print(f"║  Port    : {config.NODE_PORT:<22} ║")
        print(f"║  Local IP: {local_ip:<22} ║")
        print(f"║  DB      : {config.DB_PATH:<22} ║")
        print("╚══════════════════════════════════════╝")
        
        # Start HTTP server
        server = HTTPServer(("0.0.0.0", config.NODE_PORT), SentinelDRHandler)
        logger.info("Phone server listening on 0.0.0.0:%d", config.NODE_PORT)
        server.serve_forever()
        
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as exc:
        logger.error("Server error: %s", exc)


if __name__ == "__main__":
    # Configure logging
    logging.basicConfig(
        level=getattr(logging, getattr(config, "LOG_LEVEL", "INFO"), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    )
    
    start_server()