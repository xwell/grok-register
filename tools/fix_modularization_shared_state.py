#!/usr/bin/env python3
from pathlib import Path

path = Path(__file__).resolve().with_name("apply_full_safe_modularization.py")
text = path.read_text(encoding="utf-8")


def replace_once(source, old, new, label):
    count = source.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, got {count}")
    return source.replace(old, new, 1)


old_import = "import_block = '''\nimport functools\nimport app_config as _app_config\n"
new_import = "import_block = '''\nimport functools\nimport types\nimport app_config as _app_config\n"
text = replace_once(text, old_import, new_import, "main import block")

old_getattr = """def __getattr__(name):
    if name in {{"browser", "page", "browser_proxy_bridge", "browser_started_with_proxy", "cf_clearance"}}:
        return getattr(_registration_browser, name)
    raise AttributeError(name)
"""
new_getattr = """def __getattr__(name):
    if name in {{"browser", "page", "browser_proxy_bridge", "browser_started_with_proxy", "cf_clearance"}}:
        return getattr(_registration_browser, name)
    if name in {{"_cf_domain_index", "_cloudmail_domain_index"}}:
        return getattr(_mail_service, name)
    raise AttributeError(name)


class _CompatibilityModule(types.ModuleType):
    def __setattr__(self, name, value):
        if name == "config":
            if value is not _app_config.config:
                if not isinstance(value, dict):
                    raise TypeError("config must be a dict")
                _app_config.config.clear()
                _app_config.config.update(value)
            value = _app_config.config
        elif name in {{"_cf_domain_index", "_cloudmail_domain_index"}}:
            setattr(_mail_service, name, int(value))
            self.__dict__.pop(name, None)
            return
        super().__setattr__(name, value)


sys.modules[__name__].__class__ = _CompatibilityModule
"""
text = replace_once(text, old_getattr, new_getattr, "compatibility getattr block")

path.write_text(text, encoding="utf-8")
print("shared state compatibility patch applied")
