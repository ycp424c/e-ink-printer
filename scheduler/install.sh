#!/usr/bin/env bash
# 安装 launchd LaunchAgent：工作日（周一至周五）9:00–19:00 每半小时整点
# （:00 与 :30）刷新墨水屏余额，其余日期/时段不刷新。
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$HERE/.." && pwd)"
PLIST_TEMPLATE="$HERE/com.eink.printer.refresh.plist"
DEST="$HOME/Library/LaunchAgents/com.eink.printer.refresh.plist"
PYTHON="$PROJECT_ROOT/.venv/bin/python"
REFRESH_SCRIPT="$PROJECT_ROOT/refresh.py"
LOG_PATH="$PROJECT_ROOT/logs/launchd.log"
UID_NUM="$(id -u)"
LOAD_AGENT=true

if [ "${1:-}" = "--no-load" ]; then
    LOAD_AGENT=false
    shift
fi
if [ "$#" -ne 0 ]; then
    echo "用法: $0 [--no-load]" >&2
    exit 2
fi

if [ ! -f "$PLIST_TEMPLATE" ]; then
    echo "缺少 $PLIST_TEMPLATE" >&2
    exit 1
fi
if [ ! -x "$PYTHON" ]; then
    echo "缺少虚拟环境 Python: $PYTHON" >&2
    echo "请先按 README 创建 .venv 并安装依赖。" >&2
    exit 1
fi
if [ ! -f "$REFRESH_SCRIPT" ]; then
    echo "缺少刷新脚本: $REFRESH_SCRIPT" >&2
    exit 1
fi

mkdir -p "$HOME/Library/LaunchAgents" "$PROJECT_ROOT/logs"
cp "$PLIST_TEMPLATE" "$DEST"
PROGRAM_ARGUMENTS_JSON="$(
    "$PYTHON" -c 'import json, sys; print(json.dumps(sys.argv[1:]))' "$PYTHON" "$REFRESH_SCRIPT"
)"
plutil -replace ProgramArguments -json "$PROGRAM_ARGUMENTS_JSON" "$DEST"
plutil -replace WorkingDirectory -string "$PROJECT_ROOT" "$DEST"
plutil -replace StandardOutPath -string "$LOG_PATH" "$DEST"
plutil -replace StandardErrorPath -string "$LOG_PATH" "$DEST"
plutil -lint "$DEST" >/dev/null

if [ "$LOAD_AGENT" = false ]; then
    echo "已生成但未加载 $DEST"
    exit 0
fi

# 卸载旧的（若存在），再加载新的
launchctl bootout "gui/$UID_NUM" "$DEST" 2>/dev/null || true
launchctl bootstrap "gui/$UID_NUM" "$DEST"

echo "已安装并加载 $DEST"
echo "立即触发一次：launchctl kickstart -k gui/$UID_NUM/com.eink.printer.refresh"
echo "查看日志：tail -f $PROJECT_ROOT/logs/refresh.log"
