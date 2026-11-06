"""
SentinelDR - Standalone Frontend Dashboard Server
Port: 8080
Standard library only: http.server.
Runs independently of Laptop (8000) and Phone (8001), allowing you to monitor
cluster failover and stop/restart backend nodes without losing the dashboard UI.
Includes Zero-Conf peer auto-discovery for finding the Phone's IP automatically.
"""

import json
import os
import sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

from shared.discovery import PeerDiscoveryListener

# Global discovery listener
discovery = PeerDiscoveryListener()
discovery.start()


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=FRONTEND_DIR, **kwargs)

    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/")

        # Auto-discovery endpoint for the browser dashboard
        if path == "/api/v1/discovered-peer":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            resp_body = json.dumps({
                "ok": True,
                "data": {
                    "phone_url": discovery.phone_url,
                    "discovered": discovery.discovered_phone_ip is not None,
                    "phone_ip": discovery.discovered_phone_ip or "127.0.0.1",
                    "phone_port": discovery.discovered_phone_port
                }
            }).encode("utf-8")
            self.send_header("Content-Length", str(len(resp_body)))
            self.end_headers()
            self.wfile.write(resp_body)
            return

        if path in ("", "/", "/dashboard"):
            self.path = "/dashboard.html"
        elif path in ("/portfolio",):
            self.path = "/portfolio.html"

        return super().do_GET()


def run_dashboard_server(host: str = "0.0.0.0", port: int = 8080):
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    server.allow_reuse_address = True
    print(f"\n============================================================")
    print(f" [SentinelDR] Dedicated Frontend Dashboard Server Running!  ")
    print(f"------------------------------------------------------------")
    print(f"  URL: http://localhost:{port}/")
    print(f"  (Monitors Laptop on :8000 and Phone on :8001 independently)")
    print(f"  (Auto-Discovery: Active on UDP 8003 & Wi-Fi ARP table)")
    print(f"============================================================")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Dashboard Server...")
        discovery.stop()
        server.server_close()


if __name__ == "__main__":
    port = int(os.getenv("SDR_DASHBOARD_PORT", "8080"))
    run_dashboard_server(port=port)
