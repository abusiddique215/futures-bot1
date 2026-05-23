#!/usr/bin/env bash
# deploy/install.sh — install the topstep-bot LaunchAgents.
#
# What it does:
#   1. Refuses to run from an iCloud-tree (Mobile Documents) project dir.
#   2. Substitutes __PROJECT_DIR__ in both .plist templates with the
#      resolved absolute project root.
#   3. Copies the rendered .plist files into ~/Library/LaunchAgents/.
#   4. `launchctl bootstrap` loads them under the user's gui domain.
#
# Run as the user who will own the bot (NOT sudo).
set -euo pipefail

# Resolve project dir. realpath isn't on macOS by default; use python.
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "$PROJECT_DIR" == *"Mobile Documents"* ]]; then
    echo "ERROR: project is under iCloud Drive ('Mobile Documents'). SQLite WAL"
    echo "       is unsafe here and LaunchAgents may not exist on disk when"
    echo "       launchd loads them. Move the tree to local disk first."
    echo "       See: https://help.topstep.com/en/articles/8680268-can-i-use-a-vpn"
    exit 1
fi

UID_NUM="$(id -u)"
LAUNCH_DIR="$HOME/Library/LaunchAgents"
mkdir -p "$LAUNCH_DIR"
mkdir -p "$PROJECT_DIR/deploy/logs"

for tpl in com.user.topstepbot.plist com.user.topstepbot-heartbeat.plist; do
    src="$PROJECT_DIR/deploy/$tpl"
    dst="$LAUNCH_DIR/$tpl"
    echo "Rendering $tpl → $dst"
    sed "s|__PROJECT_DIR__|$PROJECT_DIR|g" "$src" > "$dst"

    # plutil -lint validates well-formedness before launchctl loads it.
    plutil -lint "$dst"

    label="${tpl%.plist}"
    # `launchctl bootstrap` is idempotent only if the agent isn't loaded;
    # bootout first (ignoring errors when not loaded), then bootstrap.
    launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
    launchctl bootstrap "gui/$UID_NUM" "$dst"
    echo "Loaded $label"
done

echo
echo "Installed. Tail logs with:"
echo "  tail -f $PROJECT_DIR/deploy/logs/topstepbot.out.log"
echo "  tail -f $PROJECT_DIR/deploy/logs/heartbeat.out.log"
