"""
Test: Phone & Shared Dependency Audit
Enforces non-negotiable rule:
Phone node and shared modules MUST use Python standard library only.
Strictly zero FastAPI, Pydantic, psycopg, PostgreSQL, or other third-party dependencies.
"""

import ast
import os
import pytest

FORBIDDEN_PACKAGES = {
    "fastapi",
    "pydantic",
    "psycopg",
    "psycopg2",
    "asyncpg",
    "sqlalchemy",
    "requests",
    "aiohttp",
    "flask",
    "django",
    "tortoise",
    "databases",
}


def scan_file_imports(filepath: str):
    with open(filepath, "r", encoding="utf-8") as f:
        tree = ast.parse(f.read(), filename=filepath)

    violations = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root_pkg = alias.name.split(".")[0].lower()
                if root_pkg in FORBIDDEN_PACKAGES:
                    violations.append((node.lineno, alias.name))
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                root_pkg = node.module.split(".")[0].lower()
                if root_pkg in FORBIDDEN_PACKAGES:
                    violations.append((node.lineno, node.module))
    return violations


def test_shared_no_forbidden_imports():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    shared_dir = os.path.join(root_dir, "shared")
    assert os.path.isdir(shared_dir), "shared/ directory must exist"

    all_violations = []
    for fname in os.listdir(shared_dir):
        if fname.endswith(".py"):
            fpath = os.path.join(shared_dir, fname)
            v = scan_file_imports(fpath)
            for lineno, mod in v:
                all_violations.append(f"shared/{fname}:{lineno} imports forbidden '{mod}'")

    assert not all_violations, f"Forbidden imports detected in shared/:\n" + "\n".join(all_violations)


def test_phone_no_forbidden_imports():
    root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    phone_dir = os.path.join(root_dir, "phone")
    assert os.path.isdir(phone_dir), "phone/ directory must exist"

    all_violations = []
    for fname in os.listdir(phone_dir):
        if fname.endswith(".py"):
            fpath = os.path.join(phone_dir, fname)
            v = scan_file_imports(fpath)
            for lineno, mod in v:
                all_violations.append(f"phone/{fname}:{lineno} imports forbidden '{mod}'")

    assert not all_violations, f"Forbidden imports detected in phone/:\n" + "\n".join(all_violations)
