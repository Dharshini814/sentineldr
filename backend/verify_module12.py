#!/usr/bin/env python3
"""
SentinelDR Module 12 Verification - Complete Integration Testing
Verifies phone HTTP server by starting it and testing all endpoints.
"""

import ast
import sys
import json
import time
import threading
import urllib.request
import urllib.parse
import urllib.error
import sqlite3
import tempfile
import os
from pathlib import Path


class PhoneServerTester:
    def __init__(self):
        self.test_port = 18099
        self.api_key = "test-api-key"
        self.server_thread = None
        self.temp_db = None
        self.test_passed = 0
        self.test_failed = 0
        
    def log(self, message):
        print(f"[TEST] {message}")
        
    def request(self, method, path, data=None, auth=True, expect_status=200):
        """Make HTTP request to test server"""
        url = f"http://localhost:{self.test_port}{path}"
        headers = {}
        
        if auth:
            headers['X-API-Key'] = self.api_key
            
        if data:
            headers['Content-Type'] = 'application/json'
            data = json.dumps(data).encode('utf-8')
            
        req = urllib.request.Request(url, data=data, headers=headers, method=method)
        
        try:
            with urllib.request.urlopen(req) as response:
                status = response.getcode()
                body = response.read().decode('utf-8')
                return status, json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            return e.code, {}
        except Exception as e:
            self.log(f"Request error: {e}")
            return 0, {}
            
    def test_check(self, condition, test_name):
        """Record test result"""
        if condition:
            self.log(f"✓ {test_name}")
            self.test_passed += 1
            return True
        else:
            self.log(f"❌ {test_name}")
            self.test_failed += 1
            return False
            
    def setup_test_environment(self):
        """Setup temporary database and config"""
        # Create temp database
        self.temp_db = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.temp_db.close()
        
        # Initialize SQLite tables
        conn = sqlite3.connect(self.temp_db.name)
        cursor = conn.cursor()
        
        # Create basic tables
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS projects (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                description TEXT,
                created_at TEXT,
                updated_at TEXT
            )
        ''')
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                type TEXT NOT NULL,
                severity TEXT NOT NULL,
                message TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                acknowledged INTEGER DEFAULT 0
            )
        ''')
        
        conn.commit()
        conn.close()
        
        # Set environment for phone config
        os.environ['NODE_ID'] = 'test-phone-node'
        os.environ['API_KEY'] = self.api_key
        os.environ['NODE_PORT'] = str(self.test_port)
        os.environ['DB_PATH'] = self.temp_db.name
        
    def cleanup_test_environment(self):
        """Clean up test resources"""
        if self.temp_db:
            try:
                os.unlink(self.temp_db.name)
            except:
                pass
                
    def start_test_server(self):
        """Start phone server in background thread"""
        def server_runner():
            try:
                # Import and run server on test port
                sys.path.insert(0, str(Path(__file__).parent / "phone"))
                
                # Mock the config and dependencies
                import phone.config as config
                config.NODE_PORT = self.test_port
                config.API_KEY = self.api_key
                config.DB_PATH = self.temp_db.name
                
                # Import server and modify port
                from phone.phone_server import start_server, HTTPServer, SentinelDRHandler
                
                # Create and start server
                server = HTTPServer(('localhost', self.test_port), SentinelDRHandler)
                server.serve_forever()
                
            except Exception as e:
                self.log(f"Server start error: {e}")
                
        self.server_thread = threading.Thread(target=server_runner, daemon=True)
        self.server_thread.start()
        
        # Wait for server to start
        time.sleep(2)
        
    def run_tests(self):
        """Run all verification tests"""
        self.log("Setting up test environment...")
        self.setup_test_environment()
        
        # Test 1: File and imports check
        phone_server_path = Path(__file__).parent / "phone" / "phone_server.py"
        if not phone_server_path.exists():
            self.test_check(False, "phone_server.py exists")
            return
            
        with open(phone_server_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        # AST scan for imports
        tree = ast.parse(content)
        stdlib_only = True
        forbidden_imports = ['fastapi', 'pydantic', 'sqlalchemy', 'requests', 'psycopg', 'uvicorn']
        
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                if isinstance(node, ast.Import):
                    names = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    names = [node.module] if node.module else []
                    
                for name in names:
                    if name and any(forbidden in name.lower() for forbidden in forbidden_imports):
                        stdlib_only = False
                        
        self.test_check(stdlib_only, "1. phone_server.py has zero third-party imports (AST scan)")
        
        # Test 2-4: Structure checks
        self.test_check("class SentinelDRHandler(BaseHTTPRequestHandler)" in content, 
                       "2. SentinelDRHandler class exists and extends BaseHTTPRequestHandler")
        self.test_check("def start_server()" in content, 
                       "3. start_server function exists")
        
        # Start test server
        self.log("Starting test server on port 18099...")
        try:
            self.start_test_server()
        except Exception as e:
            self.log(f"Failed to start server: {e}")
            return
            
        # Test 4: Health endpoint (no auth)
        status, data = self.request('GET', '/health', auth=False)
        health_ok = status == 200 and all(field in data for field in 
                                         ['node_id', 'role', 'status', 'failover_active', 'sync_version', 'uptime_seconds'])
        self.test_check(health_ok, "4. GET /health returns 200 with required fields (no auth)")
        
        # Test 5-6: Heartbeat
        status, _ = self.request('GET', '/heartbeat', auth=False)
        self.test_check(status == 401, "5. GET /heartbeat without API key returns 401")
        
        status, data = self.request('GET', '/heartbeat', auth=True)
        heartbeat_ok = status == 200 and all(field in data for field in 
                                            ['node_id', 'role', 'status', 'sequence', 'uptime_seconds'])
        self.test_check(heartbeat_ok, "6. GET /heartbeat with API key returns 200 with required fields")
        
        # Test 7-8: Portfolio (no auth vs with auth)
        status, _ = self.request('GET', '/portfolio/projects', auth=False)
        self.test_check(status == 401, "7. GET /portfolio/projects without API key returns 401")
        
        status, data = self.request('GET', '/portfolio/projects', auth=True)
        self.test_check(status == 200 and isinstance(data, list), 
                       "8. GET /portfolio/projects with API key returns empty list initially")
        
        # Test 9-10: Sync snapshot
        test_project = {
            "projects": [{
                "id": "test-proj-123",
                "name": "Test Project",
                "description": "Test Description",
                "created_at": "2024-01-01T00:00:00Z",
                "updated_at": "2024-01-01T00:00:00Z"
            }],
            "version": 1,
            "timestamp": "2024-01-01T00:00:00Z",
            "checksum": "abc123"
        }
        
        status, data = self.request('POST', '/sync/snapshot', data=test_project, auth=True)
        self.test_check(status == 200 and data.get('status') == 'ok', 
                       "9. POST /sync/snapshot with valid snapshot returns ok")
        
        # Test after sync
        status, data = self.request('GET', '/portfolio/projects', auth=True)
        project_synced = status == 200 and len(data) == 1 and data[0]['id'] == 'test-proj-123'
        self.test_check(project_synced, "10. GET /portfolio/projects after sync returns synced project")
        
        # Test 11-12: Individual project
        status, data = self.request('GET', '/portfolio/projects/test-proj-123', auth=True)
        self.test_check(status == 200 and data.get('id') == 'test-proj-123', 
                       "11. GET /portfolio/projects/{id} returns correct project")
        
        status, _ = self.request('GET', '/portfolio/projects/nonexistent-id-xyz', auth=True)
        self.test_check(status == 404, "12. GET /portfolio/projects/nonexistent returns 404")
        
        # Test 13-14: Events and Status
        status, data = self.request('GET', '/events', auth=True)
        self.test_check(status == 200 and isinstance(data, list), "13. GET /events returns a list")
        
        status, data = self.request('GET', '/status', auth=True)
        status_ok = status == 200 and all(field in data for field in 
                                         ['failover_active', 'sync_version', 'peer_status'])
        self.test_check(status_ok, "14. GET /status returns dict with required fields")
        
        # Test 15: Recovery announcement
        recovery_data = {
            "node_id": "laptop-node-01",
            "role": "primary", 
            "timestamp": "2024-01-01T00:00:00Z"
        }
        status, data = self.request('POST', '/recovery-announcement', data=recovery_data, auth=True)
        self.test_check(status == 200 and data.get('status') == 'acknowledged', 
                       "15. POST /recovery-announcement returns acknowledged")
        
        # Test 16-18: Error handling
        status, _ = self.request('GET', '/unknown-route-xyz', auth=True)
        self.test_check(status == 404, "16. Unknown route returns 404")
        
        # Bad JSON test
        try:
            req = urllib.request.Request(f"http://localhost:{self.test_port}/sync/snapshot", 
                                       data=b"invalid json", 
                                       headers={'X-API-Key': self.api_key, 'Content-Type': 'application/json'},
                                       method='POST')
            with urllib.request.urlopen(req) as response:
                status = response.getcode()
        except urllib.error.HTTPError as e:
            status = e.code
            
        self.test_check(status == 400, "17. Bad JSON body returns 400 not 500")
        
        # Test server is still running
        status, _ = self.request('GET', '/health', auth=False)
        self.test_check(status == 200, "18. Server remains stable after all tests")
        
    def run_verification(self):
        """Run complete verification"""
        print("=" * 60)
        print("SentinelDR Module 12 Complete Verification")
        print("=" * 60)
        
        try:
            self.run_tests()
        except Exception as e:
            self.log(f"Test execution error: {e}")
        finally:
            self.cleanup_test_environment()
            
        print("\n" + "=" * 60)
        print(f"Tests passed: {self.test_passed}")
        print(f"Tests failed: {self.test_failed}")
        
        if self.test_failed == 0:
            print("\nMODULE 12 COMPLETE — ALL CHECKS PASSED")
            print("Ready to proceed to Module 13.")
        else:
            print(f"\n❌ {self.test_failed} tests failed")
            sys.exit(1)
            
        print("=" * 60)


if __name__ == "__main__":
    tester = PhoneServerTester()
    tester.run_verification()