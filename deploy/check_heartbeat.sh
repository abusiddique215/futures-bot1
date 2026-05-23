#!/usr/bin/env bash
# deploy/check_heartbeat.sh — verify the bot is alive.
#
# Reads the heartbeat file (updated every 30s by the event loop). If the
# file is older than $STALE_AFTER_S seconds, emits a CRITICAL line to
# stderr (LaunchAgent captures it into heartbeat.err.log) and exits 1.
# Otherwise exits 0.
#
# A second-tier monitor (e.g. external uptime check, Telegram polling) can
# surface the err.log to the operator.
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HEARTBEAT="${HEARTBEAT_FILE:-$PROJECT_DIR/deploy/heartbeat.txt}"
STALE_AFTER_S="${STALE_AFTER_S:-120}"

if [[ ! -f "$HEARTBEAT" ]]; then
    echo "CRITICAL: heartbeat file missing: $HEARTBEAT" 1>&2
    exit 1
fi

# Use `stat` flavor that works on macOS (BSD stat).
LAST_MOD=$(stat -f %m "$HEARTBEAT")
NOW=$(date +%s)
AGE=$(( NOW - LAST_MOD ))

if (( AGE > STALE_AFTER_S )); then
    echo "CRITICAL: heartbeat stale: ${AGE}s > ${STALE_AFTER_S}s (file=$HEARTBEAT)" 1>&2
    exit 1
fi

echo "OK: heartbeat age ${AGE}s (threshold ${STALE_AFTER_S}s)"
exit 0
