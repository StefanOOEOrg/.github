#!/usr/bin/env bash
# Job watch of The Loop: a full engine run once a developer job has ended, and the retry of a failed
# run (cache/loop-retry.json, at most every 3 min; tools/loop/jobwatch.py, retry.py).
# No-agent cron in the sw-lead profile, every minute; silent unless a job ended or a retry is due:
#
#   hermes cron create 1m --name loop-jobwatch --script loop-jobwatch.sh --no-agent \
#     --deliver bot-chat:sw-lead --failure-deliver local
#
# stdout is the delivery to the Lead (the lines of the engine run); the log goes to cache/loop.log.
set -uo pipefail

PROFILE_DIR="${HERMES_HOME:-$HOME/.hermes/profiles/sw-lead}"
mkdir -p "$PROFILE_DIR/cache"
cd "$PROFILE_DIR/scripts" || exit 1
python3 -m loop jobwatch 2>> "$PROFILE_DIR/cache/loop.log"
