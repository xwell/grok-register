<div align="center">

[![Grok Register — GUI and CLI registration automation toolkit](assets/banner.png)](https://github.com/AaronL725/grok-register)

Grok Register 是一个面向自动化流程研究、测试环境验证和个人学习的 Python 自动化注册工具 — 支持 GUI / CLI、临时邮箱、浏览器流程控制、账号输出和 grok2api token 池写入。

<p>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
  <img src="https://img.shields.io/badge/Python-3.9%2B-3776AB.svg" alt="Python 3.9+">
  <img src="https://img.shields.io/badge/Interface-GUI%20%2B%20CLI-success.svg" alt="GUI + CLI">
  <img src="https://img.shields.io/badge/Browser-Chromium%2FChrome-4285F4.svg" alt="Chromium/Chrome">
  <a href="http://makeapullrequest.com"><img src="https://img.shields.io/badge/PRs-welcome-brightgreen.svg" alt="PRs Welcome"></a>
  <a href="https://linux.do"><img src="https://img.shields.io/badge/Join-linux.do-orange" alt="linux.do"></a>
</p>

</div>

---

> 本项目仅用于自动化流程研究、测试环境验证和个人学习。请遵守目标网站服务条款、当地法律法规和第三方服务限制。

## Contents

- [功能](#功能)
- [环境要求](#环境要求)
- [安装](#安装)
- [配置](#配置)
- [运行](#运行)
- [输出文件](#输出文件)
- [稳定性机制](#稳定性机制)
- [常见问题](#常见问题)
- [目录结构](#目录结构)
- [License](#license)
- [Acknowledgments](#acknowledgments)
- [Star History](#star-history)

## 功能

- 支持 GUI 图形界面运行。
- 支持 CLI 终端运行，不启动 Tk GUI。
- 注册流程使用 Chromium/Chrome 浏览器页面完成。
- 支持 DuckMail、YYDS、Cloudflare、FreeMail 临时邮箱接口。
- 支持 FreeMail 多域名加权轮询配置。
- 支持 HTTP/SOCKS5 代理池，每账号轮换出口 IP 降低风控；带认证的 SOCKS5 自动经本地认证桥接入浏览器。
- 支持验证码邮件轮询和解析。
- 支持成功账号实时写入本地 SQLite3 数据库 `accounts.db`。
- 支持将 SSO token 写入 grok2api 本地或远端池。
- 支持注册后尝试开启 NSFW。
- 支持页面卡住检测、当前账号重试、浏览器重启和内存清理。

## 环境要求

- Python 3.9+
- Google Chrome 或 Chromium
- 可访问注册页面和临时邮箱 API 的网络环境

## 安装

下载项目到电脑：

```bash
git clone https://github.com/AaronL725/grok-register.git
cd grok-register
```

安装依赖：

```bash
pip install -r requirements.txt
```

复制配置文件：

```bash
cp config.example.json config.json
```

然后按需编辑 `config.json`。

## 配置

常用配置项：

| 配置项 | 说明 |
| --- | --- |
| `email_provider` | 邮箱服务商：`duckmail`、`yyds`、`cloudflare`、`freemail` |
| `register_count` | 本次目标注册数量 |
| `proxy` | 固定代理地址（`proxy_mode=fixed` 时使用），可留空 |
| `proxy_mode` | 代理模式：`fixed`（沿用单个 `proxy`）或 `pool`（启用代理池，仅作用于浏览器注册阶段） |
| `proxy_pool` | 代理池列表，支持 `http://`、`https://`、`socks5://`；带认证的 socks5 写 `socks5://user:pass@host:port` |
| `register_proxy_cooldown_seconds` | 代理池中同一节点两次使用间的冷却秒数（默认 180） |
| `register_proxy_pool_random_start` | 代理池是否随机起始偏移（默认 true） |
| `enable_nsfw` | 注册后是否尝试开启 NSFW |
| `cloudflare_api_base` | Cloudflare 临时邮箱 API 地址 |
| `cloudflare_auth_mode` | Cloudflare API 鉴权模式：`none`、`bearer`、`x-api-key`、`query-key` |
| `defaultDomains` | Cloudflare 临时邮箱默认域名 |
| `grok2api_auto_add_local` | 是否写入本地 grok2api token 池 |
| `grok2api_local_token_file` | 本地 grok2api token 文件路径 |
| `grok2api_auto_add_remote` | 是否写入远端 grok2api |
| `grok2api_remote_base` | 远端 grok2api 站点根地址（如 `http://127.0.0.1:8000`），程序会自动拼接 `/admin/api/tokens/add` |
| `grok2api_remote_app_key` | 远端 grok2api 管理后台密码（`app.app_key`，默认 `grok2api`），以 `Bearer` 鉴权 |
| `freemail_api_base` | FreeMail 邮箱 API 地址 |
| `freemail_admin_token` | FreeMail 管理员 Token |
| `freemail_domains` | FreeMail 加权域名配置，结构化 `[{"domain":"a.com","weight":3},{"domain":"b.com","weight":1}]`；兼容逗号分隔字符串 |

`config.json` 包含个人配置和密钥，不要提交到 Git。

## 运行

### CLI 模式

CLI 模式不会启动 Tk GUI，但注册流程仍会打开 Chromium/Chrome 浏览器页面。

```bash
python grok_register_ttk.py cli
```

看到提示后输入：

```text
start
```

停止任务：

```text
Ctrl+C
```

CLI 模式适合长时间批量运行。程序每成功注册 5 个账号会关闭浏览器、清理运行时对象并重新启动浏览器，降低长任务内存占用。

#### 非交互模式（命令行传参）

支持通过参数覆盖本次注册数量并跳过 `start` 确认，便于脚本/crontab 调度：

```bash
python grok_register_ttk.py cli -n 5 -y
# 或经 run_cli.sh（自动处理 Xvfb）
bash run_cli.sh -n 5 -y
```

参数说明：

| 参数 | 说明 |
| --- | --- |
| `-n` / `--count N` | 本次目标注册数量，覆盖 `config.json` 的 `register_count`，**不写回配置**。隐含非交互模式。 |
| `-y` / `--yes` / `--non-interactive` | 非交互模式，跳过 `start` 确认。stdin 非 tty（如 cron）时自动启用。 |
| `cli` / `start` / `--cli` | 进入 CLI 模式（不带 `-n`/`-y` 且 stdin 是 tty 时仍需手动输入 `start`）。 |

退出码（便于 cron/脚本检测失败）：

| 退出码 | 含义 |
| --- | --- |
| `0` | 至少成功注册 1 个账号 |
| `1` | 目标数量 > 0 但 0 成功（全失败/代理初始化失败/未开始即被取消） |
| `2` | 参数非法（如 `-n 0`、`-n abc`） |

### Linux 服务器运行（无显示器）

grok 注册流程含 Cloudflare Turnstile 人机验证，**headless 模式通过率极低**，因此在 Linux 服务器上推荐用 **Xvfb 虚拟显卡**跑非 headless 浏览器。

一键安装 Chromium + Xvfb（自动识别发行版）：

```bash
bash install_chromium.sh
```

用 Xvfb 虚拟显卡启动 CLI（脚本会在无显示器的环境自动包 `xvfb-run`）：

```bash
bash run_cli.sh
```

或手动：

```bash
xvfb-run -a -s '-screen 0 1280x800x24' python grok_register_ttk.py cli
```

### 定时任务（crontab）

CLI 模式支持非交互参数，可直接挂到 crontab 定时执行。cron 运行环境无 tty，`-y`（或自动检测）会跳过 `start` 确认，`-n` 指定每次注册数量。

```bash
# 每 6 小时注册 5 个账号，日志追加到文件
crontab -e
```

```cron
0 */6 * * * cd /path/to/grok-register && bash run_cli.sh -n 5 -y >> /var/log/grok-register.log 2>&1
```

说明：

- cron 默认无 `DISPLAY`，`run_cli.sh` 会自动包 `xvfb-run` 跑非 headless 浏览器（Turnstile 需真实 DOM）。
- 退出码非 0 时 cron 默认会发邮件；如需禁用可在行尾加 `|| true`，或重定向 `MAILTO=""`。
- `config.json` 用脚本绝对路径定位（与 `run_cli.sh` 同目录），不受 cron 默认 CWD 影响。

### 定时任务（systemd timer）

仓库附带 `grok-timer.sh`，用 systemd timer 管理定时注册任务。你只需写熟悉的 **5 字段 cron 表达式**，脚本自动转 systemd `OnCalendar` 并安装系统级 `grok-register@<实例>.{service,timer}`。相比 crontab：日志进 journal、`Persistent=true` 关机错过会在开机补跑、`systemctl` 统一管理、支持多实例独立配置。

```bash
# 安装：每 6 小时注册 5 个账号（默认实例 default）
sudo bash grok-timer.sh install -n 5 -c "0 */6 * * *"

# 工作日早 9:30 注册 1 个，实例名 morning
sudo bash grok-timer.sh install -n 1 -c "30 9 * * 1-5" -i morning

# 查看状态 / 列出所有实例 / 立即触发一次 / 跟随日志
sudo bash grok-timer.sh status -i morning
sudo bash grok-timer.sh list
sudo bash grok-timer.sh run-now -i morning
sudo bash grok-timer.sh logs -i morning

# 卸载（删 timer + 实例配置；最后一个实例卸载时连 service 模板一起移除）
sudo bash grok-timer.sh uninstall -i morning
```

子命令：

| 子命令 | 说明 |
| --- | --- |
| `install` | 安装/更新任务（必填 `-n`、`-c`；已存在同实例则更新调度/数量，幂等） |
| `uninstall` | 卸载实例；无残留时移除 service 模板 |
| `enable` / `disable` | 开机自启开关（不立即运行 / 不打断当前运行） |
| `start` / `stop` | 启用 / 停用调度 |
| `status` | 查看 timer、下次触发、service 最近一次结果 |
| `list` | 列出所有已安装的 grok-register timer |
| `run-now` | 立即触发一次 service（不等调度） |
| `logs` | `journalctl -f` 跟随该实例日志 |
| `convert` | 仅把 cron 转 `OnCalendar` 并打印（调试用，不需 root） |

参数：

| 参数 | 说明 |
| --- | --- |
| `-n` / `--count N` | 本次注册目标数量（install 必填，正整数） |
| `-c` / `--cron "EXPR"` | 5 字段 cron 表达式（install 必填，如 `"0 */6 * * *"`） |
| `-i` / `--instance NAME` | 实例名，默认 `default`；不同实例独立 count/调度 |
| `--force` | install 时覆盖已存在的 service 模板 |

cron 表达式支持 `*` / `*/N` / `N` / `a,b` / `a-b` / `a-b/N`；周字段 `0/7=Sun..6=Sat`；日与周同时指定时按 cron OR 语义拆为多条 `OnCalendar`。不支持 `L`/`W`/`#` 与 `@` 宏（systemd 限制）。

说明：

- 单元装在 `/etc/systemd/system`，需 root；`install`/`uninstall`/`enable`/`disable`/`start`/`stop` 需 root，`list`/`status`/`logs`/`convert` 只读不需 root。
- service 为 `Type=oneshot`，`ExecStart` 调 `run_cli.sh -n ${REGISTER_COUNT} -y`，复用 CLI 非交互路径与退出码（`SuccessExitStatus=0 1 2`，失败不触发重启，由 timer 下次触发）。
- `run_cli.sh` 未显式指定 `PYTHON` 时自动用仓库内 `venv/bin/python`（systemd 最小环境无用户 PATH，自动检测 venv 保证依赖可用）。
- `Persistent=true`（错过补跑）、`RandomizedDelaySec=300`（随机抖动 0–5 分钟避免整点尖峰）。
- 日志：`journalctl -u grok-register@<实例>`。

可选配置（`config.json`）：

| 配置项 | 说明 |
| --- | --- |
| `browser_path` | 浏览器可执行文件路径，留空时在 Linux 上自动探测 chromium/google-chrome |
| `headless` | 是否无头模式；默认非 headless（Turnstile 需真实 DOM，Linux 用 Xvfb）；`true` 强制无头 |

### GUI 模式

```bash
python grok_register_ttk.py
```

GUI 模式会打开 Tkinter 窗口，适合手动调整配置和观察日志。

## 输出文件

运行过程中会生成：

- `accounts.db`：SQLite3 数据库，存成功账号、密码、SSO token、姓名、邮箱提供商、注册时间（`accounts` 表，`email` 唯一）。
- `mail_credentials.txt`：临时邮箱凭证。
- `*.log`：可选日志文件。

这些文件包含敏感信息，已被 `.gitignore` 忽略。

## 稳定性机制

- 每个账号结束后重启浏览器。
- 每成功 5 个账号执行一次内存清理。
- CLI 模式支持 `Ctrl+C` 中断并清理浏览器。
- 最终页长时间无变化时自动重试当前账号。
- 验证码未收到时自动更换邮箱重试。

## 常见问题

### CLI 模式为什么还会打开浏览器？

CLI 模式只是不启动 Tk GUI。注册页、Turnstile、验证码提交和 SSO cookie 获取仍依赖真实浏览器环境。

### NSFW 开启失败怎么办？

如果日志显示 `Cloudflare 防护拦截，HTTP 403`，说明请求被目标站点防护拦截。程序会继续保存账号和写入 grok2api。

### GUI 显示的数量和配置不同？

GUI 数量控件可能有上限。CLI 模式直接读取 `config.json` 中的 `register_count`。

## 目录结构

```text
.
├── grok_register_ttk.py   # 主程序（GUI + CLI）
├── cf_mail_debug.py       # Cloudflare 邮箱调试工具
├── run_cli.sh             # CLI 启动器（自动 Xvfb / venv，cron 友好）
├── install_chromium.sh    # 安装 Chromium + Xvfb
├── grok-timer.sh          # systemd timer 定时任务管理（cron→OnCalendar）
├── config.example.json    # 配置示例
├── requirements.txt       # Python 依赖
└── README.md
```

## License

[MIT](LICENSE).

## Acknowledgments

Thanks to [linux.do](https://linux.do) — a vibrant tech community where this project is shared and discussed.

## Star History

<a href="https://www.star-history.com/?repos=AaronL725%2Fgrok-register&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=AaronL725/grok-register&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=AaronL725/grok-register&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=AaronL725/grok-register&type=date&legend=top-left" />
 </picture>
</a>
