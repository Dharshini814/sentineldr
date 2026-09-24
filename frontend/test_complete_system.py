#!/usr/bin/env python3
"""
Complete SentinelDR System Test
Tests all components and connections
"""

import requests
import json
import time
from datetime import datetime

def test_endpoint(url, name, headers=None):
    """Test a single endpoint"""
    try:
        response = requests.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            try:
                data = response.json()
                return {"success": True, "status": 200, "data": data}
            except:
                return {"success": True, "status": 200, "data": "Non-JSON response"}
        else:
            return {"success": False, "status": response.status_code, "error": f"HTTP {response.status_code}"}
    except Exception as e:
        return {"success": False, "status": 0, "error": str(e)}

def main():
    print("🚀 SentinelDR Complete System Test")
    print("=" * 50)
    print(f"Test Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print()
    
    # Configuration
    API_KEY = 'my-project-final'
    headers = {'X-API-Key': API_KEY}
    
    # Test endpoints
    tests = [
        # Health endpoints (no auth needed)
        ('http://localhost:8000/health', 'Laptop Health', None),
        ('http://localhost:8001/health', 'Phone Health', None),
        
        # Authenticated endpoints
        ('http://localhost:8000/nodes', 'Nodes API', headers),
        ('http://localhost:8000/events?limit=5', 'Events API', headers),
        ('http://localhost:8000/sync/status', 'Sync Status API', headers),
        
        # Dashboard server
        ('http://localhost:5174/sentineldr_live.html', 'Live Dashboard', None),
    ]
    
    results = []
    for url, name, auth_headers in tests:
        print(f"Testing {name}...", end=" ")
        result = test_endpoint(url, name, auth_headers)
        results.append((name, result))
        
        if result["success"]:
            print(f"✅ OK ({result['status']})")
        else:
            print(f"❌ FAIL ({result.get('status', 'N/A')}: {result.get('error', 'Unknown')})")
    
    print("\n" + "=" * 50)
    print("SUMMARY")
    print("=" * 50)
    
    success_count = sum(1 for _, result in results if result["success"])
    total_count = len(results)
    
    print(f"✅ Passed: {success_count}/{total_count}")
    print(f"❌ Failed: {total_count - success_count}/{total_count}")
    
    if success_count == total_count:
        print("\n🎉 ALL SYSTEMS OPERATIONAL!")
        print("🌐 Dashboard: http://localhost:5174")
        print("💻 Laptop API: http://localhost:8000/health")
        print("📱 Phone API: http://localhost:8001/health")
    else:
        print("\n⚠️  Some components failed. Check the details above.")
    
    # Show sample data if APIs are working
    laptop_health = next((r for n, r in results if n == "Laptop Health"), None)
    phone_health = next((r for n, r in results if n == "Phone Health"), None)
    nodes_api = next((r for n, r in results if n == "Nodes API"), None)
    
    if laptop_health and laptop_health["success"] and phone_health and phone_health["success"]:
        print("\n📊 SYSTEM STATUS")
        print("=" * 50)
        try:
            laptop_data = laptop_health["data"]
            phone_data = phone_health["data"]
            
            print(f"Laptop Node: {laptop_data.get('node_id', 'Unknown')} - {laptop_data.get('status', 'Unknown').upper()}")
            print(f"Phone Node:  {phone_data.get('node_id', 'Unknown')} - {phone_data.get('status', 'Unknown').upper()}")
            print(f"Peer Connection: {'✅ Connected' if laptop_data.get('peer_reachable') else '❌ Not Connected'}")
            print(f"Failover Status: {'🔄 Active' if laptop_data.get('failover_active') else '✅ Normal'}")
            
            if nodes_api and nodes_api["success"]:
                nodes_data = nodes_api["data"]
                print(f"Total Nodes: {len(nodes_data)}")
        except Exception as e:
            print(f"Could not parse status data: {e}")

if __name__ == "__main__":
    main()