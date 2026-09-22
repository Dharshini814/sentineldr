#!/usr/bin/env python3
"""
SentinelDR Automatic Network Setup
Detects current WiFi network IP and updates all configuration files automatically
"""

import socket
import subprocess
import json
import os
import re
import datetime
from pathlib import Path

def get_local_ip():
    """Get the current local IP address"""
    try:
        # Connect to a remote server to determine local IP
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return None

def get_network_interfaces():
    """Get all network interfaces and their IPs"""
    interfaces = {}
    try:
        # Use PowerShell to get network adapter information
        cmd = [
            "powershell", "-Command",
            "Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*'} | Select-Object IPAddress,InterfaceAlias | ConvertTo-Json"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, shell=True)
        
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if isinstance(data, dict):
                data = [data]  # Single result case
            
            for item in data:
                interfaces[item['InterfaceAlias']] = item['IPAddress']
                
    except Exception as e:
        print(f"Error getting network interfaces: {e}")
    
    return interfaces

def detect_phone_network():
    """Detect if we're connected to a phone hotspot"""
    interfaces = get_network_interfaces()
    phone_keywords = ['mobile', 'hotspot', 'phone', 'cellular', 'wifi']
    
    # Check for common phone hotspot patterns
    for interface_name, ip in interfaces.items():
        interface_lower = interface_name.lower()
        if any(keyword in interface_lower for keyword in phone_keywords):
            return ip, interface_name
    
    # If no phone-specific interface found, return the primary IP
    primary_ip = get_local_ip()
    if primary_ip:
        for interface_name, ip in interfaces.items():
            if ip == primary_ip:
                return ip, interface_name
    
    return primary_ip, "Primary Network"

def update_env_file(file_path, updates):
    """Update environment file with new values"""
    if not os.path.exists(file_path):
        print(f"Warning: {file_path} not found, creating new file")
        Path(file_path).touch()
    
    # Read existing content
    content = {}
    if os.path.exists(file_path):
        with open(file_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    content[key.strip()] = value.strip()
    
    # Apply updates
    content.update(updates)
    
    # Write back
    with open(file_path, 'w') as f:
        f.write("# SentinelDR Auto-Generated Network Configuration\n")
        f.write(f"# Generated at: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
        for key, value in content.items():
            f.write(f"{key}={value}\n")

def update_frontend_env(local_ip):
    """Update frontend .env file with detected IP"""
    frontend_env = Path("frontend/.env")
    
    updates = {
        "VITE_API_URL": f"http://{local_ip}:8000",
        "VITE_PHONE_API_URL": f"http://{local_ip}:8001", 
        "VITE_API_KEY": "my-project-final"
    }
    
    update_env_file(frontend_env, updates)
    print(f"✅ Updated frontend/.env with IP: {local_ip}")

def update_laptop_env(local_ip):
    """Update laptop server .env file"""
    laptop_env = Path("backend/.env.laptop")
    
    updates = {
        "API_KEY": "my-project-final",
        "NODE_ID": "laptop-node-01",
        "NODE_ROLE": "primary",
        "NODE_PORT": "8000",
        "PEER_PORT": "8001",
        "HOST_IP": local_ip,
        "DATABASE_URL": "sqlite:///./sentineldr_laptop.db",
        "DISCOVERY_PORT": "47777",
        "DISCOVERY_INTERVAL": "5",
        "HEARTBEAT_INTERVAL": "3",
        "HEARTBEAT_TIMEOUT": "3",
        "MISSED_HEARTBEAT_THRESHOLD": "1",
        "SYNC_INTERVAL": "3",
        "FAILOVER_COOLDOWN": "15",
        "LOG_LEVEL": "INFO"
    }
    
    update_env_file(laptop_env, updates)
    print(f"✅ Updated backend/.env.laptop with IP: {local_ip}")

def update_phone_env(local_ip):
    """Update phone server .env file"""
    phone_env = Path("backend/phone/.env.phone")
    
    updates = {
        "API_KEY": "my-project-final",
        "NODE_ID": "phone-node-02", 
        "NODE_ROLE": "secondary",
        "NODE_PORT": "8001",
        "PEER_PORT": "8000",
        "HOST_IP": local_ip,
        "DB_PATH": "./sentineldr_phone.db",
        "DISCOVERY_PORT": "47777",
        "DISCOVERY_INTERVAL": "5",
        "HEARTBEAT_INTERVAL": "3",
        "HEARTBEAT_TIMEOUT": "3",
        "MISSED_HEARTBEAT_THRESHOLD": "1",
        "SYNC_INTERVAL": "3", 
        "FAILOVER_COOLDOWN": "15",
        "LOG_LEVEL": "INFO"
    }
    
    update_env_file(phone_env, updates)
    print(f"✅ Updated backend/phone/.env.phone with IP: {local_ip}")

def main():
    print("🔍 SentinelDR Auto Network Setup")
    print("=" * 50)
    
    # Detect current network
    detected_ip, interface = detect_phone_network()
    
    if not detected_ip:
        print("❌ Could not detect network IP address")
        return False
    
    print(f"📡 Detected Network Interface: {interface}")
    print(f"🌐 Detected IP Address: {detected_ip}")
    
    # Show all available interfaces for reference
    interfaces = get_network_interfaces()
    if interfaces:
        print("\n📋 All Network Interfaces:")
        for name, ip in interfaces.items():
            marker = "👈 SELECTED" if ip == detected_ip else ""
            print(f"   {name}: {ip} {marker}")
    
    print(f"\n🔧 Updating configuration files with IP: {detected_ip}")
    
    try:
        # Update all configuration files
        update_frontend_env(detected_ip)
        update_laptop_env(detected_ip)
        update_phone_env(detected_ip)
        
        print(f"\n✅ Network configuration updated successfully!")
        print(f"📱 Frontend will connect to: {detected_ip}:8000 and {detected_ip}:8001")
        print(f"💻 Laptop server will bind to: {detected_ip}:8000")
        print(f"📞 Phone server will bind to: {detected_ip}:8001")
        
        print(f"\n🚀 Next steps:")
        print(f"1. Restart frontend: cd frontend && npm run dev")
        print(f"2. Restart laptop server: cd backend && uvicorn laptop.main:app --host {detected_ip} --port 8000 --reload")
        print(f"3. Restart phone server: cd backend && PYTHONPATH=. python phone/phone_server.py")
        
        return True
        
    except Exception as e:
        print(f"❌ Error updating configuration: {e}")
        return False

if __name__ == "__main__":
    success = main()
    if not success:
        exit(1)