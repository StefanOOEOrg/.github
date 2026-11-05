#!/usr/bin/env bash
# Dev dispatcher (replaces Hermes Kanban dispatch). Runs as a no-agent cron in the sw-lead profile:
#
#   hermes cron create 3m --name dev-dispatch --script dev-dispatch.sh --no-agent \
#     --deliver local --failure-deliver local
#
# For every instance in DEV_INSTANCES it looks at the org project:
#   - instance busy  = an item with Instance=<inst> and Status="In Progress"  -> skip
#   - otherwise pick the first item with Instance=<inst>, Status="Ready", assignee StefanOOEDevBot
#     (project order = priority), set it to "In Progress", prepare a worktree and start a one-shot
#     developer job (the same mechanism as the old cron fallback, references/developer-handover.md).
# "In Progress" -> "In Review" is done by the project workflow when the PR is linked; an item that
# stays "In Progress" without a PR is reported by github-watch.sh as stale.
#
# stdout is the delivery payload (local log); empty = nothing dispatched.
# Needs: gh authenticated as StefanOOELeadBot with project read/write on the org.
set -euo pipefail

ORG="${GH_ORG:-StefanOOEOrg}"
PROJECT="${GH_PROJECT_NUMBER:?set GH_PROJECT_NUMBER in profiles/sw-lead/.env}"
INSTANCES="${DEV_INSTANCES:-dev-1}"
DEV_LOGIN="${DEV_LOGIN:-StefanOOEDevBot}"
WS_ROOT="${WS_ROOT:-/home/hermes/workspaces}"

python3 - "$ORG" "$PROJECT" "$INSTANCES" "$DEV_LOGIN" "$WS_ROOT" <<'PY'
import json, re, subprocess, sys, time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

org, project, instances, dev_login, ws_root = sys.argv[1:6]

GH_TIMEOUT = 60  # seconds per gh call; a hung call must not block the cron run
GH_ATTEMPTS = 3  # GitHub answers 502/504 on project queries now and then; retry them
GH_BACKOFF = (2, 5)  # seconds before the second and third attempt


def gh(*args):
    """Run a gh call, retrying the transient gateway failures.

    Every call here is either a read or an idempotent field write, so repeating it
    after a 502/504 is safe; without the retry one bad second skips a whole dispatch.
    """
    last = None
    for attempt in range(GH_ATTEMPTS):
        try:
            return subprocess.run(["gh", *args], check=True, capture_output=True, text=True,
                                  timeout=GH_TIMEOUT).stdout
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            last = error
            if attempt < len(GH_BACKOFF):
                time.sleep(GH_BACKOFF[attempt])
    raise last

items = json.loads(gh("project", "item-list", project, "--owner", org, "--format", "json", "-L", "1000"))["items"]
pid = json.loads(gh("project", "view", project, "--owner", org, "--format", "json"))["id"]
fields = {f["name"]: f for f in json.loads(gh("project", "field-list", project, "--owner", org, "--format", "json"))["fields"]}
status_field = fields["Status"]
option = {o["name"]: o["id"] for o in status_field.get("options", [])}

def is_dev(item):
    return dev_login in (item.get("assignees") or [])


TODAY = datetime.now(ZoneInfo("Europe/Vienna")).date()


def in_current_iteration(item):
    """Only tasks the product owner pulled into the running sprint may start."""
    it = item.get("iteration") or {}
    if not it.get("startDate"):
        return False
    start = datetime.fromisoformat(it["startDate"]).date()
    return start <= TODAY < start + timedelta(days=it["duration"])

for inst in instances.split():
    mine = [i for i in items if (i.get("instance") or "") == inst and i.get("content", {}).get("type") == "Issue"]
    if any(i.get("status") == "In Progress" for i in mine):
        continue
    ready = [i for i in mine if i.get("status") == "Ready" and is_dev(i) and in_current_iteration(i)]
    if not ready:
        continue
    item = ready[0]
    c = item["content"]
    repo = c["repository"].split("/")[-1]
    issue = json.loads(gh("issue", "view", str(c["number"]), "-R", c["repository"], "--json", "body,url,title"))
    m = re.search(r"Branch:\s*`([^`]+)`(?:\s*\(base:\s*`([^`]+)`\))?", issue["body"] or "")
    if not m:
        print(f"{inst}: {c['repository']}#{c['number']} hat keine Zeile 'Branch: `...`' — nicht gestartet")
        continue
    branch, base = m.group(1), (m.group(2) or "main")
    ws = f"{ws_root}/{repo}"
    wt = f"{ws}/.worktrees/{inst}"
    subprocess.run(["git", "-C", ws, "fetch", "-q", "upstream"], check=True)
    exists = subprocess.run(["git", "-C", ws, "rev-parse", "-q", "--verify", f"upstream/{branch}"],
                            capture_output=True).returncode == 0
    start = f"upstream/{branch}" if exists else (base if base.startswith("upstream/") else f"upstream/{base}")
    subprocess.run(["git", "-C", ws, "worktree", "remove", "--force", wt], capture_output=True)
    subprocess.run(["git", "-C", ws, "worktree", "add", "-q", "-B", branch, wt, start], check=True)
    gh("project", "item-edit", "--project-id", pid, "--id", item["id"],
       "--field-id", status_field["id"], "--single-select-option-id", option["In Progress"])
    rnd = "2+" if exists else "1"
    prompt = (f"Implement task {issue['url']} (repo {c['repository']}, instance {inst}, round {rnd}). "
              f"Work only in {wt} on branch {branch}. Follow skill sw-developer-workflow; the issue body is the order.")
    subprocess.run(["hermes", "-p", "sw-developer", "cron", "create", "1m", prompt, "--repeat", "1",
                    "--name", f"{inst}-{repo}-{c['number']}", "--skill", "sw-developer-workflow",
                    "--workdir", wt, "--deliver", "bot-chat:sw-lead", "--failure-deliver", "bot-chat:sw-lead"],
                   check=True)
    print(f"{inst}: gestartet {c['repository']}#{c['number']} ({branch}, Runde {rnd})")
PY
