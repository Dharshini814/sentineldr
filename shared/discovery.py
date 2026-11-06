"""
SentinelDR - Zero-Conf Automatic Peer Discovery
Standard library only: socket, json, threading.
Enables the Laptop and Dashboard to automatically discover the Phone's Wi-Fi IP
without any manual IP address typing or configuration.
"""

import json
import socket
import threading
import time
import subprocess
import os
from typing import Optional

DISCOVERY_UDP_PORT = 8003
BEACON_MAGIC = "sentineldr-beacon"


class PhoneBeaconBroadcaster:
    """Runs in background on Phone; broadcasts UDP discovery beacons to Wi-Fi subnet."""

    def __init__(self, port: int = 8001, cluster_id: str = "sentineldr-cluster-01"):
        self.port = port
        self.cluster_id = cluster_id
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _broadcast_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        except Exception:
            pass

        payload = json.dumps({
            "magic": BEACON_MAGIC,
            "node_type": "phone",
            "port": self.port,
            "cluster_id": self.cluster_id
        }).encode("utf-8")

        while self._running:
            try:
                # Broadcast to global broadcast and local subnet
                sock.sendto(payload, ("<broadcast>", DISCOVERY_UDP_PORT))
                sock.sendto(payload, ("255.255.255.255", DISCOVERY_UDP_PORT))
            except Exception:
                pass
            time.sleep(2.0)

        sock.close()


class PeerDiscoveryListener:
    """Runs in background on Laptop & Dashboard; discovers Phone IP automatically."""

    def __init__(self, expected_cluster_id: str = "sentineldr-cluster-01"):
        self.expected_cluster_id = expected_cluster_id
        self.discovered_phone_ip: Optional[str] = None
        self.discovered_phone_port: int = 8001
        self._running = False
        self._lock = threading.RLock()
        self._callbacks = []

    def add_on_discovered_callback(self, cb):
        with self._lock:
            self._callbacks.append(cb)

    @property
    def phone_url(self) -> str:
        with self._lock:
            if self.discovered_phone_ip:
                return f"http://{self.discovered_phone_ip}:{self.discovered_phone_port}"
            return "http://127.0.0.1:8001"

    def start(self):
        self._running = True
        t_udp = threading.Thread(target=self._udp_listener_loop, daemon=True)
        t_udp.start()
        t_scan = threading.Thread(target=self._arp_subnet_scan_loop, daemon=True)
        t_scan.start()

    def stop(self):
        self._running = False

    def _notify(self, ip: str, port: int):
        with self._lock:
            changed = (self.discovered_phone_ip != ip)
            self.discovered_phone_ip = ip
            self.discovered_phone_port = port
            if changed:
                print(f"[Auto-Discovery] Found SentinelDR Phone at http://{ip}:{port}!", flush=True)
                for cb in self._callbacks:
                    try:
                        cb(f"http://{ip}:{port}")
                    except Exception:
                        pass

    def _udp_listener_loop(self):
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass
        try:
            sock.bind(("", DISCOVERY_UDP_PORT))
        except Exception as e:
            sock.close()
            return

        sock.settimeout(2.0)
        while self._running:
            try:
                data, addr = sock.recvfrom(2048)
                msg = json.loads(data.decode("utf-8"))
                if msg.get("magic") == BEACON_MAGIC and msg.get("node_type") == "phone":
                    phone_ip = addr[0]
                    phone_port = msg.get("port", 8001)
                    self._notify(phone_ip, phone_port)
            except (socket.timeout, Exception):
                pass

        sock.close()

    def _arp_subnet_scan_loop(self):
        """Fallback subnet prober in case Wi-Fi router blocks UDP broadcast packets."""
        time.sleep(3.0)
        while self._running:
            if not self.discovered_phone_ip or self.discovered_phone_ip == "127.0.0.1":
                try:
                    candidates = self._get_lan_ip_candidates()
                    for ip in candidates:
                        if self._probe_phone_ip(ip, self.discovered_phone_port):
                            self._notify(ip, self.discovered_phone_port)
                            break
                except Exception:
                    pass
            time.sleep(10.0)

    def _probe_phone_ip(self, ip: str, port: int) -> bool:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.3)
        try:
            s.connect((ip, port))
            s.close()
            return True
        except Exception:
            return False

    def _get_lan_ip_candidates(self) -> list:
        """Parse local ARP table to find alive IP addresses on Wi-Fi subnet."""
        ips = []
        try:
            out = subprocess.check_output("arp -a", shell=True, text=True, timeout=2)
            for line in out.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2:
                    ip = parts[0]
                    if ip.startswith("192.168.") or ip.startswith("10.") or ip.startswith("172."):
                        if not ip.endswith(".255") and not ip.endswith(".1"):
                            ips.append(ip)
        except Exception:
            pass
        return ips
