"""
SentinelDR - Unified Cluster & Node Runner
Usage:
    python run.py                   # Runs all nodes (Witness :8002, Phone :8001, Laptop :8000, Dashboard :8080)
    python run.py --node laptop     # Runs Laptop node only (:8000)
    python run.py --node phone      # Runs Phone node only (:8001)
    python run.py --node witness    # Runs Witness Quorum only (:8002)
    python run.py --node dashboard  # Runs Standalone Dashboard only (:8080)
"""

import argparse
import os
import signal
import subprocess
import sys
import time

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from laptop.db import LaptopDatabase
from phone.db import PhoneDatabase
from shared.config import NodeConfig


def init_and_seed():
    """Ensure database schemas and portfolio seeds are initialized."""
    print("[SentinelDR] Initializing database schemas and seeds...", flush=True)
    laptop_cfg = NodeConfig("laptop")
    laptop_db = LaptopDatabase(laptop_cfg.database_url, dev_fallback_sqlite=laptop_cfg.dev_db_fallback)
    laptop_db.init_db()
    laptop_db.seed_portfolio_data()

    phone_cfg = NodeConfig("phone")
    phone_db = PhoneDatabase(phone_cfg.database_path)
    phone_db.seed_portfolio_data()
    print("[SentinelDR] Databases initialized and verified.", flush=True)


def run_node(node_name: str):
    """Run a specific single node."""
    if node_name == "witness":
        from shared.witness import main as witness_main
        witness_main()
    elif node_name == "laptop":
        from laptop.server import main as laptop_main
        laptop_main()
    elif node_name == "phone":
        from phone.server import main as phone_main
        phone_main()
    elif node_name == "dashboard":
        from frontend.dashboard_server import run_dashboard_server
        run_dashboard_server(port=8080)
    else:
        print(f"[ERROR] Unknown node: {node_name}. Choose from: laptop, phone, witness, dashboard.", flush=True)
        sys.exit(1)


def run_cluster():
    """Run full cluster in parallel: Witness, Phone, Laptop, and Standalone Dashboard."""
    init_and_seed()

    env = os.environ.copy()
    env["PYTHONPATH"] = BASE_DIR
    env["PYTHONUNBUFFERED"] = "1"
    env["SDR_DEV_FALLBACK_SQLITE"] = "1"

    processes = []

    def terminate_all(*_):
        print("\n[SentinelDR] Stopping all cluster processes...", flush=True)
        for name, proc in processes:
            try:
                proc.terminate()
            except Exception:
                pass
        for name, proc in processes:
            try:
                proc.wait(timeout=2)
            except Exception:
                proc.kill()
        print("[SentinelDR] All processes stopped.", flush=True)
        sys.exit(0)

    signal.signal(signal.SIGINT, terminate_all)
    signal.signal(signal.SIGTERM, terminate_all)

    print("\n============================================================", flush=True)
    print("           Starting SentinelDR Resilient Cluster            ", flush=True)
    print("============================================================", flush=True)

    # 1. Start Witness on Port 8002
    print("[1/4] Starting Witness Quorum on http://127.0.0.1:8002...", flush=True)
    wit_proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "shared.witness", "--port", "8002"],
        env=env
    )
    processes.append(("witness", wit_proc))
    time.sleep(1.0)

    # 2. Start Phone on Port 8001
    print("[2/4] Starting Phone Node (Standby) on http://127.0.0.1:8001...", flush=True)
    phone_proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "phone.server"],
        env=env
    )
    processes.append(("phone", phone_proc))
    time.sleep(1.0)

    # 3. Start Laptop on Port 8000
    print("[3/4] Starting Laptop Node (Primary) on http://127.0.0.1:8000...", flush=True)
    laptop_proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "laptop.server"],
        env=env
    )
    processes.append(("laptop", laptop_proc))
    time.sleep(1.5)

    # 4. Start Standalone Frontend Dashboard on Port 8080
    print("[4/4] Starting Standalone Dashboard on http://127.0.0.1:8080...", flush=True)
    dash_proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "frontend.dashboard_server"],
        env=env
    )
    processes.append(("dashboard", dash_proc))
    time.sleep(0.5)

    print("\n============================================================", flush=True)
    print(" [READY] SentinelDR Full Cluster is running!", flush=True)
    print("------------------------------------------------------------", flush=True)
    print("  * DEDICATED DASHBOARD: http://localhost:8080/", flush=True)
    print("    (Independent: Stays alive even if Laptop or Phone is stopped!)", flush=True)
    print("  * Laptop Portfolio:    http://localhost:8000/", flush=True)
    print("  * Phone Standby DR:    http://localhost:8001/", flush=True)
    print("  * Witness Quorum:      http://localhost:8002/health", flush=True)
    print("============================================================", flush=True)
    print("Press Ctrl+C to safely shut down all nodes.\n", flush=True)

    try:
        while True:
            time.sleep(1)
            for name, proc in processes:
                code = proc.poll()
                if code is not None:
                    print(f"[SentinelDR Alert] {name} process exited with code {code}.", flush=True)
                    terminate_all()
    except KeyboardInterrupt:
        terminate_all()


def main():
    parser = argparse.ArgumentParser(description="SentinelDR Cluster Runner")
    parser.add_argument(
        "--node",
        choices=["laptop", "phone", "witness", "dashboard", "all"],
        default="all",
        help="Specify which node to run (default: all)"
    )
    args = parser.parse_args()

    if args.node == "all":
        run_cluster()
    else:
        init_and_seed()
        run_node(args.node)


if __name__ == "__main__":
    main()
