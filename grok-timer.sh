#!/usr/bin/env bash
# grok-register 定时任务管理脚本（systemd + timer）。
#
# 用 cron 表达式（5 字段，用户熟悉）自动转 systemd OnCalendar，安装/管理
# 系统级 grok-register@<instance>.{service,timer}。支持多实例、幂等安装。
#
# 用法:
#   bash grok-timer.sh install -n 5 -c "0 */6 * * *" [-i morning]
#   bash grok-timer.sh status [-i morning]
#   bash grok-timer.sh list
#   bash grok-timer.sh run-now [-i morning]
#   bash grok-timer.sh logs [-i morning]
#   bash grok-timer.sh uninstall [-i morning]
#   (enable/disable/start/stop 见 --help)
set -euo pipefail

# --- 常量 -----------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_PREFIX="grok-register"
SYSTEMD_DIR="/etc/systemd/system"
REPO_ROOT="$SCRIPT_DIR"
RUN_CLI="$REPO_ROOT/run_cli.sh"

# --- 日志 -----------------------------------------------------------------
log()  { printf '[timer] %s\n' "$*"; }
warn() { printf '[timer] WARNING: %s\n' "$*" >&2; }
die()  { printf '[timer] 错误: %s\n' "$*" >&2; exit 1; }

# --- 前置检查 -------------------------------------------------------------
require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        die "操作 /etc/systemd/system 需要 root。请用 sudo 或 root 用户运行。"
    fi
}
require_systemd() {
    command -v systemctl >/dev/null 2>&1 || die "未找到 systemctl，当前环境不是 systemd。"
    systemctl list-units --quiet >/dev/null 2>&1 || die "systemctl 不可用（非 systemd 会话？）。"
}

# 实例名白名单：字母数字下划线短横
valid_instance() {
    local name="$1"
    [ -n "$name" ] || return 1
    [[ "$name" =~ ^[A-Za-z0-9_-]+$ ]] || return 1
    # 拒绝可能拼出路径分隔的写法
    case "$name" in -|*.*) return 1;; esac
    return 0
}

# =========================================================================
# cron 表达式 → systemd OnCalendar 转换
# 输入: 5 字段 cron（min hr dom mon dow）
# 输出: stdout 一行或多行 OnCalendar 值（dom+dow 都非 * 时按 OR 拆两行）
# 失败: die() 报错退出
# =========================================================================

# dow 数字(0-7, 0/7=Sun) → Mon..Sun 缩写
_dow_num_to_name() {
    case "$1" in
        0|7) echo Sun;; 1) echo Mon;; 2) echo Tue;; 3) echo Wed;;
        4) echo Thu;; 5) echo Fri;; 6) echo Sat;; *) return 1;;
    esac
}

# 校验单个字段是否为合法 cron 数字词：* / */N / N / a,b / a-b / a-b/N
# $1=字段值  $2=允许最小值  $3=允许最大值  $4=该字段基准值(*/N 起始：min/hr=0, dom/mon=1)
# stdout 输出归一化后的 OnCalendar 片段：
#   * → *；*/N → base/N；a-b → a..b；a-b/N → a..b/N；a,b → 逐项补零；单值 → 补零
_validate_field() {
    local val="$1" lo="$2" hi="$3" base="$4"
    local n a b
    # 拒绝 systemd 不支持的 cron 扩展
    case "$val" in
        *L*|*W*|*\#*) die "cron 字段 '$val' 含 L/W/# 扩展，systemd OnCalendar 不支持。";;
    esac
    if [ "$val" = "*" ]; then echo "*"; return 0; fi
    # */N → base/N
    if [[ "$val" =~ ^\*/[0-9]+$ ]]; then
        n="${val#*/}"
        [ "$n" -ge 1 ] 2>/dev/null || die "cron 步长 '$val' 非法。"
        printf '%02d/%d' "$base" "$n"
        return 0
    fi
    # 逗号列表：递归处理每项（列表项不接受步长）
    if [[ "$val" == *,* ]]; then
        local out="" item
        local IFS=','
        for part in $val; do
            item="$(_validate_field "$part" "$lo" "$hi" "$base")"
            out="${out:+$out,}$item"
        done
        echo "$out"; return 0
    fi
    # 范围 a-b 或 a-b/N → a..b 或 a..b/N
    if [[ "$val" =~ ^([0-9]+)-([0-9]+)(/[0-9]+)?$ ]]; then
        a="${BASH_REMATCH[1]}"; b="${BASH_REMATCH[2]}"
        [ "$a" -ge "$lo" ] 2>/dev/null && [ "$a" -le "$hi" ] 2>/dev/null \
            || die "cron 值 '$val' 超出范围 [$lo,$hi]。"
        [ "$b" -ge "$lo" ] 2>/dev/null && [ "$b" -le "$hi" ] 2>/dev/null \
            || die "cron 值 '$val' 超出范围 [$lo,$hi]。"
        [ "$a" -le "$b" ] 2>/dev/null || die "cron 范围 '$val' 起始大于结束。"
        local rng
        rng="$(printf '%02d..%02d' "$a" "$b")"
        if [ -n "${BASH_REMATCH[3]:-}" ]; then
            n="${BASH_REMATCH[3]#/}"
            [ "$n" -ge 1 ] 2>/dev/null || die "cron 步长 '$val' 非法。"
            echo "${rng}/${n}"
        else
            echo "$rng"
        fi
        return 0
    fi
    # 单值 → 补零
    if [[ "$val" =~ ^[0-9]+$ ]]; then
        [ "$val" -ge "$lo" ] 2>/dev/null && [ "$val" -le "$hi" ] 2>/dev/null \
            || die "cron 值 '$val' 超出范围 [$lo,$hi]。"
        printf '%02d' "$val"; return 0
    fi
    die "cron 字段 '$val' 语法非法。"
}

# dow 字段特殊处理：数字映射为 Mon..Sun；范围/列表逐项映射
# 输出 OnCalendar 的星期片段（如 Mon..Fri、Sun,Sat）
_validate_dow() {
    local val="$1"
    case "$val" in
        *L*|*W*|*\#*) die "cron 字段 '$val' 含 L/W/# 扩展，systemd OnCalendar 不支持。";;
    esac
    if [ "$val" = "*" ]; then echo "*"; return 0; fi
    if [[ "$val" =~ ^\*/[0-9]+$ ]]; then
        local n="${val#*/}"
        [ "$n" -ge 1 ] 2>/dev/null || die "cron 步长 '$val' 非法。"
        # dow 步长在 OnCalendar 不常用且语义模糊，直接拒绝以避免误调度
        die "cron 星期字段不支持 '$val' 步长，请用列表或范围。"
    fi
    if [[ "$val" == *,* ]]; then
        local out=""
        local IFS=','
        for part in $val; do
            local name
            name="$(_dow_num_to_name "$part")" || die "cron 星期值 '$part' 非法（应为 0-7）。"
            out="${out:+$out,}$name"
        done
        echo "$out"; return 0
    fi
    if [[ "$val" =~ ^([0-9]+)-([0-9]+)$ ]]; then
        local a="${BASH_REMATCH[1]}" b="${BASH_REMATCH[2]}"
        local na nb
        na="$(_dow_num_to_name "$a")" || die "cron 星期值 '$a' 非法（应为 0-7）。"
        nb="$(_dow_num_to_name "$b")" || die "cron 星期值 '$b' 非法（应为 0-7）。"
        # 0-6 / 1-7 均按数值顺序映射；跨周（如 5-1）拒绝
        [ "$a" -le "$b" ] 2>/dev/null || die "cron 星期范围 '$val' 不支持跨周（请用列表）。"
        # OnCalendar 范围用 .. 而非 ~（星期字段特例）
        echo "$na..$nb"; return 0
    fi
    if [[ "$val" =~ ^[0-9]+$ ]]; then
        _dow_num_to_name "$val" || die "cron 星期值 '$val' 非法（应为 0-7）。"
        return 0
    fi
    die "cron 星期字段 '$val' 语法非法。"
}

# 主转换：$1 = cron 表达式
# stdout: 一行或多行 OnCalendar 值
cron_to_oncalendar() {
    local expr="$1"
    # 拒绝 @ 宏
    case "$expr" in
        @*) die "不支持 cron 宏 '$expr'，请用 5 字段表达式（如 '@daily' → '0 0 * * *'）。";;
    esac
    # 按空白拆 5 字段（禁用 glob，避免 * 被展开成文件名）
    local fields=()
    local IFS=$' \t\n'
    set -f
    # shellcheck disable=SC2206
    fields=($expr)
    set +f
    if [ "${#fields[@]}" -ne 5 ]; then
        die "cron 表达式需为 5 字段（min hr dom mon dow），当前 ${#fields[@]} 字段: '$expr'"
    fi
    local min hr dom mon dow
    min="${fields[0]}"; hr="${fields[1]}"; dom="${fields[2]}"; mon="${fields[3]}"; dow="${fields[4]}"

    local om oh odom omon odow
    om="$(_validate_field "$min" 0 59 0)"
    oh="$(_validate_field "$hr"  0 23 0)"
    odom="$(_validate_field "$dom" 1 31 1)"
    omon="$(_validate_field "$mon" 1 12 1)"
    odow="$(_validate_dow "$dow")"

    local time_part="${oh}:${om}:00"
    local date_part="${omon}-${odom}"
    local lines=()

    if [ "$dow" = "*" ]; then
        lines+=("*-${date_part} ${time_part}")
    elif [ "$dom" = "*" ]; then
        lines+=("${odow} *-${omon}-* ${time_part}")
    else
        # dom 与 dow 都指定 → cron OR 语义，拆两行
        lines+=("*-${date_part} ${time_part}")
        lines+=("${odow} *-${omon}-* ${time_part}")
    fi

    # 用 systemd-analyze 校验每一行；不可解析则报错，避免生成无效单元
    local line
    for line in "${lines[@]}"; do
        if ! systemd-analyze calendar "$line" >/dev/null 2>&1; then
            die "转换结果 '$line' 无法被 systemd 解析（cron '$expr' 可能含未支持语法）。"
        fi
    done
    printf '%s\n' "${lines[@]}"
}

# =========================================================================
# 单元文件生成
# =========================================================================

# 写 service 模板单元（幂等：已存在则跳过，除非 $1=force）
write_service_template() {
    local force="${1:-}"
    local unit="$SYSTEMD_DIR/${SERVICE_PREFIX}@.service"
    if [ -f "$unit" ] && [ "$force" != "force" ]; then
        log "service 模板已存在，跳过: $unit"
        return 0
    fi
    cat > "$unit" <<EOF
[Unit]
Description=grok-register CLI registration (%i)
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=${REPO_ROOT}
Environment=REGISTER_COUNT=1
Environment=PYTHONUNBUFFERED=1
ExecStart=${RUN_CLI} -n \${REGISTER_COUNT} -y
TimeoutStartSec=6h
# CLI 退出码 0/1/2 均视为正常完成（不触发 oneshot 重启），由 timer 下次触发
SuccessExitStatus=0 1 2

[Install]
WantedBy=multi-user.target
EOF
    chmod 644 "$unit"
    log "已写 service 模板: $unit"
}

# 写 timer 单元（每实例独立 OnCalendar，覆盖更新）
# $1=实例名 $2=OnCalendar（可能多行，以换行分隔）
write_timer_unit() {
    local inst="$1" oncal="$2"
    local unit="$SYSTEMD_DIR/${SERVICE_PREFIX}@${inst}.timer"
    local oncal_block="" line
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        oncal_block+="OnCalendar=${line}"$'\n'
    done <<< "$oncal"
    cat > "$unit" <<EOF
[Unit]
Description=grok-register schedule (${inst})

[Timer]
${oncal_block}Persistent=true
RandomizedDelaySec=300
Unit=${SERVICE_PREFIX}@${inst}.service

[Install]
WantedBy=timers.target
EOF
    chmod 644 "$unit"
    log "已写 timer: $unit"
}

# 写 per-instance override（REGISTER_COUNT）
# $1=实例名 $2=count
write_instance_override() {
    local inst="$1" count="$2"
    local dropin_dir="$SYSTEMD_DIR/${SERVICE_PREFIX}@${inst}.service.d"
    mkdir -p "$dropin_dir"
    cat > "$dropin_dir/instance.conf" <<EOF
[Service]
Environment=REGISTER_COUNT=${count}
EOF
    chmod 644 "$dropin_dir/instance.conf"
    log "已写实例配置: $dropin_dir/instance.conf (REGISTER_COUNT=$count)"
}

# =========================================================================
# 子命令
# =========================================================================

cmd_install() {
    local count="" cron_expr="" inst="default" force=""
    while [ $# -gt 0 ]; do
        case "$1" in
            -n|--count) count="${2:-}"; shift 2;;
            -c|--cron) cron_expr="${2:-}"; shift 2;;
            -i|--instance) inst="${2:-}"; shift 2;;
            --force) force="force"; shift;;
            *) die "install: 未知参数 '$1'";;
        esac
    done
    [ -n "$count" ] || die "install 需要 --count/-n（正整数）。"
    [[ "$count" =~ ^[0-9]+$ ]] || die "--count 需为正整数，得到 '$count'。"
    [ "$count" -ge 1 ] || die "--count 须 >= 1。"
    [ -n "$cron_expr" ] || die "install 需要 --cron/-c（5 字段 cron 表达式）。"
    valid_instance "$inst" || die "实例名 '$inst' 非法（仅允许字母数字 _ -）。"
    require_root
    require_systemd

    local oncal
    oncal="$(cron_to_oncalendar "$cron_expr")"
    log "cron '$cron_expr' → OnCalendar:"
    local l; while IFS= read -r l; do log "    $l"; done <<< "$oncal"

    write_service_template "$force"
    write_timer_unit "$inst" "$oncal"
    write_instance_override "$inst" "$count"

    systemctl daemon-reload
    systemctl enable --now "${SERVICE_PREFIX}@${inst}.timer"
    log "已启用并启动 timer: ${SERVICE_PREFIX}@${inst}.timer"
    log "查看状态: bash grok-timer.sh status -i $inst"
    log "立即触发一次: bash grok-timer.sh run-now -i $inst"
}

cmd_uninstall() {
    local inst="default"
    while [ $# -gt 0 ]; do
        case "$1" in
            -i|--instance) inst="${2:-}"; shift 2;;
            *) die "uninstall: 未知参数 '$1'";;
        esac
    done
    valid_instance "$inst" || die "实例名 '$inst' 非法。"

    local timer="${SERVICE_PREFIX}@${inst}.timer"
    local service="${SERVICE_PREFIX}@${inst}.service"
    log "卸载 $timer / $service ..."
    systemctl disable --now "$timer" 2>/dev/null || true
    systemctl stop "$service" 2>/dev/null || true
    rm -f "$SYSTEMD_DIR/${SERVICE_PREFIX}@${inst}.timer"
    rm -rf "$SYSTEMD_DIR/${SERVICE_PREFIX}@${inst}.service.d"
    # 若无任何实例 timer 残留，移除 service 模板
    if ! ls "$SYSTEMD_DIR"/${SERVICE_PREFIX}@*.timer >/dev/null 2>&1; then
        rm -f "$SYSTEMD_DIR/${SERVICE_PREFIX}@.service"
        log "无实例残留，已移除 service 模板。"
    fi
    systemctl daemon-reload
    systemctl reset-failed "${SERVICE_PREFIX}@${inst}.service" 2>/dev/null || true
    log "卸载完成。"
}

cmd_enable()  { local inst="default"; _parse_inst "$@"; systemctl enable  "${SERVICE_PREFIX}@${inst}.timer"; log "已 enable ${SERVICE_PREFIX}@${inst}.timer"; }
cmd_disable() { local inst="default"; _parse_inst "$@"; systemctl disable "${SERVICE_PREFIX}@${inst}.timer"; log "已 disable ${SERVICE_PREFIX}@${inst}.timer"; }
cmd_start()   { local inst="default"; _parse_inst "$@"; systemctl start   "${SERVICE_PREFIX}@${inst}.timer"; log "已启动调度 ${SERVICE_PREFIX}@${inst}.timer"; }
cmd_stop()    { local inst="default"; _parse_inst "$@"; systemctl stop    "${SERVICE_PREFIX}@${inst}.timer"; log "已停止调度 ${SERVICE_PREFIX}@${inst}.timer"; }

# 仅解析 --instance 的公共辅助
_parse_inst() {
    while [ $# -gt 0 ]; do
        case "$1" in
            -i|--instance) inst="${2:-}"; shift 2;;
            *) die "$SUBCMD: 未知参数 '$1'";;
        esac
    done
    valid_instance "$inst" || die "实例名 '$inst' 非法。"
}

cmd_status() {
    local inst="default"; _parse_inst "$@"
    echo "=== Timer ==="
    systemctl status "${SERVICE_PREFIX}@${inst}.timer" --no-pager || true
    echo
    echo "=== 下次触发 ==="
    systemctl list-timers "${SERVICE_PREFIX}@${inst}.timer" --no-pager --all || true
    echo
    echo "=== Service 最近一次 ==="
    systemctl status "${SERVICE_PREFIX}@${inst}.service" --no-pager || true
}

cmd_list() {
    log "已安装的 grok-register timer："
    systemctl list-unit-files "${SERVICE_PREFIX}@*.timer" --no-pager 2>/dev/null || true
    echo
    systemctl list-timers "${SERVICE_PREFIX}@*.timer" --no-pager --all 2>/dev/null || true
}

cmd_run_now() {
    local inst="default"; _parse_inst "$@"
    log "立即触发 ${SERVICE_PREFIX}@${inst}.service（不等调度）..."
    systemctl start "${SERVICE_PREFIX}@${inst}.service"
    log "已触发。查看日志: bash grok-timer.sh logs -i $inst"
}

cmd_logs() {
    local inst="default"; _parse_inst "$@"
    exec journalctl -u "${SERVICE_PREFIX}@${inst}.service" -u "${SERVICE_PREFIX}@${inst}.timer" -f
}

# 调试用：仅转换并打印 OnCalendar，不写单元
cmd_convert() {
    local expr="${1:-}"
    [ -n "$expr" ] || die "convert 需要 cron 表达式参数。"
    cron_to_oncalendar "$expr"
}

# =========================================================================
# 用法
# =========================================================================
usage() {
    cat <<'EOF'
grok-register 定时任务管理（systemd + timer）

用法:
  bash grok-timer.sh <子命令> [选项]

子命令:
  install    安装/更新一个定时注册任务（必填 -n / -c）
  uninstall  卸载任务（删 timer + 实例配置；无残留时删 service 模板）
  enable     开机自启（不立即运行）
  disable    关闭开机自启（不打断当前运行）
  start      启用调度（enable + 入队）
  stop       停用调度（不打断已运行的 service）
  status     查看 timer / 下次触发 / service 最近一次结果
  list       列出所有已安装的 grok-register timer
  run-now    立即触发一次 service（不等调度）
  logs       journalctl -f 跟随该实例日志
  convert    仅把 cron 表达式转成 OnCalendar 并打印（不写单元，调试用）

选项:
  -n, --count N        本次注册目标数量（install 必填，正整数）
  -c, --cron "EXPR"    5 字段 cron 表达式（install 必填，如 "0 */6 * * *"）
  -i, --instance NAME  实例名，默认 default；不同实例可独立 count/调度
  --force              install 时覆盖已存在的 service 模板
  -h, --help           显示本帮助

示例:
  bash grok-timer.sh install -n 5 -c "0 */6 * * *"
  bash grok-timer.sh install -n 2 -c "30 9 * * 1-5" -i morning
  bash grok-timer.sh status -i morning
  bash grok-timer.sh list
  bash grok-timer.sh run-now
  bash grok-timer.sh logs -i morning
  bash grok-timer.sh uninstall -i morning

cron 表达式（5 字段：分 时 日 月 周）支持:
  * / */N / N / a,b / a-b ；
  周字段 0/7=Sun..6=Sat；
  日与周同时指定时按 cron OR 语义拆为多条 OnCalendar。
  不支持 L/W/# 与 @ 宏（systemd OnCalendar 限制）。

单元文件位于 /etc/systemd/system/grok-register@*.{service,timer}。
日志: journalctl -u grok-register@<instance>。
EOF
}

# =========================================================================
# 入口
# =========================================================================
main() {
    local subcmd="${1:-}"
    [ $# -gt 0 ] && shift || true
    case "$subcmd" in
        ""|-h|--help|help) usage; exit 0;;
        install|convert) cmd_${subcmd} "$@";;
        uninstall|enable|disable|start|stop|status|list|run-now|logs)
            SUBCMD="$subcmd"
            # 写 /etc 需 root；list/status/logs 只读但 systemctl 仍建议 root
            if [ "$subcmd" != "list" ] && [ "$subcmd" != "status" ] && [ "$subcmd" != "logs" ]; then
                require_root
            fi
            require_systemd
            local fn="${subcmd//-/_}"
            cmd_${fn} "$@";;
        *) die "未知子命令 '$subcmd'，运行 --help 查看用法。";;
    esac
}

main "$@"
