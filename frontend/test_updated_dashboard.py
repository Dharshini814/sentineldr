#!/usr/bin/env python3
"""
Test the updated dashboard with phone server detection
"""

import http.server
import socketserver
import webbrowser
import threading
import time
import os

PORT = 5175  # Different port to avoid conflicts

class UpdatedDashboardHandler(http.server.SimpleHTTPRequestHandler):
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
        # Serve the updated dashboard for root requests
        if self.path == '/' or self.path == '':
            self.path = '/sentineldr_dashboard.html'
        return super().do_GET()

def open_browser():
    time.sleep(1.5)
    webbrowser.open(f'http://localhost:{PORT}')

def main():
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    try:
        with socketserver.TCPServer(("", PORT), UpdatedDashboardHandler) as httpd:
            print("🚀 Testing Updated SentinelDR Dashboard...")
            print(f"📊 Updated Dashboard: http://localhost:{PORT}")
            print(f"💻 Primary API: http://localhost:8000")
            print(f"📱 DR Node API: http://localhost:8001")
            print("🔧 Features: Enhanced phone server detection")
            
            # Open browser in background thread
            threading.Thread(target=open_browser, daemon=True).start()
            
            # Start server
            httpd.serve_forever()
            
    except KeyboardInterrupt:
        print("\n\n🛑 Test dashboard server stopped")
    except OSError as e:
        print(f"❌ Server error: {e}")

if __name__ == "__main__":
    main()