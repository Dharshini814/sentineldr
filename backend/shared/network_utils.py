"""
SentinelDR Network Utilities
Automatic IP detection for dynamic network environments
"""

import socket
import os
import logging
import subprocess
import json
from typing import Optional, Dict, List

logger = logging.getLogger(__name__)

def get_local_ip() -> Optional[str]:
    """Get the current local IP address by connecting to external server"""
    try:
        # Try multiple methods to get IP
        methods = [
            lambda: _get_ip_via_socket(),
            lambda: _get_ip_via_powershell(),
            lambda: _get_ip_via_ipconfig()
        ]
        
        for method in methods:
            try:
                ip = method()
                if ip and _is_valid_ip(ip):
                    return ip
            except Exception:
                continue
                
        return None
    except Exception as e:
        logger.error(f"Failed to detect IP: {e}")
        return None

def _get_ip_via_socket() -> Optional[str]:
    """Get IP by connecting to external server"""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(5)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        return local_ip
    except Exception:
        return None

def _get_ip_via_powershell() -> Optional[str]:
    """Get IP using PowerShell network commands"""
    try:
        cmd = [
            "powershell", "-Command",
            "(Get-NetRoute -DestinationPrefix '0.0.0.0/0' | Get-NetIPAddress | Where-Object {$_.AddressFamily -eq 'IPv4' -and $_.IPAddress -notlike '127.*'} | Select-Object -First 1).IPAddress"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    return None

def _get_ip_via_ipconfig() -> Optional[str]:
    """Get IP using ipconfig command (Windows)"""
    try:
        result = subprocess.run(['ipconfig'], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            lines = result.stdout.split('\n')
            for i, line in enumerate(lines):
                if 'IPv4 Address' in line and '192.168.' in line or '10.' in line:
                    # Extract IP from line like "   IPv4 Address. . . . . . . . . . . : 192.168.1.100"
                    ip = line.split(':')[-1].strip()
                    if _is_valid_ip(ip):
                        return ip
    except Exception:
        pass
    return None

def _is_valid_ip(ip: str) -> bool:
    """Check if IP address is valid and not loopback/link-local"""
    try:
        parts = ip.split('.')
        if len(parts) != 4:
            return False
        
        # Check each part is valid
        for part in parts:
            num = int(part)
            if num < 0 or num > 255:
                return False
        
        # Exclude loopback and link-local
        if ip.startswith('127.') or ip.startswith('169.254.'):
            return False
            
        return True
    except Exception:
        return False

def get_network_interfaces() -> Dict[str, str]:
    """Get all available network interfaces and their IPs"""
    interfaces = {}
    try:
        cmd = [
            "powershell", "-Command",
            "Get-NetIPAddress -AddressFamily IPv4 | Where-Object {$_.IPAddress -notlike '127.*' -and $_.IPAddress -notlike '169.254.*'} | Select-Object IPAddress,InterfaceAlias | ConvertTo-Json"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        if result.returncode == 0 and result.stdout.strip():
            data = json.loads(result.stdout)
            if isinstance(data, dict):
                data = [data]
            
            for item in data:
                if isinstance(item, dict) and 'InterfaceAlias' in item and 'IPAddress' in item:
                    interfaces[item['InterfaceAlias']] = item['IPAddress']
                    
    except Exception as e:
        logger.debug(f"Could not get network interfaces: {e}")
    
    return interfaces

def auto_detect_network_ip() -> Optional[str]:
    """Automatically detect the best network IP to use"""
    
    # First try the socket method (most reliable)
    ip = get_local_ip()
    if ip:
        logger.info(f"Auto-detected IP address: {ip}")
        return ip
    
    # Fallback to checking interfaces manually
    interfaces = get_network_interfaces()
    if interfaces:
        # Prefer non-loopback interfaces
        for name, ip in interfaces.items():
            if _is_valid_ip(ip):
                logger.info(f"Auto-detected IP address: {ip} (via interface: {name})")
                return ip
    
    logger.warning("Could not auto-detect IP address, falling back to localhost")
    return "localhost"

def get_host_for_binding(config_host: Optional[str] = None) -> str:
    """
    Get the host address to bind servers to.
    Returns the detected IP or falls back to config/localhost
    """
    
    # If config specifies a host, try to use it
    if config_host and config_host not in ['localhost', '127.0.0.1', '0.0.0.0']:
        if _is_valid_ip(config_host):
            return config_host
    
    # Auto-detect IP
    detected_ip = auto_detect_network_ip()
    
    if detected_ip and detected_ip != "localhost":
        return detected_ip
    
    # Fallback to bind all interfaces
    return "0.0.0.0"

def update_frontend_env_if_needed():
    """Update frontend .env file with current IP if it exists"""
    try:
        from pathlib import Path
        
        current_ip = get_local_ip()
        if not current_ip:
            return
        
        frontend_env = Path(__file__).parent.parent.parent / "frontend" / ".env"
        
        if frontend_env.exists():
            # Read current config
            content = frontend_env.read_text()
            
            # Check if IPs need updating
            needs_update = False
            new_content = []
            
            for line in content.split('\n'):
                if line.startswith('VITE_API_URL='):
                    new_line = f"VITE_API_URL=http://{current_ip}:8000"
                    if line != new_line:
                        needs_update = True
                    new_content.append(new_line)
                elif line.startswith('VITE_PHONE_API_URL='):
                    new_line = f"VITE_PHONE_API_URL=http://{current_ip}:8001"
                    if line != new_line:
                        needs_update = True
                    new_content.append(new_line)
                else:
                    new_content.append(line)
            
            if needs_update:
                frontend_env.write_text('\n'.join(new_content))
                logger.info(f"Updated frontend .env with IP: {current_ip}")
                
    except Exception as e:
        logger.debug(f"Could not update frontend .env: {e}")

# Auto-detect IP when module is imported
_detected_ip = auto_detect_network_ip()
logger.info(f"Network utils initialized with IP: {_detected_ip}")