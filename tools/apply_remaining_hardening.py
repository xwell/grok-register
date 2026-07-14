#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "grok_register_ttk.py"
FLOW = ROOT / "registration_flow.py"
OAUTH = ROOT / "cpa_xai" / "oauth_device.py"
BROWSER = ROOT / "cpa_xai" / "browser_confirm.py"
EXPORT = ROOT / "cpa_export.py"
MINT = ROOT / "cpa_xai" / "mint.py"


def read(path):
    return path.read_text(encoding="utf-8-sig")


def write(path, text):
    path.write_text(text, encoding="utf-8")


def replace_once(text, old, new, label):
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, got {count}")
    return text.replace(old, new, 1)


def replace_between(text, start, end, new, label):
    i = text.find(start)
    if i < 0:
        raise RuntimeError(f"{label}: start not found")
    j = text.find(end, i + len(start))
    if j < 0:
        raise RuntimeError(f"{label}: end not found")
    return text[:i] + new + text[j:]


flow = r'''"""Shared registration workflow used by both GUI and CLI adapters."""
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Optional, Tuple


@dataclass
class RegistrationCallbacks:
    log: Callable[[str], None]
    cancelled: Callable[[], bool]


@dataclass
class RegistrationOperations:
    start_browser: Callable[[], None]
    restart_browser: Callable[[], None]
    browser_missing: Callable[[], bool]
    open_signup_page: Callable[[], None]
    fill_email_and_submit: Callable[[], Tuple[str, str]]
    save_mail_credential: Callable[[str, str], bool]
    fill_code_and_submit: Callable[[str, str], str]
    fill_profile_and_submit: Callable[[], Dict[str, Any]]
    wait_for_sso_cookie: Callable[[], str]
    enable_nsfw: Callable[[str], Tuple[bool, str]]
    persist_account_line: Callable[[str, str, str], None]
    queue_unsaved_result: Callable[[Dict[str, Any], str], bool]
    add_tokens: Callable[[str, str], Dict[str, Dict[str, Any]]]
    export_cpa: Callable[[str, str, str], Dict[str, Any]]
    cleanup: Callable[[str], None]
    sleep: Callable[[float], None]
    cancelled_exception: type
    retry_exception: type


@dataclass
class RegistrationResult:
    ok: bool
    email: str = ""
    password: str = ""
    sso: str = ""
    profile: Dict[str, Any] = field(default_factory=dict)
    error: str = ""
    retryable: bool = False


@dataclass
class OutputResult:
    registered: bool
    saved: bool
    pending_saved: bool = False
    save_error: str = ""
    pools: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    cpa: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchResult:
    success_count: int = 0
    fail_count: int = 0
    processed_count: int = 0
    cancelled: bool = False
    results: list = field(default_factory=list)


def register_one_account(callbacks, ops, enable_nsfw=True, max_mail_retry=3):
    email = ""
    dev_token = ""
    code = ""
    mail_ok = False
    for mail_try in range(1, max_mail_retry + 1):
        if callbacks.cancelled():
            raise ops.cancelled_exception()
        callbacks.log(f"[*] 1. 打开注册页 (尝试 {mail_try}/{max_mail_retry})")
        ops.open_signup_page()
        callbacks.log("[*] 2. 创建邮箱并提交")
        email, dev_token = ops.fill_email_and_submit()
        callbacks.log(f"[*] 邮箱: {email}")
        callbacks.log(f"[Debug] 邮箱credential(jwt): {dev_token}")
        if not ops.save_mail_credential(email, dev_token):
            callbacks.log("[!] 邮箱凭据保存失败，注册继续，但已明确记录该异常")
        callbacks.log("[*] 3. 拉取验证码")
        try:
            code = ops.fill_code_and_submit(email, dev_token)
            mail_ok = True
            break
        except Exception as exc:
            message = str(exc)
            if ("未收到验证码" in message or "验证码" in message) and mail_try < max_mail_retry:
                callbacks.log(f"[!] 本邮箱未取到验证码，自动更换新邮箱重试: {message}")
                ops.restart_browser()
                ops.sleep(1)
                continue
            raise
    if not mail_ok:
        raise RuntimeError("验证码阶段失败，已达到最大重试次数")
    callbacks.log(f"[*] 验证码: {code}")
    callbacks.log("[*] 4. 填写资料")
    profile = ops.fill_profile_and_submit()
    callbacks.log(f"[*] 资料已填: {profile.get('given_name')} {profile.get('family_name')}")
    callbacks.log("[*] 5. 等待 sso cookie")
    sso = ops.wait_for_sso_cookie()
    if enable_nsfw:
        callbacks.log("[*] 6. 开启 NSFW")
        nsfw_ok, nsfw_msg = ops.enable_nsfw(sso)
        if nsfw_ok:
            callbacks.log(f"[+] NSFW 开启成功: {nsfw_msg}")
        else:
            callbacks.log(f"[!] NSFW 未开启，继续保存账号: {nsfw_msg}")
    return RegistrationResult(
        ok=True,
        email=email,
        password=str(profile.get("password") or ""),
        sso=sso,
        profile=profile,
    )


def persist_account_result(result, callbacks, ops):
    try:
        ops.persist_account_line(result.email, result.password, result.sso)
        saved = True
        save_error = ""
        pending_saved = False
    except Exception as exc:
        saved = False
        save_error = str(exc)
        pending_saved = ops.queue_unsaved_result(
            {
                "email": result.email,
                "password": result.password,
                "sso": result.sso,
                "profile": result.profile,
            },
            save_error,
        )
        callbacks.log(f"[!] 账号已注册但主结果文件保存失败: {save_error}")
        if pending_saved:
            callbacks.log("[!] 未保存账号已写入 pending 队列，等待人工重试")
        else:
            callbacks.log("[!] pending 队列也写入失败，请立即复制当前账号信息")
    pools = ops.add_tokens(result.sso, result.email)
    for name, state in pools.items():
        if state.get("enabled") and not state.get("ok"):
            callbacks.log(f"[!] grok2api {name} 入池失败: {state.get('error')}")
    cpa = ops.export_cpa(result.email, result.password, result.sso)
    return OutputResult(
        registered=True,
        saved=saved,
        pending_saved=pending_saved,
        save_error=save_error,
        pools=pools,
        cpa=cpa,
    )


def run_batch(count, callbacks, observer, ops, enable_nsfw=True, cleanup_interval=5,
              max_slot_retry=3, max_mail_retry=3):
    result = BatchResult()
    retry_count_for_slot = 0
    ops.start_browser()
    callbacks.log("[*] 浏览器已启动")
    try:
        while result.processed_count < count:
            if callbacks.cancelled():
                result.cancelled = True
                break
            callbacks.log(f"--- 开始第 {result.processed_count + 1}/{count} 个账号 ---")
            account = None
            output = None
            try:
                account = register_one_account(
                    callbacks, ops, enable_nsfw=enable_nsfw,
                    max_mail_retry=max_mail_retry,
                )
                output = persist_account_result(account, callbacks, ops)
                result.results.append({"registration": account, "output": output})
                retry_count_for_slot = 0
                result.processed_count += 1
                if output.saved:
                    result.success_count += 1
                    callbacks.log(f"[+] 注册并保存成功: {account.email}")
                else:
                    result.fail_count += 1
                    callbacks.log(f"[-] 注册成功但持久化未完成: {account.email}")
                if result.success_count > 0 and result.success_count % cleanup_interval == 0 and result.processed_count < count:
                    ops.cleanup(f"已成功 {result.success_count} 个账号，执行定期清理")
            except ops.cancelled_exception:
                result.cancelled = True
                callbacks.log("[!] 注册被停止")
                break
            except ops.retry_exception as exc:
                retry_count_for_slot += 1
                if retry_count_for_slot <= max_slot_retry:
                    callbacks.log(f"[!] 当前账号流程卡住，重试第 {retry_count_for_slot}/{max_slot_retry} 次: {exc}")
                else:
                    result.fail_count += 1
                    result.processed_count += 1
                    retry_count_for_slot = 0
                    callbacks.log(f"[-] 当前账号已达到最大重试次数，跳过: {exc}")
            except Exception as exc:
                result.fail_count += 1
                result.processed_count += 1
                retry_count_for_slot = 0
                callbacks.log(f"[-] 注册失败: {exc}")
            finally:
                observer(result, account, output)
                if callbacks.cancelled():
                    result.cancelled = True
                    break
                if ops.browser_missing():
                    ops.start_browser()
                else:
                    ops.restart_browser()
                ops.sleep(1)
    finally:
        ops.cleanup("任务结束")
    return result
'''
write(FLOW, flow)
ast.parse(flow)

app = read(APP)
app = replace_once(app, "import tempfile\n", "import tempfile\nimport traceback\n", "traceback import")
app = replace_once(app, '    "cpa_mint_cookie_inject": True,\n', '    "cpa_mint_cookie_inject": True,\n    "cpa_oidc_request_timeout_sec": 15,\n    "cpa_oidc_poll_timeout_sec": 15,\n    "grok2api_allow_legacy_full_save": False,\n', "config defaults")

config_block = r'''def _require_bool(cfg, key):
    value = cfg.get(key)
    if type(value) is not bool:
        raise ConfigError(f"配置项 {key} 必须是布尔值 true/false")
    return value


def _require_int(cfg, key, minimum, maximum):
    value = cfg.get(key)
    if type(value) is not int:
        raise ConfigError(f"配置项 {key} 必须是整数")
    if not minimum <= value <= maximum:
        raise ConfigError(f"配置项 {key} 必须在 {minimum} 到 {maximum} 之间")
    return value


def _require_string(cfg, key, path=False):
    value = cfg.get(key)
    if not isinstance(value, str):
        raise ConfigError(f"配置项 {key} 必须是字符串")
    value = value.strip() if key not in ("user_agent",) else value
    if "\x00" in value:
        raise ConfigError(f"配置项 {key} 包含非法空字符")
    if path and value:
        os.path.expanduser(value)
    return value


def validate_config(raw):
    if not isinstance(raw, dict):
        raise ConfigError("config root must be a JSON object")
    cfg = {**DEFAULT_CONFIG, **raw}
    bool_keys = (
        "enable_nsfw", "grok2api_auto_add_local", "grok2api_auto_add_remote",
        "grok2api_allow_legacy_full_save", "cpa_export_enabled",
        "cpa_copy_to_hotload", "cpa_headless", "cpa_force_standalone",
        "cpa_mint_cookie_inject",
    )
    for key in bool_keys:
        cfg[key] = _require_bool(cfg, key)
    cfg["register_count"] = _require_int(cfg, "register_count", 1, 2500)
    cfg["cpa_mint_timeout_sec"] = _require_int(cfg, "cpa_mint_timeout_sec", 30, 1800)
    cfg["cpa_oidc_request_timeout_sec"] = _require_int(cfg, "cpa_oidc_request_timeout_sec", 3, 120)
    cfg["cpa_oidc_poll_timeout_sec"] = _require_int(cfg, "cpa_oidc_poll_timeout_sec", 3, 120)
    string_keys = tuple(key for key, value in DEFAULT_CONFIG.items() if isinstance(value, str))
    path_keys = {"grok2api_local_token_file", "api_reverse_tools", "cpa_auth_dir", "cpa_hotload_dir"}
    for key in string_keys:
        cfg[key] = _require_string(cfg, key, path=key in path_keys)
    enums = {
        "email_provider": {"duckmail", "yyds", "cloudflare", "cloudmail"},
        "cloudflare_auth_mode": {"query-key", "bearer", "x-api-key", "x-admin-auth", "none"},
        "grok2api_pool_name": {"ssoBasic", "ssoSuper"},
    }
    for key, allowed in enums.items():
        value = cfg.get(key, DEFAULT_CONFIG.get(key, ""))
        if value not in allowed:
            raise ConfigError(f"配置项 {key} 的值无效: {value!r}; 允许值: {sorted(allowed)}")
        cfg[key] = value
    return cfg


def load_config():
    global config
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
            config = validate_config(loaded)
        except ConfigError:
            raise
        except Exception as exc:
            raise ConfigError(f"配置文件解析失败: {CONFIG_FILE}: {exc}") from exc
    else:
        config = validate_config(DEFAULT_CONFIG.copy())
    return config


'''
app = replace_between(app, "def load_config():\n", "def save_config():\n", config_block, "config load/validation")
app = replace_once(app, "def save_config():\n    config_dir", "def save_config():\n    global config\n    config = validate_config(config)\n    config_dir", "validate before save")
app = replace_once(app, "\nload_config()\n\nEXTENSION_PATH", "\nEXTENSION_PATH", "remove import-time config load")

insert_exceptions = r'''

class RemoteTokenCompatibilityError(RuntimeError):
    pass


class RemoteTokenRequestError(RuntimeError):
    pass


def log_exception(context, exc, log_callback=None):
    message = f"{context}: {exc.__class__.__name__}: {exc}"
    if log_callback:
        log_callback(f"[!] {message}")
    else:
        print(f"[!] {message}", file=sys.stderr)
    return message
'''
app = replace_once(app, "class ConfigError(RuntimeError):\n    pass\n", "class ConfigError(RuntimeError):\n    pass\n" + insert_exceptions, "exception helpers")

remote_block = r'''def add_token_to_grok2api_remote_pool(raw_token, email="", log_callback=None):
    token = _normalize_sso_token(raw_token)
    if not token:
        return False
    base = str(config.get("grok2api_remote_base", "") or "").strip().rstrip("/")
    app_key = str(config.get("grok2api_remote_app_key", "") or "").strip()
    pool_name = str(config.get("grok2api_pool_name", "ssoBasic") or "ssoBasic").strip()
    if not base or not app_key:
        raise RemoteTokenRequestError("grok2api 远端未配置 base/app_key")
    headers = {"Content-Type": "application/json"}
    query = {"app_key": app_key}
    remote_pool = {"ssoBasic": "basic", "ssoSuper": "super"}[pool_name]
    api_bases = get_grok2api_remote_api_bases(base)
    incompatible = []
    add_payload = {"tokens": [token], "pool": remote_pool, "tags": ["auto-register"]}
    for api_base in api_bases:
        endpoint = f"{api_base}/tokens/add"
        try:
            response = http_post(endpoint, headers=headers, params=query, json=add_payload, timeout=30)
        except Exception as exc:
            raise RemoteTokenRequestError(f"远端 /tokens/add 网络请求失败: {endpoint}: {exc}") from exc
        status = int(getattr(response, "status_code", 0) or 0)
        if 200 <= status < 300:
            if log_callback:
                log_callback(f"[+] 已写入 grok2api 远端池: {pool_name} ({endpoint})")
            return True
        if status in (404, 405):
            incompatible.append(f"{endpoint}: HTTP {status}")
            continue
        body = str(getattr(response, "text", "") or "")[:300]
        raise RemoteTokenRequestError(f"远端 /tokens/add 请求失败，不允许全量回退: {endpoint}: HTTP {status}: {body}")
    if not bool(config.get("grok2api_allow_legacy_full_save", False)):
        raise RemoteTokenCompatibilityError(
            "/tokens/add 不受支持，旧版全量保存默认禁用以避免并发覆盖: " + "; ".join(incompatible)
        )
    current = None
    fallback_base = None
    etag = None
    load_errors = []
    for api_base in api_bases or [base]:
        endpoint = f"{api_base}/tokens"
        try:
            response = http_get(endpoint, headers=headers, params=query, timeout=20)
        except Exception as exc:
            raise RemoteTokenRequestError(f"旧版远端池读取网络失败: {endpoint}: {exc}") from exc
        status = int(getattr(response, "status_code", 0) or 0)
        if status != 200:
            load_errors.append(f"{endpoint}: HTTP {status}")
            continue
        payload = response.json()
        candidate = payload.get("tokens") if isinstance(payload, dict) and "tokens" in payload else payload
        if not isinstance(candidate, dict):
            load_errors.append(f"{endpoint}: unexpected payload")
            continue
        current = candidate
        fallback_base = api_base
        response_headers = getattr(response, "headers", {}) or {}
        etag = response_headers.get("ETag") or response_headers.get("etag")
        break
    if current is None or fallback_base is None:
        raise RemoteTokenRequestError("无法安全读取旧版远端 token 池: " + "; ".join(load_errors))
    pool = current.get(pool_name)
    if pool is None:
        pool = []
    elif not isinstance(pool, list):
        raise RemoteTokenRequestError(f"远端 token 池 {pool_name} 不是列表，拒绝全量覆盖")
    existing = {
        _normalize_sso_token(item if isinstance(item, str) else item.get("token", ""))
        for item in pool if isinstance(item, (str, dict))
    }
    if token not in existing:
        pool.append({"token": token, "tags": ["auto-register"], "note": email})
    current[pool_name] = pool
    save_headers = dict(headers)
    if etag:
        save_headers["If-Match"] = etag
    elif log_callback:
        log_callback("[!] 旧版远端接口未提供 ETag；已由显式配置允许，但仍不建议多实例并发")
    endpoint = f"{fallback_base}/tokens"
    try:
        response = http_post(endpoint, headers=save_headers, params=query, json=current, timeout=30)
    except Exception as exc:
        raise RemoteTokenRequestError(f"旧版远端池保存网络失败: {endpoint}: {exc}") from exc
    status = int(getattr(response, "status_code", 0) or 0)
    if not 200 <= status < 300:
        raise RemoteTokenRequestError(f"旧版远端池保存失败: {endpoint}: HTTP {status}")
    if log_callback:
        log_callback(f"[+] 已写入 grok2api 远端池（旧版兼容）: {pool_name} ({endpoint})")
    return True


'''
app = replace_between(app, "def add_token_to_grok2api_remote_pool", "def add_token_to_grok2api_pools", remote_block, "remote token writer")

pools_block = r'''def add_token_to_grok2api_pools(raw_token, email="", log_callback=None):
    result = {
        "local": {"enabled": bool(config.get("grok2api_auto_add_local", False)), "ok": None, "error": None},
        "remote": {"enabled": bool(config.get("grok2api_auto_add_remote", False)), "ok": None, "error": None},
    }
    if result["local"]["enabled"]:
        try:
            result["local"]["ok"] = bool(add_token_to_grok2api_local_pool(raw_token, email=email, log_callback=log_callback))
        except Exception as exc:
            result["local"]["ok"] = False
            result["local"]["error"] = log_exception("写入 grok2api 本地池失败", exc, log_callback)
    if result["remote"]["enabled"]:
        try:
            result["remote"]["ok"] = bool(add_token_to_grok2api_remote_pool(raw_token, email=email, log_callback=log_callback))
        except Exception as exc:
            result["remote"]["ok"] = False
            result["remote"]["error"] = log_exception("写入 grok2api 远端池失败", exc, log_callback)
    return result


'''
app = replace_between(app, "def add_token_to_grok2api_pools", "def apply_browser_proxy_option", pools_block, "structured pool result")

shared = r'''
def _save_mail_credential(email, credential, log_callback=None):
    path = os.path.join(os.path.dirname(__file__), "mail_credentials.txt")
    try:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(f"{email}\t{credential}\n")
            handle.flush()
        return True
    except Exception as exc:
        log_exception("保存邮箱凭据失败", exc, log_callback)
        return False


def _append_account_line(path, email, password, sso):
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(f"{email}----{password}----{sso}\n")
        handle.flush()
        os.fsync(handle.fileno())


def _queue_unsaved_account(path, payload, error, log_callback=None):
    pending_path = path + ".pending.jsonl"
    record = dict(payload)
    record["save_error"] = str(error)
    record["queued_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    try:
        with open(pending_path, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.chmod(pending_path, 0o600)
        except Exception:
            pass
        return True
    except Exception as exc:
        log_exception("写入账号 pending 队列失败", exc, log_callback)
        return False


def run_registration_common(count, log_callback, cancel_callback, accounts_output_file, observer):
    from registration_flow import RegistrationCallbacks, RegistrationOperations, run_batch
    callbacks = RegistrationCallbacks(log=log_callback, cancelled=cancel_callback)
    operations = RegistrationOperations(
        start_browser=lambda: start_browser(log_callback=log_callback),
        restart_browser=lambda: restart_browser(log_callback=log_callback),
        browser_missing=lambda: browser is None,
        open_signup_page=lambda: open_signup_page(log_callback=log_callback, cancel_callback=cancel_callback),
        fill_email_and_submit=lambda: fill_email_and_submit(log_callback=log_callback, cancel_callback=cancel_callback),
        save_mail_credential=lambda email, token: _save_mail_credential(email, token, log_callback),
        fill_code_and_submit=lambda email, token: fill_code_and_submit(email, token, log_callback=log_callback, cancel_callback=cancel_callback),
        fill_profile_and_submit=lambda: fill_profile_and_submit(log_callback=log_callback, cancel_callback=cancel_callback),
        wait_for_sso_cookie=lambda: wait_for_sso_cookie(log_callback=log_callback, cancel_callback=cancel_callback),
        enable_nsfw=lambda sso: enable_nsfw_for_token(sso, log_callback=log_callback),
        persist_account_line=lambda email, password, sso: _append_account_line(accounts_output_file, email, password, sso),
        queue_unsaved_result=lambda payload, error: _queue_unsaved_account(accounts_output_file, payload, error, log_callback),
        add_tokens=lambda sso, email: add_token_to_grok2api_pools(sso, email=email, log_callback=log_callback),
        export_cpa=lambda email, password, sso: maybe_export_cpa_xai_after_success(
            email=email, password=password, sso=sso,
            log_callback=log_callback, cancel_callback=cancel_callback,
        ),
        cleanup=lambda reason: cleanup_runtime_memory(log_callback=log_callback, reason=reason),
        sleep=lambda seconds: sleep_with_cancel(seconds, cancel_callback),
        cancelled_exception=RegistrationCancelled,
        retry_exception=AccountRetryNeeded,
    )
    return run_batch(
        count=count,
        callbacks=callbacks,
        observer=observer,
        ops=operations,
        enable_nsfw=bool(config.get("enable_nsfw", True)),
        cleanup_interval=MEMORY_CLEANUP_INTERVAL,
        max_slot_retry=3,
        max_mail_retry=3,
    )


'''
app = replace_once(app, "class GrokRegisterGUI:\n", shared + "class GrokRegisterGUI:\n", "shared registration adapter")
app = replace_once(app, "        self._ui_thread_id = threading.get_ident()\n        self.accounts_output_file = \"\"\n        self.setup_ui()\n", "        self.accounts_output_file = \"\"\n        self.setup_ui()\n        self.root.after(50, self.process_ui_queue)\n", "GUI queue startup")
app = replace_once(app, "    def setup_ui(self):\n        load_config()\n", "    def setup_ui(self):\n        load_config()\n", "GUI load remains reachable")

queue_methods = r'''    def process_ui_queue(self):
        try:
            while True:
                event = self.ui_queue.get_nowait()
                kind = event[0]
                if kind == "log":
                    line = event[1]
                    self.log_text.insert(tk.END, f"{line}\n")
                    self.log_text.see(tk.END)
                elif kind == "stats":
                    self.stats_var.set(f"成功: {event[1]} | 失败: {event[2]}")
                elif kind == "running":
                    running = bool(event[1])
                    self.start_btn.config(state=tk.DISABLED if running else tk.NORMAL)
                    self.stop_btn.config(state=tk.NORMAL if running else tk.DISABLED)
                    self.status_var.set("运行中..." if running else "就绪")
                    self.status_label.config(foreground="blue" if running else "green")
                elif kind == "error":
                    messagebox.showerror(event[1], event[2])
        except queue.Empty:
            pass
        except Exception as exc:
            print(f"[!] UI 队列处理失败: {exc}", file=sys.stderr)
        finally:
            try:
                self.root.after(50, self.process_ui_queue)
            except Exception:
                pass

    def log(self, message):
        timestamp = datetime.datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] {message}"
        print(line, flush=True)
        self.ui_queue.put(("log", line))

    def clear_log(self):
        self.log_text.delete(1.0, tk.END)

    def update_stats(self):
        self.ui_queue.put(("stats", self.success_count, self.fail_count))

    def _set_running_ui(self, running):
        self.is_running = bool(running)
        self.ui_queue.put(("running", self.is_running))


'''
app = replace_between(app, "    def _call_ui", "    def should_stop", queue_methods, "GUI main-thread queue")

new_gui_run = r'''    def run_registration(self, count):
        def observer(batch, account, output):
            self.success_count = batch.success_count
            self.fail_count = batch.fail_count
            if account is not None:
                self.results.append({"email": account.email, "sso": account.sso, "profile": account.profile, "output": output})
            self.update_stats()
        try:
            batch = run_registration_common(
                count=count,
                log_callback=self.log,
                cancel_callback=self.should_stop,
                accounts_output_file=self.accounts_output_file,
                observer=observer,
            )
            self.success_count = batch.success_count
            self.fail_count = batch.fail_count
        except Exception as exc:
            log_exception("任务异常", exc, self.log)
        finally:
            self._set_running_ui(False)
            self.log("[*] 任务结束")


'''
app = replace_between(app, "    def run_registration(self, count):", "\n\nclass CliStopController:", new_gui_run, "GUI shared batch")

new_cli = r'''def run_registration_cli(count):
    controller = CliStopController()
    accounts_output_file = os.path.join(
        os.path.dirname(__file__),
        f"accounts_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
    )
    cli_log(f"[*] 终端模式启动，目标数量: {count}")
    cli_log(f"[*] 成功账号将实时保存到: {accounts_output_file}")
    last_stats = {"success": 0, "fail": 0}
    def observer(batch, account, output):
        last_stats["success"] = batch.success_count
        last_stats["fail"] = batch.fail_count
        cli_log(f"[*] 当前统计: 成功 {batch.success_count} | 失败 {batch.fail_count}")
    try:
        batch = run_registration_common(
            count=count,
            log_callback=cli_log,
            cancel_callback=controller.should_stop,
            accounts_output_file=accounts_output_file,
            observer=observer,
        )
        last_stats["success"] = batch.success_count
        last_stats["fail"] = batch.fail_count
    except KeyboardInterrupt:
        controller.stop()
        cli_log("[!] 收到 Ctrl+C，正在停止并清理")
    except Exception as exc:
        log_exception("任务异常", exc, cli_log)
    finally:
        cli_log(f"[*] 任务结束。成功 {last_stats['success']} | 失败 {last_stats['fail']}")


'''
app = replace_between(app, "def run_registration_cli(count):", "def main_cli():", new_cli, "CLI shared batch")
ast.parse(app)
write(APP, app)

oauth = read(OAUTH)
oauth = replace_once(oauth, "def discover(proxy=None, timeout=30.0):", "def discover(proxy=None, timeout=30.0, cancel=None, retries=2):", "discover signature")
old_discover_body_start = "def discover(proxy=None, timeout=30.0, cancel=None, retries=2):\n"
new_discover = r'''def discover(proxy=None, timeout=30.0, cancel=None, retries=2):
    request = urllib.request.Request(
        DISCOVERY_URL,
        method="GET",
        headers={"Accept": "application/json", "User-Agent": "grok-register-cpa/1.0"},
    )
    last_error = None
    for attempt in range(max(int(retries), 0) + 1):
        _check_cancel(cancel)
        opener = _build_opener(proxy)
        try:
            with opener.open(request, timeout=float(timeout)) as response:
                body = response.read().decode("utf-8", errors="replace")
                status = int(getattr(response, "status", 200) or 200)
            _check_cancel(cancel)
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise OAuthDeviceError("xAI discovery failed HTTP %s: %s" % (exc.code, body))
        except Exception as exc:
            last_error = exc
            if not _is_transient_net_error(exc) or attempt >= int(retries):
                raise OAuthDeviceError("xAI discovery request failed: %s" % exc)
            _sleep_with_cancel(1.0 * (attempt + 1), cancel)
            continue
        if status != 200:
            raise OAuthDeviceError("xAI discovery failed HTTP %s: %s" % (status, body))
        try:
            payload = json.loads(body)
        except Exception as exc:
            raise OAuthDeviceError("xAI discovery parse failed: %s" % exc)
        return {
            "device_authorization_endpoint": _validate_endpoint(
                payload.get("device_authorization_endpoint"), "device_authorization_endpoint"
            ),
            "token_endpoint": _validate_endpoint(payload.get("token_endpoint"), "token_endpoint"),
        }
    raise OAuthDeviceError("xAI discovery failed: %s" % last_error)


'''
oauth = replace_between(oauth, old_discover_body_start, "def _is_transient_net_error", new_discover, "cancellable discovery")
helper = r'''def _check_cancel(cancel):
    if cancel and cancel():
        raise OAuthDeviceError("cancelled")


def _sleep_with_cancel(seconds, cancel=None):
    deadline = time.time() + max(float(seconds), 0.0)
    while time.time() < deadline:
        _check_cancel(cancel)
        time.sleep(min(0.2, max(deadline - time.time(), 0.0)))
    _check_cancel(cancel)


'''
oauth = replace_once(oauth, "def _is_transient_net_error", helper + "def _is_transient_net_error", "cancel helpers")
oauth = replace_once(oauth, "def _post_form(url, form, timeout=30.0, proxy=None, retries=0, retry_sleep=1.5):", "def _post_form(url, form, timeout=30.0, proxy=None, retries=0, retry_sleep=1.5, cancel=None):", "post cancel signature")
oauth = replace_once(oauth, "    for attempt in range(max(int(retries), 0) + 1):\n        opener = _build_opener(proxy)\n", "    for attempt in range(max(int(retries), 0) + 1):\n        _check_cancel(cancel)\n        opener = _build_opener(proxy)\n", "post precheck")
oauth = replace_once(oauth, "                status = int(getattr(response, \"status\", 200) or 200)\n", "                status = int(getattr(response, \"status\", 200) or 200)\n            _check_cancel(cancel)\n", "post postcheck")
oauth = replace_once(oauth, "            time.sleep(float(retry_sleep) * (attempt + 1))\n", "            _sleep_with_cancel(float(retry_sleep) * (attempt + 1), cancel)\n", "post cancel sleep")
oauth = replace_between(oauth, "def request_device_code", "def _sleep_with_cancel", r'''def request_device_code(client_id=CLIENT_ID, scope=SCOPE, timeout=15.0, proxy=None, cancel=None, retries=2):
    discovery = discover(proxy=proxy, timeout=timeout, cancel=cancel, retries=retries)
    _check_cancel(cancel)
    device_endpoint = discovery["device_authorization_endpoint"]
    token_endpoint = discovery["token_endpoint"]
    status, payload = _post_form(
        device_endpoint,
        {"client_id": client_id, "scope": scope},
        timeout=timeout,
        proxy=proxy,
        retries=retries,
        retry_sleep=1.0,
        cancel=cancel,
    )
    _check_cancel(cancel)
    if status != 200 or not isinstance(payload, dict):
        raise OAuthDeviceError("device code request failed HTTP %s: %r" % (status, payload))
    device_code = str(payload.get("device_code") or "").strip()
    user_code = str(payload.get("user_code") or "").strip()
    if not device_code or not user_code:
        raise OAuthDeviceError("device code response missing fields: %r" % payload)
    verification_uri = str(payload.get("verification_uri") or "https://accounts.x.ai/oauth2/device").strip()
    verification_uri_complete = str(
        payload.get("verification_uri_complete") or ("%s?user_code=%s" % (verification_uri, user_code))
    ).strip()
    return DeviceCodeSession(
        device_code=device_code,
        user_code=user_code,
        verification_uri=verification_uri,
        verification_uri_complete=verification_uri_complete,
        expires_in=int(payload.get("expires_in") or 1800),
        interval=max(int(payload.get("interval") or 5), 1),
        token_endpoint=token_endpoint,
        raw=payload,
    )


''', "cancellable device request")
# Remove duplicate old helper left by boundary endpoint.
first = oauth.find("def _sleep_with_cancel")
second = oauth.find("def _sleep_with_cancel", first + 1)
if second >= 0:
    end = oauth.find("def poll_device_token", second)
    oauth = oauth[:second] + oauth[end:]
oauth = oauth.replace("timeout=min(float(timeout), 5.0)", "timeout=float(timeout)")
oauth = oauth.replace("retry_sleep=1.0,\n            )", "retry_sleep=1.0,\n                cancel=cancel,\n            )", 1)
ast.parse(oauth)
write(OAUTH, oauth)

browser = read(BROWSER)
old_create = r'''    resolved = resolve_proxy(proxy)
    proxy_bridge = None
    chrome_proxy, proxy_bridge = prepare_chromium_proxy(resolved, log=logger)
    try:
        if chrome_proxy:
            options.set_argument("--proxy-server=%s" % chrome_proxy)
            logger("browser proxy=%s (chromium %s)" % (proxy_log_label(resolved), chrome_proxy))
        else:
            logger("browser proxy=(none)")

        browser = Chromium(options)
        if proxy_bridge is not None:
            try:
                setattr(browser, "_cpa_proxy_bridge", proxy_bridge)
            except Exception:
                pass
        _register_mint_browser(browser)
        page = browser.latest_tab
        logger("standalone chromium started")
        return browser, page
    except Exception:
        if proxy_bridge is not None:
            try:
                proxy_bridge.stop()
            except Exception:
                pass
        raise
'''
new_create = r'''    resolved = resolve_proxy(proxy)
    proxy_bridge = None
    browser = None
    chrome_proxy, proxy_bridge = prepare_chromium_proxy(resolved, log=logger)
    try:
        if chrome_proxy:
            options.set_argument("--proxy-server=%s" % chrome_proxy)
            logger("browser proxy=%s (chromium %s)" % (proxy_log_label(resolved), chrome_proxy))
        else:
            logger("browser proxy=(none)")
        browser = Chromium(options)
        if proxy_bridge is not None:
            setattr(browser, "_cpa_proxy_bridge", proxy_bridge)
        page = browser.latest_tab
        _register_mint_browser(browser)
        logger("standalone chromium started")
        return browser, page
    except Exception:
        if browser is not None:
            close_standalone(browser)
        elif proxy_bridge is not None:
            try:
                proxy_bridge.stop()
            except Exception:
                pass
        raise
'''
browser = replace_once(browser, old_create, new_create, "CPA browser creation cleanup")
browser = replace_once(browser, "    recycle_every: int = 15,\n):", "    recycle_every: int = 15,\n    request_timeout_sec: float = 15.0,\n    poll_timeout_sec: float = 15.0,\n):", "mint timeout params")
old_retry = r'''        last_error = None
        session = None
        for attempt in range(1, 4):
            try:
                session = request_device_code(proxy=resolved or None)
                last_error = None
                break
            except Exception as exc:
                last_error = exc
                logger("request_device_code attempt %s/3 failed: %s" % (attempt, exc))
                _sleep(1.5 * attempt)
        if session is None:
            raise last_error or RuntimeError("request_device_code failed")
'''
new_retry = r'''        session = request_device_code(
            proxy=resolved or None,
            timeout=float(request_timeout_sec),
            cancel=cancel,
            retries=2,
        )
'''
browser = replace_once(browser, old_retry, new_retry, "single OIDC retry strategy")
browser = replace_once(browser, "                    proxy=resolved or None,\n                )", "                    proxy=resolved or None,\n                    timeout=float(poll_timeout_sec),\n                )", "poll configurable timeout")
ast.parse(browser)
write(BROWSER, browser)

export = read(EXPORT)
export = replace_once(export, "    timeout = float(cfg.get(\"cpa_mint_timeout_sec\") or 300)\n", "    timeout = float(cfg.get(\"cpa_mint_timeout_sec\") or 300)\n    request_timeout = float(cfg.get(\"cpa_oidc_request_timeout_sec\") or 15)\n    poll_timeout = float(cfg.get(\"cpa_oidc_poll_timeout_sec\") or 15)\n", "export timeout config")
export = replace_once(export, "        cancel=cancel_callback,\n    )", "        cancel=cancel_callback,\n        request_timeout_sec=request_timeout,\n        poll_timeout_sec=poll_timeout,\n    )", "export timeout pass")
export = replace_once(export, "        except Exception:\n            pass\n    return result\n", "        except Exception as exc:\n            log(\"[cpa] failed to persist failure record: %s\" % exc)\n    return result\n", "CPA failure log")
ast.parse(export)
write(EXPORT, export)

mint = read(MINT)
mint = replace_once(mint, "    cancel=None,\n):", "    cancel=None,\n    request_timeout_sec=15.0,\n    poll_timeout_sec=15.0,\n):", "mint API timeouts")
mint = replace_once(mint, "            recycle_every=int(recycle_every or 0),\n        )", "            recycle_every=int(recycle_every or 0),\n            request_timeout_sec=float(request_timeout_sec),\n            poll_timeout_sec=float(poll_timeout_sec),\n        )", "mint pass timeouts")
ast.parse(mint)
write(MINT, mint)

for path in (APP, FLOW, OAUTH, BROWSER, EXPORT, MINT):
    ast.parse(read(path))
print("remaining hardening migration applied")
