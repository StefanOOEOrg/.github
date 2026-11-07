#!/usr/bin/env bash
# Tick of The Loop. No-agent cron in the sw-lead profile, fired by the webhook route `loop`
# (loop_filter.py) on every relevant GitHub event, and once an hour as a safety net:
#
#   hermes cron create 60m --name loop-tick --script loop-tick.sh --no-agent \
#     --deliver bot-chat:sw-lead --failure-deliver local
#
# One tick = dispatcher, then watch (Lead inbox, new issues on Triage, assignee sync). Both read the
# whole state again, so a lost or doubled event does no harm. Both hold their own lock, so a tick and
# the old crons running in parallel never start a card or comment twice.
# Hermes drops a trigger while the tick runs; the filter therefore stamps cache/tick-requested and
# the tick runs again (at most MAX_ROUNDS) if a stamp is newer than its start.
#
# stdout is the delivery payload: only the watch's Lead messages; the dispatcher logs locally.
set -uo pipefail

PROFILE_DIR="${HERMES_HOME:-$HOME/.hermes/profiles/sw-lead}"
SCRIPTS="$PROFILE_DIR/scripts"
CACHE="$PROFILE_DIR/cache"
MAX_ROUNDS=3
mkdir -p "$CACHE"

for round in $(seq 1 "$MAX_ROUNDS"); do
  start=$(date +%s)
  if ! bash "$SCRIPTS/dev-dispatch.sh" >> "$CACHE/dispatch-tick.log" 2>&1; then
    echo "Tick: Dispatcher fehlgeschlagen, siehe cache/dispatch-tick.log"
  fi
  bash "$SCRIPTS/github-watch.sh" || echo "Tick: Watch fehlgeschlagen"
  requested=$(cat "$CACHE/tick-requested" 2>/dev/null || echo 0)
  if [ "${requested:-0}" -lt "$start" ]; then
    break
  fi
  echo "$(date -Is) Tick-Runde $((round + 1)): Ereignis während Runde $round" >> "$CACHE/dispatch-tick.log"
done
