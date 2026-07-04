#!/usr/bin/env bash
# 在 Linux 上运行 grok-register CLI。
# - 桌面环境（有 $DISPLAY）：直接跑
# - 无显示器服务器：用 xvfb-run 虚拟显卡跑非 headless（Turnstile 需要真实 DOM）
# 用法：bash run_cli.sh [python 脚本的额外参数...]
set -e

cd "$(dirname "$0")"

PY="${PYTHON:-python3}"
if ! command -v "$PY" >/dev/null 2>&1; then
    PY=python
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