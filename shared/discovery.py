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
    """Runs in background on Phone; broadcasts UDP beacons AND actively registers with Laptop/Dashboard."""

    def __init__(self, port: int = 8001, cluster_id: str = "sentineldr-cluster-01"):
        self.port = port
        self.cluster_id = cluster_id
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._reg_thread: Optional[threading.Thread] = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._broadcast_loop, daemon=True)
        self._thread.start()
        self._reg_thread = threading.Thread(target=self._active_registration_loop, daemon=True)
        self._reg_thread.start()

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

    def _active_registration_loop(self):
        """Actively finds Laptop (port 8000) or Dashboard (port 8080) on local Wi-Fi subnet and sends registration ping."""
        import urllib.request
        time.sleep(1.0)
        while self._running:
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    s.connect(("8.8.8.8", 80))
                    my_ip = s.getsockname()[0]
                except Exception:
                    my_ip = "127.0.0.1"
                finally:
                    s.close()

                if my_ip and not my_ip.startswith("127."):
                    prefix = ".".join(my_ip.split(".")[:3]) + "."
                    for target_port in (8080, 8000):
                        for i in range(1, 255):
                            target_ip = f"{prefix}{i}"
                            if target_ip == my_ip:
                                continue
                            try:
                                test_s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                                test_s.settimeout(0.08)
                                test_s.connect((target_ip, target_port))
                                test_s.close()

                                reg_url = f"http://{target_ip}:{target_port}/api/v1/peer/register"
                                req = urllib.request.Request(
                                    reg_url,
                                    data=json.dumps({"node_id": "phone", "port": self.port}).encode("utf-8"),
                                    headers={"Content-Type": "application/json"}
                                )
                                urllib.request.urlopen(req, timeout=1.0)
                            except Exception:
                                pass
            except Exception:
                pass
            time.sleep(6.0)


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

    @phone_url.setter
    def phone_url(self, val: str):
        with self._lock:
            try:
                from urllib.parse import urlparse
                p = urlparse(val)
                if p.hostname:
                    self.discovered_phone_ip = p.hostname
                if p.port:
                    self.discovered_phone_port = p.port
            except Exception:
                pass

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
        """Active fast subnet prober in case Wi-Fi router blocks UDP broadcast packets."""
        time.sleep(1.0)
        while self._running:
            if not self.discovered_phone_ip or self.discovered_phone_ip == "127.0.0.1":
                try:
                    found_ip = self._fast_sweep_subnet()
                    if found_ip:
                        self._notify(found_ip, self.discovered_phone_port)
                except Exception:
                    pass
            time.sleep(4.0)

    def _fast_sweep_subnet(self) -> Optional[str]:
        """Concurrently sweeps local /24 subnet for open port 8001."""
        local_ip = self._get_local_ip()
        if not local_ip or local_ip.startswith("127."):
            return None
        parts = local_ip.split(".")
        if len(parts) != 4:
            return None
        prefix = f"{parts[0]}.{parts[1]}.{parts[2]}."

        import concurrent.futures

        def probe(ip_str):
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.3)
            try:
                s.connect((ip_str, self.discovered_phone_port))
                s.close()
                return ip_str
            except Exception:
                return None

        candidates = [f"{prefix}{i}" for i in range(1, 255) if f"{prefix}{i}" != local_ip]
        ex = concurrent.futures.ThreadPoolExecutor(max_workers=30)
        try:
            futures = [ex.submit(probe, c) for c in candidates]
            for f in concurrent.futures.as_completed(futures, timeout=1.5):
                res = f.result()
                if res:
                    ex.shutdown(wait=False, cancel_futures=True)
                    return res
        except Exception:
            pass
        finally:
            ex.shutdown(wait=False, cancel_futures=True)
        return None

    def _get_local_ip(self) -> str:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
        except Exception:
            return "127.0.0.1"
        finally:
            s.close()
