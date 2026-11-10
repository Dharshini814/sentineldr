"""
SentinelDR - Master QA Audit Runner
Executes all QA layers (0 through 9) 3 times to detect flakiness.
Compiles pass/fail/not-run status, bug inventory, and flakiness statistics.
"""

import os
import sys
import time

BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from tests.qa.test_layer0_preflight import run_layer0_preflight
from tests.qa.test_layer1_static import run_layer1_static
from tests.qa.test_layer2_api import run_layer2_tests
from tests.qa.test_layer3_database import run_layer3_database
from tests.qa.test_layer4_replication import run_layer4_replication
from tests.qa.test_layer5_ownership import run_layer5_ownership
from tests.qa.test_layer6_lifecycle import run_layer6_lifecycle
from tests.qa.test_layer7_portfolio_dashboard import run_layer7_portfolio_dashboard
from tests.qa.test_layer8_edge_routing import run_layer8_edge_routing
from tests.qa.test_layer9_nonfunctional import run_layer9_nonfunctional

LAYERS = [
    ("Layer 0: Preflight", run_layer0_preflight),
    ("Layer 1: Static Code", run_layer1_static),
    ("Layer 2: API Endpoints", run_layer2_tests),
    ("Layer 3: Database", run_layer3_database),
    ("Layer 4: Replication", run_layer4_replication),
    ("Layer 5: Ownership & Leases", run_layer5_ownership),
    ("Layer 6: Lifecycle & Failover", run_layer6_lifecycle),
    ("Layer 7: Portfolio & Dashboard", run_layer7_portfolio_dashboard),
    ("Layer 8: Edge Routing", run_layer8_edge_routing),
    ("Layer 9: Non-Functional & Load", run_layer9_nonfunctional),
]

def run_suite_once(run_number: int):
    print(f"\n==================== STARTING QA SUITE RUN {run_number}/3 ====================")
    run_results = {}
    for layer_name, layer_func in LAYERS:
        try:
            results = layer_func()
            for item in results:
                test_id = item[0]
                real_sim = item[1]
                status = item[2]
                details = item[3]
                run_results[test_id] = (layer_name, real_sim, status, details)
        except Exception as e:
            print(f"ERROR executing {layer_name}: {e}")
    return run_results

def main():
    all_runs = []
    for r in range(1, 4):
        run_res = run_suite_once(r)
        all_runs.append(run_res)
        time.sleep(1.0)

    print("\n==================== QA 3-RUN CONVERGENCE & FLAKINESS REPORT ====================")
    # Collect all test IDs
    all_test_ids = list(all_runs[0].keys())
    flaky_count = 0
    passed_count = 0
    failed_count = 0
    not_run_count = 0

    results_table = []
    flaky_table = []

    for tid in all_test_ids:
        layer_name, real_sim, s1, d1 = all_runs[0][tid]
        _, _, s2, _ = all_runs[1].get(tid, (None, None, "UNKNOWN", None))
        _, _, s3, _ = all_runs[2].get(tid, (None, None, "UNKNOWN", None))

        is_flaky = (s1 != s2 or s2 != s3)
        if is_flaky:
            flaky_count += 1
            flaky_table.append((tid, layer_name, s1, s2, s3))
        else:
            if s1 == "PASS":
                passed_count += 1
            elif s1 == "FAIL":
                failed_count += 1
            elif s1 == "NOT RUN":
                not_run_count += 1

        results_table.append((tid, layer_name, real_sim, s1, s2, s3, "YES" if is_flaky else "NO", d1))

    print(f"Total Unique Tests Audited: {len(all_test_ids)}")
    print(f"Consistent Passes (3/3):   {passed_count}")
    print(f"Consistent Failures (3/3): {failed_count}")
    print(f"Consistent Not Run:        {not_run_count}")
    print(f"Flaky Tests (Inconsistent):{flaky_count}")

    if flaky_count > 0:
        print("\nFLAKY TESTS DETECTED:")
        for ft in flaky_table:
            print(f"  {ft[0]} ({ft[1]}): Run 1={ft[2]}, Run 2={ft[3]}, Run 3={ft[4]}")
    else:
        print("\nFLAKINESS VERDICT: 0 flaky tests detected across 3 full suite runs (100% deterministic).")

if __name__ == "__main__":
    main()
