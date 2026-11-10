#!/usr/bin/env python3
"""
SentinelDR - Safe Environment Setup Helper
Standard library only: getpass, pathlib, os, sys.

Configures alert and SMTP notification credentials in .env without echoing
passwords or committing secrets to version control.
"""

import getpass
import os
import pathlib
import sys
from typing import Callable, Dict, Optional, Tuple

# Reusable Alert Configuration Keys
ALERT_KEYS = [
    "SDR_ALERT_CHANNEL",
    "SDR_SMTP_HOST",
    "SDR_SMTP_PORT",
    "SDR_SMTP_USER",
    "SDR_SMTP_APP_PASSWORD",
    "SDR_ADMIN_ALERT_EMAIL",
]


def validate_email(email_str: str) -> bool:
    """Validate that an email address string is non-empty and contains '@'."""
    if not email_str:
        return False
    trimmed = email_str.strip()
    return "@" in trimmed and len(trimmed) >= 3


def validate_app_password(raw_password: str) -> Tuple[bool, str]:
    """
    Validate Gmail App Password.
    Removes spaces and verifies exact length of 16 characters.
    Never prints, echoes, or logs the password.
    """
    if not raw_password:
        return False, ""
    cleaned = "".join(raw_password.split())
    if len(cleaned) == 16:
        return True, cleaned
    return False, ""


def write_env_file(
    target_path: pathlib.Path,
    new_values: Dict[str, str],
    confirm_fn: Optional[Callable[[str, str], bool]] = None,
) -> Dict[str, str]:
    """
    Writes or updates keys in target_path (.env).
    - Preserves all existing keys, comments, and structure.
    - Prompts before overwriting any existing non-empty value.
    - Sets permissions to 0o600 on Linux/Termux.
    - Never prints password values to stdout or stderr.

    Returns a dict summary of actions taken: {key: "UPDATED" | "CREATED" | "KEPT_EXISTING"}
    """
    existing_lines = []
    existing_keys: Dict[str, Tuple[str, int]] = {}  # key -> (current_value, line_index)

    if target_path.exists():
        with open(target_path, "r", encoding="utf-8") as f:
            existing_lines = f.readlines()

        for idx, line in enumerate(existing_lines):
            stripped = line.strip()
            if stripped and not stripped.startswith("#") and "=" in stripped:
                parts = stripped.split("=", 1)
                k = parts[0].strip()
                v = parts[1].strip()
                if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                    v = v[1:-1]
                existing_keys[k] = (v, idx)

    status_summary: Dict[str, str] = {}
    updated_lines = list(existing_lines)

    for key, new_val in new_values.items():
        if key in existing_keys:
            old_val, line_idx = existing_keys[key]
            if old_val and old_val != new_val:
                # Ask confirmation before overwriting
                allow = True
                if confirm_fn is not None:
                    allow = confirm_fn(key, old_val)
                elif sys.stdin.isatty():
                    ans = input(
                        f"Key '{key}' already exists in {target_path.name}. Overwrite? [y/N]: "
                    ).strip().lower()
                    allow = ans in ("y", "yes")
                else:
                    allow = False

                if not allow:
                    status_summary[key] = "KEPT_EXISTING"
                    continue

            # Update existing line
            updated_lines[line_idx] = f"{key}={new_val}\n"
            status_summary[key] = "UPDATED"
        else:
            # Append new key
            if updated_lines and not updated_lines[-1].endswith("\n"):
                updated_lines[-1] = updated_lines[-1] + "\n"
            updated_lines.append(f"{key}={new_val}\n")
            status_summary[key] = "CREATED"

    # Write file securely
    target_path.parent.mkdir(parents=True, exist_ok=True)
    with open(target_path, "w", encoding="utf-8") as f:
        f.writelines(updated_lines)

    # Restrict permissions on Linux / Termux / POSIX
    if os.name != "nt":
        try:
            os.chmod(target_path, 0o600)
        except OSError:
            pass

    return status_summary


def resolve_target_path(repo_root: pathlib.Path, node_choice: str) -> pathlib.Path:
    """Resolve target .env path based on node selection."""
    choice = node_choice.strip().lower()
    if choice == "phone":
        return repo_root / "phone" / ".env"
    return repo_root / ".env"


def main():
    """Interactive command-line setup entry point."""
    print("==================================================")
    print(" SentinelDR - Secure .env & Email Alert Setup")
    print("==================================================")

    repo_root = pathlib.Path(__file__).resolve().parent.parent

    # 1. Node selection
    while True:
        node_input = input("Which node is this? [laptop / phone] (default: laptop): ").strip().lower()
        if not node_input:
            node_input = "laptop"
        if node_input in ("laptop", "phone"):
            break
        print("Invalid selection. Please enter 'laptop' or 'phone'.")

    target_env = resolve_target_path(repo_root, node_input)
    print(f"Target file: {target_env}")

    # 2. Sender Gmail Address
    while True:
        sender_email = input("Enter sender Gmail address (e.g., yourname@gmail.com): ").strip()
        if validate_email(sender_email):
            break
        print("Invalid email format. Address must contain '@'. Please try again.")

    # 3. Gmail App Password (hidden input via getpass)
    while True:
        print("\nNote: Use a 16-character Google App Password (not your personal Gmail password).")
        print("Spaces will be stripped automatically. The input will NOT be echoed.")
        raw_pw = getpass.getpass("Enter 16-character Gmail App Password (hidden): ")
        valid_pw, clean_pw = validate_app_password(raw_pw)
        if valid_pw:
            break
        print("Invalid App Password. Must be exactly 16 characters (excluding spaces). Please try again.")

    # 4. Admin Alert Email Address
    while True:
        admin_email = input("Enter recipient admin alert email: ").strip()
        if validate_email(admin_email):
            break
        print("Invalid email format. Address must contain '@'. Please try again.")

    # Build payload
    env_payload = {
        "SDR_ALERT_CHANNEL": "email",
        "SDR_SMTP_HOST": "smtp.gmail.com",
        "SDR_SMTP_PORT": "465",
        "SDR_SMTP_USER": sender_email,
        "SDR_SMTP_APP_PASSWORD": clean_pw,
        "SDR_ADMIN_ALERT_EMAIL": admin_email,
    }

    # Write configuration
    summary = write_env_file(target_env, env_payload)

    print("\n--------------------------------------------------")
    print(f"[SUCCESS] Environment configured successfully in: {target_env}")
    for k, status in summary.items():
        if k == "SDR_SMTP_APP_PASSWORD":
            print(f"  - {k}: {status} (value: **************** [HIDDEN])")
        else:
            print(f"  - {k}: {status}")

    if os.name != "nt":
        print("[SECURITY] File permissions set to 600 (read/write by owner only).")
    print("--------------------------------------------------")
    print("Done. Do NOT commit the .env file to version control.")


if __name__ == "__main__":
    main()
