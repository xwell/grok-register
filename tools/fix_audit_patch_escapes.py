#!/usr/bin/env python3
"""Repair string escapes inside the temporary audit patch script before running it.

The patch script embeds Python source inside triple-quoted strings. Source snippets
that should generate literal backslash-n in grok_register_ttk.py must therefore
use double escaping in this script.
"""
from pathlib import Path

path = Path(__file__).resolve().parent / "apply_audit_fixes.py"
text = path.read_text(encoding="utf-8")

replacements = {
    'f.write("\\n")': 'f.write("\\\\n")',
    'line = f"{email}----{password or \'\'}----{sso}\\n"': 'line = f"{email}----{password or \'\'}----{sso}\\\\n"',
}

for old, new in replacements.items():
    text = text.replace(old, new)

path.write_text(text, encoding="utf-8")
print("audit patch escapes repaired")
