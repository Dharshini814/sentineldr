#!/usr/bin/env python3
"""
Test script to manually check and trigger phone server failover
"""
import requests
import json
import time

PHONE_SERVER = "http://10.187.68.57:8001"
API_KEY = "my-project-final"

def test_phone_server():
    print("📱 Testing Phone Server Failover Detection")
    print("=" * 50)
    
    # Test health endpoint
    print("\n🔍 Phone Server Health:")
    try:
        response = requests.get(f"{PHONE_SERVER}/health", timeout=5)
        if response.status_code == 200:
            health = response.json()
            print(f"   Status: {health.get('status', 'unknown')}")
            print(f"   Failover Active: {health.get('failover_active', False)}")
            print(f"   Peer Status: {health.get('peer_status', 'unknown')}")
            print(f"   Missed Heartbeats: {health.get('missed_heartbeats', 0)}")
            print(f"   Node ID: {health.get('node_id', 'unknown')}")
        else:
            print(f"   ❌ HTTP {response.status_code}")
    except Exception as e:
        print(f"   ❌ Connection failed: {e}")
        return False
    
    # Test portfolio access
    print("\n📂 Portfolio Access Test:")
    try:
        response = requests.get(f"{PHONE_SERVER}/", timeout=5)
        print(f"   HTTP Status: {response.status_code}")
        
        if response.status_code == 200:
            print("   ✅ Portfolio served successfully")
        elif response.status_code == 302:
            redirect = response.headers.get('Location', 'unknown')
            print(f"   🔄 Redirected to: {redirect}")
        elif response.status_code == 503:
            print(f"   ❌ Service unavailable: {response.text}")
        else:
            print(f"   ❌ Unexpected response")
    except Exception as e:
        print(f"   ❌ Connection failed: {e}")
    
    # Test if we can reach primary server from here
    print("\n💻 Primary Server Connectivity Test:")
    PRIMARY_SERVER = "http://localhost:8000"  # Test from where this script runs
    try:
        response = requests.get(f"{PRIMARY_SERVER}/health", timeout=3)
        if response.status_code == 200:
            print("   ✅ Primary server reachable from this machine")
        else:
            print(f"   ❌ Primary server HTTP {response.status_code}")
    except Exception as e:
        print(f"   ❌ Primary server unreachable: {e}")
    
    print("\n" + "=" * 50)
    return True

if __name__ == "__main__":
    test_phone_server()