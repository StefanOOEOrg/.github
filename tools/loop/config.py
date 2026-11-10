"""Configuration of the loop engine: every tunable value in one place.

Values come from the environment (Hermes loads the profile's .env for its cron jobs) with the
defaults of the current process. Nothing here is a secret: the GitHub token stays in gh's own
config (GH_CONFIG_DIR).
"""

from __future__ import annotations

import os

# === GITHUB ===
ORG = os.getenv("GH_ORG", "StefanOOEOrg")
PROJECT_NUMBER = int(os.getenv("GH_PROJECT_NUMBER", "1"))
# one gh call; a hung call must not block the run
GH_TIMEOUT_SECONDS = int(os.getenv("GH_TIMEOUT_SECONDS", "60"))
GH_ATTEMPTS = 3  # GitHub answers 502/504 on project queries now and then
GH_BACKOFF_SECONDS = (2, 5)  # before the second and the third attempt

# === ROLES (logins) ===
LEAD = os.getenv("LEAD_LOGIN", "StefanOOELeadBot")
DEV = os.getenv("DEV_LOGIN", "StefanOOEDevBot")
OWNER = os.getenv("OWNER_LOGIN", "StefanOOE")

# === BOARD ===
STATUSES = ("Triage", "Backlog", "Goal", "Action", "Verify", "Done")
# set by hand; the engine moves a card into Goal only for the next round after a change request
# (#81) and back after a failed start
OWNER_ONLY_STATUSES = ("Backlog", "Goal")
INSTANCES = tuple(os.getenv("DEV_INSTANCES", "dev-1").split())  # built for n, run with one
# maintained directly: no board card, no Closes line, the Lead reviews after the merge
OUTER_LOOP_REPO = ".github"

# === RULE THRESHOLDS ===
ROUND_LIMIT = 3  # Lead change requests on one PR before the product owner decides (A3)
MAX_BLOCKER_CHAIN = 5  # enough for real chains, and it ends a dependency cycle (P3)
STUCK_MINUTES = 15  # Action without PR and without a developer job (D2)
OWNER_WAIT_HOURS = 2  # approve reminder: first after (W6)
OWNER_REPEAT_HOURS = 24  # approve reminder: then at most every (W6)
REMIND_MINUTES = 60  # an open Lead notice is repeated after this long
ARCHIVE_DAYS = 14  # Done and closed this long: archive the item

# === RETRY OF A FAILED RUN (retry.py, carried out by the job watch) ===
RETRY_MINUTES = int(os.getenv("LOOP_RETRY_MINUTES", "3"))  # at most one retry this often
RETRY_REPORT_MINUTES = int(os.getenv("LOOP_RETRY_REPORT_MINUTES", "30"))  # then tell the Lead

# === PROPOSALS (off until decided) ===
# Verify -> Action when the linked PR was closed without a merge (design doc: proposal, not in use).
VERIFY_BACK_TO_ACTION = os.getenv("LOOP_VERIFY_BACK_TO_ACTION") == "1"

# === PATHS (TC) ===
PROFILE_DIR = os.getenv("HERMES_HOME", os.path.expanduser("~/.hermes/profiles/sw-lead"))
CACHE_DIR = os.path.join(PROFILE_DIR, "cache")
DEV_JOBS = os.getenv("DEV_JOBS", os.path.join(os.path.dirname(PROFILE_DIR), "sw-developer", "cron",
                                              "jobs.json"))
# one git clone per repository, the worktrees inside
WS_ROOT = os.getenv("WS_ROOT", "/home/hermes/workspaces")
DEV_PROFILE = "sw-developer"
DEV_SKILL = "sw-developer-workflow"
LOCK_WAIT_SECONDS = 600  # a second run waits for the first, then gives up quietly

# === WEBHOOK LISTENER (listener.py, dispatcher.py; `python3 -m loop listen`) ===
# The secret is read at start from LOOP_WEBHOOK_SECRET or the file LOOP_WEBHOOK_SECRET_FILE.
LISTEN_HOST = os.getenv("LOOP_LISTEN_HOST", "127.0.0.1")  # Tailscale Funnel proxies to it
LISTEN_PORT = int(os.getenv("LOOP_LISTEN_PORT", "8655"))
LISTEN_PATH = os.getenv("LOOP_LISTEN_PATH", "")  # "": every path (the HMAC check guards it)
MAX_BODY_BYTES = 10 * 1024 * 1024  # GitHub caps a payload at 25 MB; ours are a few KB
DEDUPE_DELIVERIES = 5000  # X-GitHub-Delivery IDs remembered against redeliveries
BACKOFF_FIRST_SECONDS = 5  # a failed run: the next try after this, doubled up to
BACKOFF_MAX_SECONDS = int(os.getenv("LOOP_BACKOFF_MAX_SECONDS", "300"))
# a full run on the clock: the time rules (D2 stuck, W6 reminders, repeats, archive) need one even
# without events, and it catches a webhook GitHub failed to deliver; 0 switches it off
FULL_RUN_MINUTES = int(os.getenv("LOOP_FULL_RUN_MINUTES", "60"))
SHUTDOWN_SECONDS = 90  # SIGTERM: time for the last run and the open deliveries

# === DELIVERY TO THE LEAD (delivery.py, outbox.py) ===
# Listener side: a command that takes one message on stdin; exit 0 means accepted.
DELIVER_CMD = os.getenv("LOOP_DELIVER_CMD", "python3 -m loop deliver")
DELIVER_TIMEOUT_SECONDS = 60
# Default command: spool into cache/outbox, then fire the no-agent cron `loop-deliver`
# (--deliver bot-chat:sw-lead), whose script prints and removes the spool.
OUTBOX_TRIGGER = os.getenv("LOOP_OUTBOX_TRIGGER", "hermes -p sw-lead cron run loop-deliver")

# === SIGNAL SOURCES AND OUTPUT SINKS (ports.py; wiring.py picks them, the names are its registry)
# `listen`: comma-separated signal sources, all feeding the one serial queue
# (webhook | timer | jobwatch | hermes-cron); the default is the listener as it was built
SOURCES = os.getenv("LOOP_SOURCES", "webhook,timer")
# `listen`: output, behind the delivery thread (command | hermes-outbox | stdout | file);
# command = LOOP_DELIVER_CMD, whose default is the outbox + loop-deliver path
SINK = os.getenv("LOOP_SINK", "command")
# `tick`, `jobwatch` (Hermes cron runs): output; stdout is what Hermes delivers to the Lead
TICK_SINK = os.getenv("LOOP_TICK_SINK", "stdout")
JOBWATCH_SECONDS = int(os.getenv("LOOP_JOBWATCH_SECONDS", "60"))  # source jobwatch: one look per
FILE_SINK = os.getenv("LOOP_FILE_SINK", os.path.join(CACHE_DIR, "loop-out.txt"))  # sink file
