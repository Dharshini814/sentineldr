"""
Tests for SentinelDR Safe .env Setup Helper (scripts/setup_env.py)
Verifies:
1. Email and app password validation formats (spaces stripped, exact 16 chars).
2. Preserves existing unrelated keys and comments in .env.
3. Overwrite protection prompts/guards.
4. Permissions set to 0o600 where supported (POSIX/Linux/Termux).
5. Ensures secrets/passwords NEVER leak or appear in stdout/stderr.
"""

import io
import os
import pathlib
import stat
import sys
import pytest

from scripts.setup_env import (
    ALERT_KEYS,
    resolve_target_path,
    validate_app_password,
    validate_email,
    write_env_file,
)


def test_validate_email():
    """Verify email format validation requires '@' and non-empty string."""
    assert validate_email("admin@example.invalid") is True
    assert validate_email("user.test@gmail.com") is True
    assert validate_email("invalid-address") is False
    assert validate_email("") is False
    assert validate_email("   ") is False


def test_validate_app_password():
    """Verify Gmail App Password validation requires 16 characters and strips spaces."""
    # 16 contiguous chars
    valid, clean = validate_app_password("abcdefghijklmnop")
    assert valid is True
    assert clean == "abcdefghijklmnop"

    # 16 chars with spaces (standard Google 4x4 grouping)
    valid, clean = validate_app_password("abcd efgh ijkl mnop")
    assert valid is True
    assert clean == "abcdefghijklmnop"

    # Too short
    valid, clean = validate_app_password("abcdefgh")
    assert valid is False
    assert clean == ""

    # Too long
    valid, clean = validate_app_password("abcdefghijklmnopq")
    assert valid is False
    assert clean == ""

    # Empty
    valid, clean = validate_app_password("")
    assert valid is False
    assert clean == ""


def test_resolve_target_path(tmp_path):
    """Verify correct path resolution for laptop root and phone subdirectory."""
    laptop_env = resolve_target_path(tmp_path, "laptop")
    assert laptop_env == tmp_path / ".env"

    phone_env = resolve_target_path(tmp_path, "phone")
    assert phone_env == tmp_path / "phone" / ".env"


def test_write_env_creates_file_and_sets_keys(tmp_path, capsys):
    """Verify new .env creation with fake alert values."""
    target_env = tmp_path / "test.env"
    fake_password = "test-app-pass-01"
    new_values = {
        "SDR_ALERT_CHANNEL": "email",
        "SDR_SMTP_HOST": "smtp.gmail.com",
        "SDR_SMTP_PORT": "465",
        "SDR_SMTP_USER": "sender@example.invalid",
        "SDR_SMTP_APP_PASSWORD": fake_password,
        "SDR_ADMIN_ALERT_EMAIL": "admin@example.invalid",
    }

    summary = write_env_file(target_env, new_values)

    assert target_env.exists()
    for k in ALERT_KEYS:
        assert summary[k] == "CREATED"

    content = target_env.read_text(encoding="utf-8")
    assert "SDR_ALERT_CHANNEL=email" in content
    assert "SDR_SMTP_HOST=smtp.gmail.com" in content
    assert "SDR_SMTP_PORT=465" in content
    assert "SDR_SMTP_USER=sender@example.invalid" in content
    assert f"SDR_SMTP_APP_PASSWORD={fake_password}" in content
    assert "SDR_ADMIN_ALERT_EMAIL=admin@example.invalid" in content

    # Verify stdout / stderr from capsys never contains password
    captured = capsys.readouterr()
    assert fake_password not in captured.out
    assert fake_password not in captured.err

    # Check file permissions on POSIX / Linux / Termux
    if os.name != "nt":
        file_mode = stat.S_IMODE(target_env.stat().st_mode)
        assert file_mode == 0o600


def test_write_env_preserves_existing_keys_and_respects_overwrite(tmp_path):
    """Verify existing keys are preserved and overwrite confirmation is enforced."""
    target_env = tmp_path / "existing.env"
    initial_content = (
        "# Existing Cluster Secrets\n"
        "SDR_CLUSTER_ID=cluster-fake-99\n"
        "SDR_HMAC_SECRET=existing_secret_token_1234\n"
        "SDR_SMTP_USER=old_user@example.invalid\n"
    )
    target_env.write_text(initial_content, encoding="utf-8")

    fake_password = "test-new-pass-02"
    new_values = {
        "SDR_ALERT_CHANNEL": "email",
        "SDR_SMTP_HOST": "smtp.gmail.com",
        "SDR_SMTP_PORT": "465",
        "SDR_SMTP_USER": "new_user@example.invalid",
        "SDR_SMTP_APP_PASSWORD": fake_password,
        "SDR_ADMIN_ALERT_EMAIL": "admin@example.invalid",
    }

    # Case 1: Deny overwrite of SDR_SMTP_USER
    summary_denied = write_env_file(
        target_env,
        new_values,
        confirm_fn=lambda k, old: False,  # Deny all overwrites
    )

    assert summary_denied["SDR_SMTP_USER"] == "KEPT_EXISTING"
    assert summary_denied["SDR_ALERT_CHANNEL"] == "CREATED"
    content_after_deny = target_env.read_text(encoding="utf-8")
    # Existing keys must still be present
    assert "SDR_CLUSTER_ID=cluster-fake-99" in content_after_deny
    assert "SDR_HMAC_SECRET=existing_secret_token_1234" in content_after_deny
    assert "SDR_SMTP_USER=old_user@example.invalid" in content_after_deny

    # Case 2: Allow overwrite
    summary_allowed = write_env_file(
        target_env,
        new_values,
        confirm_fn=lambda k, old: True,  # Allow overwrites
    )
    assert summary_allowed["SDR_SMTP_USER"] == "UPDATED"
    content_after_allow = target_env.read_text(encoding="utf-8")
    assert "SDR_SMTP_USER=new_user@example.invalid" in content_after_allow
    assert "SDR_CLUSTER_ID=cluster-fake-99" in content_after_allow
