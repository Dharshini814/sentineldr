#!/usr/bin/env python3
"""
SentinelDR Dashboard Server
Serves the disaster recovery console on http://localhost:5173
"""

import http.server
import socketserver
import os
import webbrowser
import threading
import time

PORT = 5173

class SentinelDRHandler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        # Add CORS headers for API communication
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'X-API-Key, Content-Type')
        super().end_headers()
    
    def log_message(self, format, *args):
        # Custom logging format
        print(f"📊 Dashboard: {format % args}")

def serve_dashboard():
    """Start the SentinelDR dashboard server"""
    os.chdir(os.path.dirname(os.path.abspath(__file__)))
    
    print("╔══════════════════════════════════════════════╗")
    print("║          SentinelDR Dashboard Server        ║") 
    print("╠══════════════════════════════════════════════╣")
    print(f"║  URL: http://localhost:{PORT}                    ║")
    print("║  Dashboard: Real-time DR monitoring         ║")
    print("║  Backend: localhost:8000 (Primary)          ║")
    print("║  DR Node: localhost:8001 (Secondary)        ║")
    print("╚══════════════════════════════════════════════╝")
    print()
    
    try:
        with socketserver.TCPServer(("", PORT), SentinelDRHandler) as httpd:
            print(f"🌐 SentinelDR Dashboard serving at http://localhost:{PORT}")
            print("📊 Live disaster recovery monitoring active")
            print("🔄 Auto-refresh: Every 3 seconds")
            print()
            print("Press Ctrl+C to stop the dashboard server")
            print("-" * 50)
            
            # Auto-open browser after a short delay
            def open_browser():
                time.sleep(2)
                try:
                    webbrowser.open(f"http://localhost:{PORT}")
                    print("🌐 Dashboard opened in browser")
                except:
                    print("💡 Manual: Open http://localhost:5173 in your browser")
            
            threading.Thread(target=open_browser, daemon=True).start()
            
            httpd.serve_forever()
            
    except KeyboardInterrupt:
        print("\n🛑 Dashboard server stopped by user")
    except OSError as e:
        if "Address already in use" in str(e):
            print(f"❌ Port {PORT} is already in use")
            print("💡 Either stop the existing server or use a different port")
        else:
            print(f"❌ Error starting server: {e}")
    except Exception as e:
        print(f"❌ Unexpected error: {e}")

if __name__ == "__main__":
    serve_dashboard()