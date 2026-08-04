#!/usr/bin/env bash
# 卸载 launchd LaunchAgent。
set -euo pipefail

DEST="$HOME/Library/LaunchAgents/com.eink.printer.refresh.plist"
UID_NUM="$(id -u)"

launchctl bootout "gui/$UID_NUM" "$DEST" 2>/dev/null || true
rm -f "$DEST"
echo "已卸载 com.eink.printer.refresh"
