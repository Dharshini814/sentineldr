#!/usr/bin/env python3
"""
SentinelDR Live Dashboard Server - Fresh instance with cache busting
"""

import os
import sys
import http.server
import socketserver
import webbrowser
import threading
import time

PORT = 5174  # Different port to avoid conflicts

class LiveDashboardHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Aggressive cache prevention
        self.send_header('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        # Add CORS headers
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', '*')
        super().end_headers()
    
    def do_GET(self):
        # Serve the live dashboard for root requests
        if self.path == '/' or self.path == '':
            self.path = '/sentineldr_live.html'
        return super().do_GET()
    
    def do_OPTIONS(self):
        self.send_response(200)
        self.end_headers()

def open_browser():
    """Open browser after server starts"""
    time.sleep(1.5)
    webbrowser.open(f'http://localhost:{PORT}')

def main():
    # Change to frontend directory
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    # Create server
    try:
        with socketserver.TCPServer(("", PORT), LiveDashboardHandler) as httpd:
            print("🚀 SentinelDR LIVE Dashboard Starting...")
            print(f"📊 Live Dashboard: http://localhost:{PORT}")
            print(f"💻 Primary API: http://localhost:8000")
            print(f"📱 DR Node API: http://localhost:8001")
            print("🔧 Features: Fresh session, no cache, live monitoring")
            print("\n⚡ Server ready! Opening dashboard in new browser window...")
            
            # Open browser in background thread
            threading.Thread(target=open_browser, daemon=True).start()
            
            # Start server
            httpd.serve_forever()
            
    except KeyboardInterrupt:
        print("\n\n🛑 Live dashboard server stopped")
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"❌ Port {PORT} is already in use. Please stop the existing server or use a different port.")
        else:
            print(f"❌ Server error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()