#!/usr/bin/env bash
# Delivery of the webhook listener's notices to the Lead (tools/loop/outbox.py).
# The listener spools every message into cache/outbox and fires this no-agent cron of the sw-lead
# profile with `hermes -p sw-lead cron run <id>` (LOOP_OUTBOX_TRIGGER); the script prints the spool
# in order and empties it, Hermes delivers the output to Bot Chat (async pending lane):
#
#   hermes -p sw-lead cron create 60m --name loop-deliver --script loop-deliver.sh --no-agent \
#     --deliver bot-chat:sw-lead --failure-deliver local
#
# The 60-minute schedule only reads the local spool (no GitHub call): a safety net in case a trigger
# was refused. Empty spool, empty stdout: Hermes stays silent.
set -uo pipefail

PROFILE_DIR="${HERMES_HOME:-$HOME/.hermes/profiles/sw-lead}"
mkdir -p "$PROFILE_DIR/cache"
cd "$PROFILE_DIR/scripts" || exit 1
python3 -m loop outbox 2>> "$PROFILE_DIR/cache/loop.log"
