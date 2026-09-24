#!/usr/bin/env python3
"""
SentinelDR Dashboard Server
Serves the production-ready SentinelDR dashboard with live backend integration
"""

import os
import sys
import http.server
import socketserver
import webbrowser
import threading
import time

# Configuration
PORT = 5173
DASHBOARD_FILE = "sentineldr_dashboard.html"

class SentinelDRHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Add CORS headers for API requests
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        super().end_headers()
    
    def do_GET(self):
        # Serve the dashboard for root requests
        if self.path == '/' or self.path == '':
            self.path = f'/{DASHBOARD_FILE}'
        return super().do_GET()
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

def open_browser():
    """Open browser after server starts"""
    time.sleep(1)
    webbrowser.open(f'http://localhost:{PORT}')

def main():
    # Change to frontend directory
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    # Check if dashboard file exists
    if not os.path.exists(DASHBOARD_FILE):
        print(f"❌ Error: {DASHBOARD_FILE} not found in {os.getcwd()}")
        sys.exit(1)
    
    # Create server
    try:
        with socketserver.TCPServer(("", PORT), SentinelDRHandler) as httpd:
            print("🚀 SentinelDR Dashboard Server Starting...")
            print(f"📊 Dashboard: http://localhost:{PORT}")
            print(f"💻 Primary API: http://localhost:8000")
            print(f"📱 DR Node API: http://localhost:8001")
            print("🔧 Features: Live monitoring, failover testing, sync management")
            print("\n⚡ Server ready! Opening dashboard in browser...")
            
            # Open browser in background thread
            threading.Thread(target=open_browser, daemon=True).start()
            
            # Start server
            httpd.serve_forever()
            
    except KeyboardInterrupt:
        print("\n\n🛑 Dashboard server stopped")
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"❌ Port {PORT} is already in use. Please stop the existing server or use a different port.")
        else:
            print(f"❌ Server error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()