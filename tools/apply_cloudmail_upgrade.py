#!/usr/bin/env python3
"""Finalize the temporary Cloud Mail upgrade.

The Cloud Mail provider patch has already been applied to main. This script is
kept intentionally small and idempotent so the temporary GitHub Actions workflow
can re-run safely and then remove itself plus this file.
"""
from pathlib import Path
import ast
import json
import re

ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "grok_register_ttk.py"
CONFIG_PATH = ROOT / "config.example.json"
README_PATH = ROOT / "README.md"

app = APP_PATH.read_text(encoding="utf-8-sig")

# Repair the only known bad generated form from the interrupted bot attempt.
# It turns valid source into:
#     combined = "
#     ".join(parts)
# before ast.parse(). Keep this here so the workflow is safe even if it is run
# on a half-applied workspace.
app = app.replace('combined = "\n".join(parts)', 'combined = "\\n".join(parts)')

required_app_markers = [
    '"cloudmail_api_base": ""',
    '"cloudmail_public_token": ""',
    '"cloudmail_domains": ""',
    '"cloudmail_path_messages": "/api/public/emailList"',
    '_cloudmail_domain_index = 0',
    'def cloudmail_get_email_and_token():',
    'def cloudmail_get_messages(address):',
    'def cloudmail_get_oai_code(',
    'if provider == "cloudmail":\n        return cloudmail_get_email_and_token()',
    'if provider == "cloudmail":\n        return cloudmail_get_oai_code(',
    '["duckmail", "yyds", "cloudflare", "cloudmail"]',
    'self.cloudmail_api_base_var',
    'self.cloudmail_public_token_var',
    'self.cloudmail_domains_var',
    'Cloud Mail 模式缺少配置',
]
missing = [marker for marker in required_app_markers if marker not in app]
if missing:
    raise RuntimeError("Cloud Mail upgrade is not fully applied; missing markers: " + ", ".join(missing))

ast.parse(app)
APP_PATH.write_text(app, encoding="utf-8-sig")

config_text = CONFIG_PATH.read_text(encoding="utf-8")
config = json.loads(config_text)
for key in (
    "cloudmail_api_base",
    "cloudmail_public_token",
    "cloudmail_domains",
    "cloudmail_path_messages",
):
    if key not in config:
        raise RuntimeError(f"config.example.json missing {key}")

readme = README_PATH.read_text(encoding="utf-8")
required_readme_markers = [
    "Cloud Mail 无人收件模式（可选）",
    "cloudmail_api_base",
    "cloudmail_public_token",
    "cloudmail_domains",
    "POST /api/public/emailList",
]
missing_readme = [marker for marker in required_readme_markers if marker not in readme]
if missing_readme:
    raise RuntimeError("README Cloud Mail docs are incomplete: " + ", ".join(missing_readme))

print("Cloud Mail upgrade is already applied and syntactically valid.")
