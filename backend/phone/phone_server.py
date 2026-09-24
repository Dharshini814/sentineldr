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
            elif clean_path == "/dr-status":
                self._handle_get_dr_status()
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
            
            # ENTERPRISE APPROACH: Serve from same path as laptop server
            # Both servers now serve identical portfolio content
            logger.info("[PORTFOLIO] Serving failover portfolio from same source as laptop")
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
        """Return the SAME portfolio HTML that laptop server serves with live DR status.
        
        ENTERPRISE PATTERN: Content served with real-time disaster recovery monitoring
        - Both servers serve identical portfolio content
        - Live status updates for demonstration
        - Auto-refresh for real-time monitoring
        """
        try:
            # Try to read from the original portfolio file
            portfolio_path = Path(__file__).parent.parent.parent / "frontend" / "portfolio" / "index.html"
            
            if portfolio_path.exists():
                logger.info("[PORTFOLIO] Serving from original portfolio file with DR status monitoring")
                with open(portfolio_path, 'r', encoding='utf-8') as f:
                    original_content = f.read()
                
                # Add live DR status monitoring to the original portfolio
                return self._add_dr_status_to_portfolio(original_content)
            else:
                # Fallback: embedded minimal portfolio with DR status
                logger.info("[PORTFOLIO] Serving fallback portfolio with DR monitoring")
                return self._get_fallback_portfolio_with_dr_status()
                
        except Exception as e:
            logger.error(f"[PORTFOLIO] Error loading portfolio: {e}")
            return self._get_basic_fallback_portfolio()
    
    def _add_dr_status_to_portfolio(self, original_html):
        """Add live DR status monitoring to the original portfolio"""
        # Get real-time DR status
        dr_status = self._get_dr_status_info()
        
        # Create the DR status banner
        dr_banner = f'''
    <!-- Live Disaster Recovery Status Banner -->
    <div id="dr-status-banner" style="
        position: fixed; top: 0; left: 0; right: 0; z-index: 9999;
        background: linear-gradient(135deg, #2C3E50 0%, #34495E 100%);
        color: white; padding: 15px; text-align: center;
        box-shadow: 0 2px 10px rgba(0,0,0,0.3);
        border-bottom: 3px solid {dr_status['banner_color']};
    ">
        <div style="max-width: 1200px; margin: 0 auto; display: flex; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 15px;">
            <div style="display: flex; align-items: center; gap: 10px;">
                <div style="
                    width: 12px; height: 12px; border-radius: 50%;
                    background: {dr_status['status_color']}; 
                    animation: pulse 2s infinite;
                "></div>
                <strong>🛡️ SentinelDR Status:</strong>
                <span id="dr-status-text">{dr_status['message']}</span>
            </div>
            <div style="font-size: 0.9em; opacity: 0.8;">
                <span id="dr-uptime">Server: {dr_status['server_info']}</span> | 
                <span id="dr-sync">Sync: v{dr_status['sync_version']}</span> |
                <span id="dr-timestamp">Updated: {dr_status['timestamp']}</span>
            </div>
        </div>
    </div>
    
    <script>
        // Auto-refresh DR status every 3 seconds
        let drStatusInterval;
        let pageRefreshTimeout;
        
        function updateDRStatus() {{
            fetch('/dr-status')
                .then(response => response.json())
                .then(data => {{
                    document.getElementById('dr-status-text').textContent = data.message;
                    document.getElementById('dr-uptime').textContent = 'Server: ' + data.server_info;
                    document.getElementById('dr-sync').textContent = 'Sync: v' + data.sync_version;
                    document.getElementById('dr-timestamp').textContent = 'Updated: ' + data.timestamp;
                    
                    // Update banner color based on status
                    const banner = document.getElementById('dr-status-banner');
                    banner.style.borderBottomColor = data.banner_color;
                    
                    // Log status changes for demonstration
                    const currentMessage = data.message;
                    if (window.lastDRMessage !== currentMessage) {{
                        console.log('🛡️ SentinelDR Status Change:', currentMessage);
                        window.lastDRMessage = currentMessage;
                        
                        // Show notification for key events
                        if (currentMessage.includes('PRIMARY SERVER RECOVERED')) {{
                            showNotification('Primary server came back online! Preparing for handover...', 'success');
                        }} else if (currentMessage.includes('DISASTER RECOVERY ACTIVE')) {{
                            showNotification('Disaster recovery mode active - serving from secondary', 'warning');
                        }} else if (currentMessage.includes('Synchronizing')) {{
                            showNotification('Synchronizing with primary server...', 'info');
                        }}
                    }}
                    
                    // Check if we should redirect back to primary
                    if (data.redirect_to_primary && data.primary_url) {{
                        clearInterval(drStatusInterval);
                        showTransferMessage(data.primary_url);
                    }}
                }})
                .catch(err => console.log('DR status update failed:', err));
        }}
        
        function showNotification(message, type) {{
            // Create a temporary notification
            const notification = document.createElement('div');
            notification.style.cssText = `
                position: fixed; top: 100px; right: 20px; z-index: 10000;
                background: ${{type === 'success' ? '#27AE60' : type === 'warning' ? '#F39C12' : '#3498DB'}};
                color: white; padding: 15px 20px; border-radius: 8px;
                box-shadow: 0 4px 15px rgba(0,0,0,0.3); max-width: 400px;
                transform: translateX(100%); transition: transform 0.3s ease;
            `;
            notification.textContent = message;
            document.body.appendChild(notification);
            
            // Animate in
            setTimeout(() => notification.style.transform = 'translateX(0)', 100);
            
            // Remove after 4 seconds
            setTimeout(() => {{
                notification.style.transform = 'translateX(100%)';
                setTimeout(() => document.body.removeChild(notification), 300);
            }}, 4000);
        }}
        
        function showTransferMessage(primaryUrl) {{
            console.log('🔄 SentinelDR: Initiating transfer back to primary server');
            
            const banner = document.getElementById('dr-status-banner');
            banner.innerHTML = `
                <div style="max-width: 1200px; margin: 0 auto; text-align: center;">
                    <div style="display: flex; align-items: center; justify-content: center; gap: 15px; margin-bottom: 10px;">
                        <div style="width: 15px; height: 15px; border-radius: 50%; background: #27AE60; animation: pulse 0.8s infinite;"></div>
                        <strong style="font-size: 1.1em;">🔄 CONTROL TRANSFER IN PROGRESS</strong>
                        <div style="width: 15px; height: 15px; border-radius: 50%; background: #27AE60; animation: pulse 0.8s infinite;"></div>
                    </div>
                    <div style="margin: 10px 0;">
                        ✅ Primary server recovery confirmed<br>
                        ✅ Data synchronization completed<br>
                        ✅ Handover sequence initiated
                    </div>
                    <div style="font-size: 1em; margin-top: 15px;">
                        Redirecting to primary server in <span id="countdown">5</span> seconds
                    </div>
                </div>
            `;
            banner.style.borderBottomColor = '#27AE60';
            banner.style.background = 'linear-gradient(135deg, #27AE60, #2ECC71)';
            
            // Show success notification
            showNotification('✅ Primary server recovered! Transferring control back...', 'success');
            
            // Countdown and redirect
            let countdown = 5;
            const countdownInterval = setInterval(() => {{
                countdown--;
                const countdownEl = document.getElementById('countdown');
                if (countdownEl) countdownEl.textContent = countdown;
                
                if (countdown <= 0) {{
                    clearInterval(countdownInterval);
                    console.log('🎯 SentinelDR: Redirecting to primary server at', primaryUrl);
                    window.location.href = primaryUrl;
                }}
            }}, 1000);
        }}
        
        // Start DR status monitoring
        updateDRStatus(); // Initial update
        drStatusInterval = setInterval(updateDRStatus, 3000); // Update every 3 seconds
        
        // Add CSS for pulse animation
        const style = document.createElement('style');
        style.textContent = `
            @keyframes pulse {{
                0% {{ opacity: 1; transform: scale(1); }}
                50% {{ opacity: 0.7; transform: scale(1.1); }}
                100% {{ opacity: 1; transform: scale(1); }}
            }}
        `;
        document.head.appendChild(style);
        
        // Adjust page content to account for fixed banner
        document.addEventListener('DOMContentLoaded', function() {{
            document.body.style.paddingTop = '80px';
        }});
    </script>
        '''
        
        # Insert the DR banner right after the <body> tag
        body_index = original_html.find('<body>')
        if body_index != -1:
            body_end = original_html.find('>', body_index) + 1
            modified_html = original_html[:body_end] + dr_banner + original_html[body_end:]
            return modified_html
        else:
            # If no body tag found, just return original with banner prepended
            return dr_banner + original_html
    def _get_dr_status_info(self):
        """Get real-time disaster recovery status information"""
        # Get current system state
        in_failover = config.runtime.get("failover_active", False)
        peer_status = config.runtime.get("peer_status", "unknown")
        peer_host = config.runtime.get("peer_host")
        local_ip = get_local_ip()
        uptime = int(time.time() - config.runtime.get("start_time", time.time()))
        stats = storage.get_storage_stats()
        
        # Check if we just transitioned to primary being healthy
        previous_peer_status = config.runtime.get("previous_peer_status", "unknown")
        if peer_status == "healthy" and previous_peer_status != "healthy":
            logger.warning("🔄 [DR-STATUS] PRIMARY SERVER RECOVERY DETECTED")
            logger.warning("🔗 [DR-STATUS] Primary server came back online - initiating handover sequence")
        config.runtime["previous_peer_status"] = peer_status
        
        # Determine status message and colors based on current state
        if peer_status == "healthy" and not in_failover:
            # Primary is online and healthy - should redirect back
            message = "🔄 PRIMARY SERVER ONLINE - Preparing to transfer control back to primary server"
            status_color = "#27AE60"  # Green
            banner_color = "#27AE60"
            redirect_to_primary = True
            logger.info("🎯 [DR-STATUS] Ready to redirect back to primary server")
        elif peer_status == "healthy" and in_failover:
            # Primary came back online during failover
            message = "🔄 PRIMARY SERVER RECOVERED - Synchronizing data and preparing handover"
            status_color = "#F39C12"  # Orange
            banner_color = "#F39C12"
            redirect_to_primary = False  # Wait for sync to complete
            logger.info("🔄 [DR-STATUS] Primary recovered, sync in progress")
        elif in_failover:
            # Active failover mode
            message = f"🚨 DISASTER RECOVERY ACTIVE - Primary server offline, secondary serving traffic (Uptime: {uptime}s)"
            status_color = "#E74C3C"  # Red
            banner_color = "#E74C3C"
            redirect_to_primary = False
            if uptime % 30 == 0:  # Log every 30 seconds during DR
                logger.warning(f"🚨 [DR-STATUS] Active failover - serving traffic for {uptime}s")
        else:
            # Standby mode
            message = f"🛡️ SECONDARY STANDBY - Monitoring primary server health (Uptime: {uptime}s)"
            status_color = "#3498DB"  # Blue
            banner_color = "#3498DB"
            redirect_to_primary = False
        
        # Format timestamp
        timestamp = datetime.now(timezone.utc).strftime("%H:%M:%S UTC")
        
        return {
            "message": message,
            "status_color": status_color,
            "banner_color": banner_color,
            "server_info": f"{config.NODE_ID} ({local_ip}:8001)",
            "sync_version": stats.get("sync_version", 0),
            "timestamp": timestamp,
            "failover_active": in_failover,
            "peer_status": peer_status,
            "peer_host": peer_host,
            "redirect_to_primary": redirect_to_primary,
            "primary_url": f"http://{peer_host}:{config.PEER_PORT}/" if peer_host else None
        }
    
    def _get_fallback_portfolio_with_dr_status(self):
        """Fallback portfolio with DR status monitoring"""
        dr_status = self._get_dr_status_info()
        
        return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Dharshini J - Portfolio</title>
    <style>
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            margin: 0; padding: 20px; padding-top: 100px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white; min-height: 100vh;
        }}
        .container {{ 
            max-width: 1000px; margin: 0 auto; 
            background: rgba(255,255,255,0.1); 
            padding: 40px; border-radius: 15px;
        }}
        @keyframes pulse {{
            0% {{ opacity: 1; transform: scale(1); }}
            50% {{ opacity: 0.7; transform: scale(1.1); }}
            100% {{ opacity: 1; transform: scale(1); }}
        }}
    </style>
</head>
<body>
    <div id="dr-status-banner" style="
        position: fixed; top: 0; left: 0; right: 0; z-index: 9999;
        background: linear-gradient(135deg, #2C3E50 0%, #34495E 100%);
        color: white; padding: 15px; text-align: center;
        box-shadow: 0 2px 10px rgba(0,0,0,0.3);
        border-bottom: 3px solid {dr_status['banner_color']};
    ">
        <div style="max-width: 1200px; margin: 0 auto;">
            <div style="display: flex; align-items: center; justify-content: center; gap: 10px;">
                <div style="
                    width: 12px; height: 12px; border-radius: 50%;
                    background: {dr_status['status_color']}; 
                    animation: pulse 2s infinite;
                "></div>
                <strong>🛡️ SentinelDR:</strong>
                <span id="dr-status-text">{dr_status['message']}</span>
            </div>
        </div>
    </div>

    <div class="container">
        <h1>🚀 Dharshini J - Portfolio</h1>
        
        <div style="background: rgba(0,150,255,0.2); padding: 20px; border-radius: 10px; margin: 20px 0; text-align: center;">
            <h3>🛡️ Served via SentinelDR Disaster Recovery</h3>
            <p>Portfolio served by secondary server with live monitoring.</p>
        </div>
        
        <div style="background: rgba(255,255,255,0.1); padding: 30px; border-radius: 10px;">
            <h2>Welcome to my Portfolio</h2>
            <p>BCA student at SSMRV College, Bengaluru building real-world systems.</p>
            
            <h3>📧 Contact</h3>
            <p>Email: dharshinijofficial@gmail.com</p>
            <p>LinkedIn: linkedin.com/in/dharshinijreddy</p>
            <p>GitHub: github.com/Dharshini814</p>
        </div>
    </div>
    
    <script>
        setInterval(() => {{
            fetch('/dr-status')
                .then(response => response.json())
                .then(data => {{
                    document.getElementById('dr-status-text').textContent = data.message;
                    
                    if (data.redirect_to_primary && data.primary_url) {{
                        window.location.href = data.primary_url;
                    }}
                }})
                .catch(err => console.log('Status update failed'));
        }}, 3000);
    </script>
</body>
</html>'''
    
    def _get_basic_fallback_portfolio(self):
        """Basic fallback if all else fails"""
        return '''<!DOCTYPE html>
<html><head><title>Dharshini J - Portfolio</title></head>
<body style="font-family: Arial; padding: 40px; background: #f0f0f0;">
<h1>Dharshini J - Portfolio</h1>
<p>Portfolio served via SentinelDR disaster recovery system.</p>
<p>Contact: dharshinijofficial@gmail.com</p>
</body></html>'''
        """Basic fallback if all else fails"""
        return '''<!DOCTYPE html>
<html><head><title>Dharshini J - Portfolio</title></head>
<body style="font-family: Arial; padding: 40px; background: #f0f0f0;">
<h1>Dharshini J - Portfolio</h1>
<p>Portfolio served via SentinelDR disaster recovery system.</p>
<p>Contact: dharshinijofficial@gmail.com</p>
</body></html>'''

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

    def _handle_get_dr_status(self):
        """GET /dr-status — Live disaster recovery status for AJAX updates."""
        try:
            dr_status = self._get_dr_status_info()
            self._send_json(dr_status)
        except Exception as exc:
            logger.error("[DR-STATUS] Error: %s", exc)
            self._send_error(500, "DR status check failed")

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