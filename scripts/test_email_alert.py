#!/usr/bin/env python3
"""
SentinelDR - Email Alert Verification Script
Sends a test alert email to verify that Gmail SMTP credentials and network access
are working correctly.
"""

import os
import pathlib
import sys

# Ensure repository root is on sys.path
BASE_DIR = pathlib.Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

# Load .env if present
env_file = BASE_DIR / ".env"
if not env_file.exists():
    phone_env = BASE_DIR / "phone" / ".env"
    if phone_env.exists():
        env_file = phone_env

if env_file.exists():
    with open(env_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip()
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                if k not in os.environ:
                    os.environ[k] = v

from shared.alerts import EmailAlertDispatcher, SEVERITY_INFO


def main():
    print("==================================================")
    print(" SentinelDR - Live Email Alert Dispatcher Test")
    print("==================================================")

    dispatcher = EmailAlertDispatcher()

    if not dispatcher.is_configured():
        print("\n[ERROR] Email alerts are not configured.")
        print("Missing required environment variables in .env:")
        if not os.getenv("SDR_SMTP_USER"):
            print("  - SDR_SMTP_USER (Sender Gmail address)")
        if not os.getenv("SDR_SMTP_APP_PASSWORD"):
            print("  - SDR_SMTP_APP_PASSWORD (16-character Google App Password)")
        if not os.getenv("SDR_ADMIN_ALERT_EMAIL"):
            print("  - SDR_ADMIN_ALERT_EMAIL (Recipient alert address)")
        print("\nPlease run the setup helper first:")
        print("  python scripts/setup_env.py")
        sys.exit(1)

    print(f"\nConfiguration detected:")
    print(f"  - SMTP Server: {dispatcher.smtp_host}:{dispatcher.smtp_port}")
    print(f"  - Sender:      {dispatcher.smtp_user}")
    print(f"  - Recipient:   {dispatcher.admin_email}")
    print(f"  - Password:    **************** [CONFIGURED]")

    print("\nSending live test notification via Google SMTP...")
    subject = "Live Alert System Verification"
    body = (
        "Congratulations! Your SentinelDR email alerting system is operational.\n\n"
        "SentinelDR will automatically dispatch critical incident alerts to this\n"
        "address whenever primary server heartbeats are lost, failovers occur,\n"
        "or split-brain SAFE_MODE is engaged."
    )

    ok, err = dispatcher.send_alert_sync(
        subject=subject,
        body=body,
        severity=SEVERITY_INFO,
        node_id="manual-test"
    )

    if ok:
        print("\n[SUCCESS] Test email dispatched successfully!")
        print(f"An email from '{dispatcher.smtp_user}' was delivered to '{dispatcher.admin_email}'.")
        print("Please check your email inbox (and Spam/Junk folder if not immediately visible).")
    else:
        print(f"\n[FAILED] SMTP Delivery Error: {err}")
        print("\nTroubleshooting tips:")
        print("1. Verify your 16-character Google App Password (ensure no spaces and correct letters).")
        print("2. Ensure 2-Step Verification is active on the sender Google Account.")
        print("3. Check internet connectivity and firewall access to smtp.gmail.com on port 465.")
        sys.exit(1)


if __name__ == "__main__":
    main()
