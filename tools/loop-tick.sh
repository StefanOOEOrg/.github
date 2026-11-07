#!/usr/bin/env bash
# Tick of The Loop. No-agent cron in the sw-lead profile, fired by the Hermes webhook route `loop` on
# every relevant GitHub event, and once an hour as a safety net:
#
#   hermes cron create 60m --name loop-tick --script loop-tick.sh --no-agent \
#     --deliver bot-chat:sw-lead --failure-deliver local
#
# The route filters the GitHub events itself (declarative `filters` in webhook_subscriptions.json:
# our org, relevant actions, no echo of the Lead bot, no fork PR) and, with `cron_job_on_busy:
# coalesce` (local Hermes patch), fires this job once more if an event came in while it ran.
#
# One tick = dispatcher, then watch (Lead inbox, new issues on Triage, assignee sync). Both read the
# whole state, so a lost or doubled event does no harm. Both hold their own lock, so a tick and the old
# crons running in parallel never start a card or comment twice.
#
# stdout is the delivery payload: only the watch's Lead messages; the dispatcher logs locally.
set -uo pipefail

PROFILE_DIR="${HERMES_HOME:-$HOME/.hermes/profiles/sw-lead}"
SCRIPTS="$PROFILE_DIR/scripts"
CACHE="$PROFILE_DIR/cache"
mkdir -p "$CACHE"

if ! bash "$SCRIPTS/dev-dispatch.sh" >> "$CACHE/dispatch-tick.log" 2>&1; then
  echo "Tick: Dispatcher fehlgeschlagen, siehe cache/dispatch-tick.log"
fi
bash "$SCRIPTS/github-watch.sh" || echo "Tick: Watch fehlgeschlagen"
