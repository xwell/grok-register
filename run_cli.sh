#!/usr/bin/env bash
# 在 Linux 上运行 grok-register CLI。
# - 桌面环境（有 $DISPLAY）：直接跑
# - 无显示器服务器：用 xvfb-run 虚拟显卡跑非 headless（Turnstile 需要真实 DOM）
# 用法：bash run_cli.sh [python 脚本的额外参数...]
#   非交互 + 指定数量（适合 crontab）：bash run_cli.sh -n 5 -y
#   crontab 示例：
#     0 */6 * * * cd /path/to/grok-register && bash run_cli.sh -n 5 -y >> /var/log/grok-register.log 2>&1
# 退出码：≥1 个注册成功 → 0；全部失败 → 非 0；参数非法 → 2。
set -e

cd "$(dirname "$0")"

# cron 无 tty，确保非 cli_log 的库输出也及时落盘
export PYTHONUNBUFFERED=1

PY="${PYTHON:-}"
# 若未显式指定 PYTHON，优先用仓库内 venv（systemd/cron 最小环境常无依赖）
if [ -z "$PY" ]; then
    if [ -x "$(dirname "$0")/venv/bin/python" ]; then
        PY="$(dirname "$0")/venv/bin/python"
    else
        PY=python3
        if ! command -v "$PY" >/dev/null 2>&1; then
            PY=python
        fi
    fi
fi

# 检查 Xvfb 可用性；缺失则提示装
need_xvfb=0
if [ -z "${DISPLAY:-}" ]; then
    if ! command -v xvfb-run >/dev/null 2>&1; then
        echo "[run_cli] 当前环境无 DISPLAY 且未安装 xvfb-run。" >&2
        echo "[run_cli] 请先运行: bash install_chromium.sh" >&2
        exit 1
    fi
    need_xvfb=1
fi

if [ "$need_xvfb" = "1" ]; then
    echo "[run_cli] 无显示器，使用 Xvfb 虚拟显卡运行（非 headless）"
    exec xvfb-run -a -s '-screen 0 1280x800x24' "$PY" grok_register_ttk.py cli "$@"
else
    exec "$PY" grok_register_ttk.py cli "$@"
fi