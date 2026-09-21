#!/usr/bin/env python3
"""
SentinelDR API Validation Test
Tests both laptop and phone APIs to validate the integration.
"""

import json
import time
import urllib.request
import urllib.error

def test_endpoint(url, headers=None, description=""):
    """Test a single endpoint and return the response or error."""
    if headers is None:
        headers = {}
    
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode())
            print(f"✅ {description}")
            print(f"   URL: {url}")
            print(f"   Response: {json.dumps(data, indent=2)}")
            return data
    except Exception as exc:
        print(f"❌ {description}")
        print(f"   URL: {url}")
        print(f"   Error: {exc}")
        return None

def main():
    """Run comprehensive API validation tests."""
    print("SentinelDR API Validation Test")
    print("=" * 50)
    print()
    
    # Test configuration
    api_key = "my-project-final"
    laptop_base = "http://localhost:8000"
    phone_base = "http://localhost:8001"
    
    auth_headers = {"X-API-Key": api_key}
    
    # Test laptop endpoints
    print("LAPTOP API TESTS")
    print("-" * 20)
    laptop_health = test_endpoint(f"{laptop_base}/health", description="Laptop Health (public)")
    laptop_nodes = test_endpoint(f"{laptop_base}/nodes", headers=auth_headers, description="Laptop Nodes")
    laptop_events = test_endpoint(f"{laptop_base}/events?limit=5", headers=auth_headers, description="Laptop Events")
    laptop_sync_status = test_endpoint(f"{laptop_base}/sync/status", headers=auth_headers, description="Laptop Sync Status")
    
    print()
    print("PHONE API TESTS")
    print("-" * 20)
    phone_health = test_endpoint(f"{phone_base}/health", description="Phone Health (public)")
    
    print()
    print("INTEGRATION ANALYSIS")
    print("-" * 20)
    
    # Analyze results
    if laptop_health and phone_health:
        print("✅ Both nodes responding")
        
        # Check failover state consistency
        laptop_failover = laptop_health.get("failover_active", False)
        phone_failover = phone_health.get("failover_active", False)
        
        print(f"   Laptop failover_active: {laptop_failover}")
        print(f"   Phone failover_active: {phone_failover}")
        
        if laptop_failover and phone_failover:
            print("⚠️  Both nodes report failover active - this should not happen")
        elif phone_failover and not laptop_failover:
            print("✅ Phone in failover mode, laptop reports normal - EXPECTED during DR")
        elif not laptop_failover and not phone_failover:
            print("✅ Both nodes in normal operation")
        
        # Check peer connectivity
        laptop_peer_reachable = laptop_health.get("peer_reachable", False)
        phone_peer_reachable = phone_health.get("peer_reachable", False)
        
        print(f"   Laptop can reach peer: {laptop_peer_reachable}")
        print(f"   Phone can reach peer: {phone_peer_reachable}")
        
        # Check IP addresses
        laptop_ip = laptop_health.get("local_ip")
        phone_ip = phone_health.get("local_ip")
        laptop_peer_host = laptop_health.get("peer_host")
        phone_peer_host = phone_health.get("peer_host")
        
        print(f"   Laptop reports its IP as: {laptop_ip}")
        print(f"   Phone reports its IP as: {phone_ip}")
        print(f"   Laptop sees peer at: {laptop_peer_host}")
        print(f"   Phone sees peer at: {phone_peer_host}")
        
        if laptop_nodes:
            print(f"   Laptop /nodes reports {len(laptop_nodes)} nodes:")
            for node in laptop_nodes:
                print(f"     - {node.get('node_id')} ({node.get('role')}) at {node.get('host')}:{node.get('port')} [{node.get('status')}]")
    
    else:
        print("❌ One or both nodes not responding")
    
    print()
    print("Test completed.")

if __name__ == "__main__":
    main()