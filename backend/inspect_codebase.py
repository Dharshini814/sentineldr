#!/usr/bin/env python3
"""
SentinelDR Codebase Inspection
Comprehensive scan for import violations, missing files, and standard library compliance.
"""

import ast
import sys
from pathlib import Path
from typing import List, Tuple, Set

# Standard library modules allowed in phone and shared code
ALLOWED_STDLIB_MODULES = {
    'os', 'sys', 'json', 'time', 'datetime', 'pathlib', 'socket',
    'threading', 'logging', 'hashlib', 'uuid', 'sqlite3',
    'urllib', 'http', 'io', 're', 'math', 'random', 'secrets',
    'collections', 'functools', 'itertools', 'contextlib',
    'traceback', 'inspect', 'ast', 'copy', 'struct', 'base64',
    'tempfile', 'dataclasses', 'typing', 'enum', 'abc'
}

class CodebaseInspector:
    def __init__(self):
        self.backend_root = Path(__file__).parent
        self.violations = []
        self.files_scanned = 0
    
    def scan_all(self):
        """Run all inspection checks"""
        print("INSPECTION RESULTS")
        print("==================")
        
        # Scan all Python files in backend
        for py_file in self.backend_root.rglob("*.py"):
            if "__pycache__" in str(py_file):
                continue
            
            self.files_scanned += 1
            self._check_file(py_file)
        
        # Check configuration files
        self._check_config_files()
        
        # Print results
        print(f"Files scanned: {self.files_scanned}")
        print(f"Violations found: {len(self.violations)}")
        print()
        
        if self.violations:
            for violation in self.violations:
                print(violation)
            print()
            print("INSPECTION FAILED — Fix all violations before running integration tests")
            return False
        else:
            print("INSPECTION PASSED — No violations found")
            return True
    
    def _check_file(self, file_path: Path):
        """Check a single Python file for violations"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Parse AST
            tree = ast.parse(content, str(file_path))
            
            # Check imports
            self._check_imports(file_path, tree)
            
        except Exception as e:
            self._add_violation("ERROR", file_path, f"Failed to parse: {e}")
    
    def _check_imports(self, file_path: Path, tree: ast.AST):
        """Check all imports in a file"""
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self._validate_import(file_path, alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    self._validate_import(file_path, node.module)
    
    def _validate_import(self, file_path: Path, module_name: str):
        """Validate a single import statement"""
        relative_path = file_path.relative_to(self.backend_root)
        
        # Get the top-level module name
        top_module = module_name.split('.')[0]
        
        # Check phone purity
        if self._is_phone_file(relative_path):
            if top_module not in ALLOWED_STDLIB_MODULES:
                # Allow internal phone imports
                if not (module_name.startswith('phone.') or module_name == 'phone'):
                    # Allow shared imports
                    if not (module_name.startswith('shared.') or module_name == 'shared'):
                        self._add_violation("CRITICAL", relative_path, 
                                          f"imports '{module_name}' — NOT allowed on phone")
        
        # Check shared purity
        elif self._is_shared_file(relative_path):
            if top_module not in ALLOWED_STDLIB_MODULES:
                # Only allow other shared imports
                if not (module_name.startswith('shared.') or module_name == 'shared'):
                    self._add_violation("CRITICAL", relative_path, 
                                      f"imports '{module_name}' — shared must use stdlib only")
        
        # Check laptop doesn't import phone
        elif self._is_laptop_file(relative_path):
            if module_name.startswith('phone.') or module_name == 'phone':
                self._add_violation("CRITICAL", relative_path, 
                                  f"laptop imports phone module '{module_name}' — NOT allowed")
        
        # Check cross-module contamination
        self._check_module_isolation(relative_path, module_name)
    
    def _is_phone_file(self, path: Path) -> bool:
        """Check if file is in phone directory"""
        return 'phone' in path.parts
    
    def _is_laptop_file(self, path: Path) -> bool:
        """Check if file is in laptop directory"""
        return 'laptop' in path.parts
    
    def _is_shared_file(self, path: Path) -> bool:
        """Check if file is in shared directory"""
        return 'shared' in path.parts
    
    def _check_module_isolation(self, file_path: Path, module_name: str):
        """Ensure modules don't cross-contaminate"""
        if self._is_phone_file(file_path):
            if module_name.startswith('laptop.'):
                self._add_violation("CRITICAL", file_path, 
                                  f"phone imports laptop module '{module_name}'")
        
        if self._is_shared_file(file_path):
            if module_name.startswith(('laptop.', 'phone.')):
                self._add_violation("CRITICAL", file_path, 
                                  f"shared imports platform module '{module_name}'")
    
    def _check_config_files(self):
        """Check configuration files exist and are correct"""
        # Check .env examples exist
        laptop_env = self.backend_root / "laptop" / ".env.laptop.example"
        phone_env = self.backend_root / "phone" / ".env.phone.example"
        
        if not laptop_env.exists():
            self._add_violation("WARNING", Path("laptop"), ".env.laptop.example missing")
        else:
            self._check_no_hardcoded_ips(laptop_env)
        
        if not phone_env.exists():
            self._add_violation("WARNING", Path("phone"), ".env.phone.example missing")
        else:
            self._check_no_hardcoded_ips(phone_env)
    
    def _check_no_hardcoded_ips(self, file_path: Path):
        """Check file doesn't contain hardcoded IP addresses"""
        try:
            content = file_path.read_text(encoding='utf-8')
            
            # Look for IP patterns (but allow localhost)
            import re
            ip_pattern = r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b'
            matches = re.findall(ip_pattern, content)
            
            for match in matches:
                if match not in ['127.0.0.1', '0.0.0.0']:
                    self._add_violation("WARNING", file_path, 
                                      f"contains hardcoded IP: {match}")
        
        except Exception as e:
            self._add_violation("ERROR", file_path, f"Failed to check IPs: {e}")
    
    def _add_violation(self, severity: str, file_path: Path, message: str):
        """Add a violation to the list"""
        self.violations.append(f"[{severity}] {file_path} {message}")

def main():
    """Run codebase inspection"""
    inspector = CodebaseInspector()
    success = inspector.scan_all()
    
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()