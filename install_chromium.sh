#!/usr/bin/env bash
# 安装 Chromium 及其运行依赖，并在无显示器的 Linux 服务器上安装 Xvfb 虚拟显卡。
# 自动识别发行版（Debian/Ubuntu、RHEL/CentOS/Fedora、Alpine、Arch）。
# 用法：bash install_chromium.sh
set -e

detect_distro() {
    if [ -f /etc/os-release ]; then
        # shellcheck disable=SC1091
        . /etc/os-release
        echo "${ID:-unknown}|${ID_LIKE:-}"
    else
        echo "unknown|"
    fi
}

install_via_apt() {
    export DEBIAN_FRONTEND=noninteractive
    # discover Chromium 需要的运行库（即便走系统 chromium 也可能缺失）
    apt-get update -y
    apt-get install -y \
        chromium \
        xvfb \
        libnss3 libnspr4 libatk1.0-0 libatk-bridge2.0-0 libcups2 \
        libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
        libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2 \
        libatspi2.0-0 libxshmfence1 fonts-liberation xdg-utils \
        || {
            # 某些发行版包名是 chromium-browser
            echo "[install] 'chromium' 包不可用，尝试 chromium-browser ..."
            apt-get install -y chromium-browser
        }
    # 字体：避免页面乱码/方块
    apt-get install -y fonts-noto-cjk || apt-get install -y fonts-wqy-zenhei || true
}

install_via_dnf() {
    dnf install -y epel-release 2>/dev/null || true
    dnf install -y \
        chromium \
        xorg-x11-server-Xvfb \
        nss nspr atk at-spi2-atk cups-libs libdrm libxkbcommon \
        libXcomposite libXdamage libXfixes libXrandr libgbm \
        pango cairo alsa-lib at-spi2-core libXshmfence \
        liberation-fonts-common xdg-utils \
        || dnf install -y chromium-headless chromium
    dnf install -y google-noto-sans-cjk-fonts || dnf install -y wqy-zenhei-fonts || true
}

install_via_yum() {
    yum install -y epel-release 2>/dev/null || true
    yum install -y \
        chromium \
        xorg-x11-server-Xvfb \
        nss nspr atk at-spi2-atk cups-libs libdrm libxkbcommon \
        libXcomposite libXdamage libXfixes libXrandr libgbm \
        pango cairo alsa-lib at-spi2-core libXshmfence \
        liberation-fonts-common xdg-utils \
        || yum install -y chromium-headless chromium
    yum install -y google-noto-sans-cjk-fonts || yum install -y wqy-zenhei-fonts || true
}

install_via_apk() {
    apk update
    apk add --no-cache \
        chromium \
        xvfb \
        nss freetype harfbuzz ca-certificates ttf-freefont \
        eudev mesa-egl glib libxcomposite libxdamage libxrandh \
        libxkbcommon libdrm libgcc \
        font-noto-cjk || true
}

install_via_pacman() {
    pacman -Sy --noconfirm \
        chromium \
        xorg-server-xvfb \
        nss at-spi2-atk cups libdrm libxkbcommon libxcomposite \
        libxdamage libxrandr libgbm pango cairo alsa-lib \
        noto-fonts-cjk
}

DISTRO="$(detect_distro)"
echo "[install] 检测到发行版: ${DISTRO%%|*}"

case "${DISTRO}" in
    *debian*|*ubuntu*|*linuxmint*|*raspbian*)
        install_via_apt
        ;;
    *fedora*)
        install_via_dnf
        ;;
    *rhel*|*centos*|*rocky*|*almalinux*|*amazon*|*oracle*)
        # 优先 dnf，找不到则回退 yum
        if command -v dnf >/dev/null 2>&1; then
            install_via_dnf
        else
            install_via_yum
        fi
        ;;
    *alpine*)
        install_via_apk
        ;;
    *arch*|*manjaro*|*endeavouros*)
        install_via_pacman
        ;;
    *)
        echo "[install] 未识别的发行版，尝试 apt 兜底..."
        install_via_apk 2>/dev/null || install_via_apt 2>/dev/null || {
            echo "[install] 无法识别发行版，请手动安装 chromium + xvfb 及运行依赖。"
            exit 1
        }
        ;;
esac

echo
echo "[install] 安装完成。校验结果:"
command -v chromium \
    || command -v chromium-browser \
    || command -v google-chrome \
    || command -v google-chrome-stable \
    || find /usr -maxdepth 4 -type f -name 'chrome' 2>/dev/null | head -3
echo "Xvfb: $(command -v Xvfb 2>/dev/null || echo '未找到')"
echo
echo "下一步: 在无显示器的服务器上用 xvfb-run 启动 CLI:"
echo "  xvfb-run -a -s '-screen 0 1280x800x24' python grok_register_ttk.py cli"
echo "（或直接运行本仓库的 ./run_cli.sh）"