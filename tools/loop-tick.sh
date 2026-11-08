#!/usr/bin/env bash
# Tick of The Loop: one run of the loop engine (tools/loop, design "Loop-Engine: Neudesign").
# No-agent cron in the sw-lead profile, fired by the Hermes webhook route `loop` on every relevant
# GitHub event (with the event in HERMES_CRON_EVENT, Hermes patch A), and once an hour as the full
# reconciliation:
#
#   hermes cron create 60m --name loop-tick --script loop-tick.sh --no-agent \
#     --deliver bot-chat:sw-lead --failure-deliver local
#
# stdout is the delivery to the Lead; the engine's log goes to cache/loop.log.
# The old scripts (dev-dispatch.sh, github-watch.sh, assignee_sync.py) stay in the repository as
# the way back until the engine has proved itself.
set -uo pipefail

PROFILE_DIR="${HERMES_HOME:-$HOME/.hermes/profiles/sw-lead}"
mkdir -p "$PROFILE_DIR/cache"
cd "$PROFILE_DIR/scripts" || exit 1
python3 -m loop tick 2>> "$PROFILE_DIR/cache/loop.log"
