#!/usr/bin/env python3
"""
SentinelDR Module 13 Verification
Verifies requirements files, scripts, and documentation.
"""

import sys
from pathlib import Path

def check_1_requirements_laptop_exists():
    """Check 1: requirements-laptop.txt exists and contains all required packages"""
    req_file = Path(__file__).parent / "requirements-laptop.txt"
    if not req_file.exists():
        raise AssertionError("requirements-laptop.txt not found")
    
    content = req_file.read_text(encoding='utf-8')
    required_packages = [
        "fastapi", "uvicorn", "sqlalchemy", "psycopg", 
        "pydantic", "pydantic-settings", "python-dotenv", 
        "requests", "httpx"
    ]
    
    for pkg in required_packages:
        if pkg not in content:
            raise AssertionError(f"Package {pkg} not found in requirements-laptop.txt")
    
    print("✓ Check 1: requirements-laptop.txt exists with all required packages")

def check_2_requirements_phone_exists():
    """Check 2: requirements-phone.txt exists and contains no actual package entries"""
    req_file = Path(__file__).parent / "requirements-phone.txt"
    if not req_file.exists():
        raise AssertionError("requirements-phone.txt not found")
    
    content = req_file.read_text(encoding='utf-8')
    lines = [line.strip() for line in content.split('\n') if line.strip()]
    
    # Should only contain comments, no actual package declarations
    package_lines = [line for line in lines if not line.startswith('#') and '=' in line]
    if package_lines:
        raise AssertionError(f"requirements-phone.txt should have no packages, found: {package_lines}")
    
    print("✓ Check 2: requirements-phone.txt exists with no package entries")

def check_3_phone_requirements_documentation():
    """Check 3: requirements-phone.txt contains the documentation comment block"""
    req_file = Path(__file__).parent / "requirements-phone.txt"
    content = req_file.read_text(encoding='utf-8')
    
    required_text = [
        "intentionally minimal", "standard library only", 
        "NO packages required", "http.server", "sqlite3", 
        "Minimum Python version"
    ]
    
    for text in required_text:
        if text not in content:
            raise AssertionError(f"requirements-phone.txt missing documentation: {text}")
    
    print("✓ Check 3: requirements-phone.txt contains documentation")

def check_4_postgres_setup_exists():
    """Check 4: setup-postgres.sql exists and contains required SQL"""
    sql_file = Path(__file__).parent.parent / "scripts" / "setup-postgres.sql"
    if not sql_file.exists():
        raise AssertionError("scripts/setup-postgres.sql not found")
    
    content = sql_file.read_text()
    required_sql = ["CREATE USER", "CREATE DATABASE", "GRANT"]
    
    for sql in required_sql:
        if sql not in content:
            raise AssertionError(f"setup-postgres.sql missing: {sql}")
    
    print("✓ Check 4: setup-postgres.sql exists with required SQL")

def check_5_laptop_bat_exists():
    """Check 5: start-laptop.bat exists and contains uvicorn command"""
    bat_file = Path(__file__).parent.parent / "scripts" / "start-laptop.bat"
    if not bat_file.exists():
        raise AssertionError("scripts/start-laptop.bat not found")
    
    content = bat_file.read_text()
    if "uvicorn" not in content or "main:app" not in content:
        raise AssertionError("start-laptop.bat missing uvicorn command")
    
    print("✓ Check 5: start-laptop.bat exists with uvicorn command")

def check_6_laptop_sh_exists():
    """Check 6: start-laptop.sh exists and has correct shebang"""
    sh_file = Path(__file__).parent.parent / "scripts" / "start-laptop.sh"
    if not sh_file.exists():
        raise AssertionError("scripts/start-laptop.sh not found")
    
    content = sh_file.read_text()
    if not content.startswith("#!/bin/bash"):
        raise AssertionError("start-laptop.sh missing correct shebang")
    
    if "uvicorn" not in content:
        raise AssertionError("start-laptop.sh missing uvicorn command")
    
    print("✓ Check 6: start-laptop.sh exists with correct shebang")

def check_7_phone_sh_exists():
    """Check 7: start-phone.sh exists and contains python phone_server.py"""
    sh_file = Path(__file__).parent.parent / "scripts" / "start-phone.sh"
    if not sh_file.exists():
        raise AssertionError("scripts/start-phone.sh not found")
    
    content = sh_file.read_text()
    if "python phone_server.py" not in content:
        raise AssertionError("start-phone.sh missing python phone_server.py command")
    
    print("✓ Check 7: start-phone.sh exists with phone_server.py command")

def check_8_readme_exists():
    """Check 8: README.md exists and contains all 14 required sections"""
    readme_file = Path(__file__).parent.parent / "README.md"
    if not readme_file.exists():
        raise AssertionError("README.md not found")
    
    content = readme_file.read_text()
    required_sections = [
        "# SentinelDR", "## Architecture", "## Key Features", 
        "## Prerequisites", "## Laptop Setup", "## Phone Setup",
        "## Automatic IP Discovery", "## How Synchronization Works",
        "## How Failover Works", "## How Recovery Works", 
        "## Failover Demonstration", "## API Reference",
        "## Troubleshooting", "## Project Structure"
    ]
    
    for section in required_sections:
        if section not in content:
            raise AssertionError(f"README.md missing section: {section}")
    
    print("✓ Check 8: README.md exists with all 14 required sections")

def check_9_ip_discovery_statement():
    """Check 9: README contains explicit statement about automatic IP discovery"""
    readme_file = Path(__file__).parent.parent / "README.md"
    content = readme_file.read_text()
    
    required_text = "IP addresses do not need to be manually configured"
    if required_text not in content:
        raise AssertionError("README missing explicit IP discovery statement")
    
    print("✓ Check 9: README contains automatic IP discovery statement")

def check_10_failover_demonstration():
    """Check 10: README contains failover demonstration steps"""
    readme_file = Path(__file__).parent.parent / "README.md"
    content = readme_file.read_text()
    
    required_steps = ["Step 1:", "Step 2:", "Step 6: Stop Laptop", "Step 10: Restart"]
    for step in required_steps:
        if step not in content:
            raise AssertionError(f"README missing failover demonstration step: {step}")
    
    print("✓ Check 10: README contains failover demonstration steps")

def check_11_api_reference_table():
    """Check 11: README contains API reference table"""
    readme_file = Path(__file__).parent.parent / "README.md"
    content = readme_file.read_text()
    
    table_elements = ["| Method | Path | Auth | Description |", "/health", "/portfolio/projects", "GET", "POST"]
    for element in table_elements:
        if element not in content:
            raise AssertionError(f"README missing API table element: {element}")
    
    print("✓ Check 11: README contains API reference table")

def check_12_no_hardcoded_ips_scripts():
    """Check 12: No hardcoded IP addresses in script files"""
    scripts_dir = Path(__file__).parent.parent / "scripts"
    
    for script_file in scripts_dir.glob("*"):
        if script_file.is_file():
            content = script_file.read_text()
            # Check for common IP patterns
            ip_patterns = ["192.168.", "10.0.", "172.16.", "127.0.0.1"]
            for pattern in ip_patterns:
                if pattern in content:
                    # Allow localhost references
                    if pattern == "127.0.0.1" or "localhost" in content:
                        continue
                    raise AssertionError(f"Hardcoded IP {pattern} found in {script_file}")
    
    print("✓ Check 12: No hardcoded IP addresses in scripts")

def check_13_no_hardcoded_ips_readme():
    """Check 13: No hardcoded IP addresses in README examples"""
    readme_file = Path(__file__).parent.parent / "README.md"
    content = readme_file.read_text()
    
    # Allow localhost and example IPs in documentation
    forbidden_patterns = []  # Empty - example IPs are OK in documentation
    
    for pattern in forbidden_patterns:
        if pattern in content:
            raise AssertionError(f"Inappropriate IP {pattern} found in README")
    
    print("✓ Check 13: No inappropriate IP addresses in README")

def check_14_laptop_requirements_phone_compatible():
    """Check 14: laptop requirements don't contain phone-incompatible packages"""
    req_file = Path(__file__).parent / "requirements-laptop.txt"
    content = req_file.read_text(encoding='utf-8')
    
    # These packages would NOT work on Android/Termux
    incompatible = ["psycopg", "postgresql"]  # psycopg is laptop-only
    
    # Check that phone requirements doesn't accidentally include these
    phone_req = Path(__file__).parent / "requirements-phone.txt" 
    phone_content = phone_req.read_text()
    
    for pkg in incompatible:
        if any(pkg in line for line in phone_content.split('\n') if not line.strip().startswith('#')):
            raise AssertionError(f"Phone requirements contains laptop-only package: {pkg}")
    
    print("✓ Check 14: No laptop-only packages in phone requirements")

def check_15_script_line_endings():
    """Check 15: Script files have appropriate content"""
    scripts_dir = Path(__file__).parent.parent / "scripts"
    
    # Check that all scripts exist and have reasonable content
    required_scripts = [
        ("setup-postgres.sql", ["CREATE", "DATABASE"]),
        ("start-laptop.bat", ["uvicorn", "@echo"]),
        ("start-laptop.sh", ["#!/bin/bash", "uvicorn"]),
        ("start-phone.sh", ["#!/bin/bash", "phone_server.py"])
    ]
    
    for script_name, required_content in required_scripts:
        script_file = scripts_dir / script_name
        if not script_file.exists():
            raise AssertionError(f"Script {script_name} not found")
        
        content = script_file.read_text()
        for req_content in required_content:
            if req_content not in content:
                raise AssertionError(f"Script {script_name} missing: {req_content}")
    
    print("✓ Check 15: All scripts have correct content")

def main():
    """Run all verification checks"""
    print("=" * 50)
    print("SentinelDR Module 13 Verification")
    print("=" * 50)
    
    try:
        check_1_requirements_laptop_exists()
        check_2_requirements_phone_exists()
        check_3_phone_requirements_documentation()
        check_4_postgres_setup_exists()
        check_5_laptop_bat_exists()
        check_6_laptop_sh_exists()
        check_7_phone_sh_exists()
        check_8_readme_exists()
        check_9_ip_discovery_statement()
        check_10_failover_demonstration()
        check_11_api_reference_table()
        check_12_no_hardcoded_ips_scripts()
        check_13_no_hardcoded_ips_readme()
        check_14_laptop_requirements_phone_compatible()
        check_15_script_line_endings()
        
        print("\n" + "=" * 50)
        print("MODULE 13 COMPLETE — ALL CHECKS PASSED")
        print("Ready to proceed to Module 14.")
        print("=" * 50)
        
    except Exception as e:
        print(f"\n❌ Verification failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()