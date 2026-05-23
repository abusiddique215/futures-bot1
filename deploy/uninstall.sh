#!/usr/bin/env bash
# deploy/uninstall.sh — remove the topstep-bot LaunchAgents.
#
# Bootouts each agent under the user's gui domain (no-op if not loaded),
# then deletes the .plist files. Logs are NOT deleted.
set -euo pipefail

UID_NUM="$(id -u)"
LAUNCH_DIR="$HOME/Library/LaunchAgents"

for tpl in com.user.topstepbot.plist com.user.topstepbot-heartbeat.plist; do
    label="${tpl%.plist}"
    plist="$LAUNCH_DIR/$tpl"

    echo "Unloading $label"
    launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true

    if [[ -f "$plist" ]]; then
        rm -f "$plist"
        echo "Removed $plist"
    else
        echo "Skipped (not present): $plist"
    fi
done

echo "Uninstalled. Logs under deploy/logs/ retained."
