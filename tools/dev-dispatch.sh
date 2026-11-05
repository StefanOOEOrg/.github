#!/usr/bin/env bash
# Dev dispatcher. Runs as a no-agent cron in the sw-lead profile:
#
#   hermes cron create 3m --name dev-dispatch --script dev-dispatch.sh --no-agent \
#     --deliver local --failure-deliver local
#
# Pull flow: the product owner moves a card to Goal, the order in that column is the priority.
# Per free instance (no open Action card on it) the first startable Goal card goes to Action: instance
# and Developer are set, a worktree is prepared and a one-shot developer job starts.
# A card that cannot start stays on Goal: an open blocker or a missing Branch / Allowed files line gets
# one comment with the reason (the assignee sync then puts it in the right inbox); a card whose files
# overlap an Action card waits silently for its turn.
# Action -> Verify is done by the project workflow when the PR is linked.
#
# stdout is the delivery payload (local log); empty = nothing dispatched.
# Needs: gh authenticated as StefanOOELeadBot with project read/write on the org.
set -euo pipefail

ORG="${GH_ORG:-StefanOOEOrg}"
PROJECT="${GH_PROJECT_NUMBER:?set GH_PROJECT_NUMBER in profiles/sw-lead/.env}"
INSTANCES="${DEV_INSTANCES:-dev-1}"
DEV_LOGIN="${DEV_LOGIN:-StefanOOEDevBot}"
OWNER_LOGIN="${OWNER_LOGIN:-StefanOOE}"
WS_ROOT="${WS_ROOT:-/home/hermes/workspaces}"
PROFILE_DIR="${HERMES_HOME:-$HOME/.hermes/profiles/sw-lead}"
mkdir -p "$PROFILE_DIR/cache"

python3 - "$ORG" "$PROJECT" "$INSTANCES" "$DEV_LOGIN" "$OWNER_LOGIN" "$WS_ROOT" "$PROFILE_DIR/cache" <<'PY'
import fnmatch, json, os, re, subprocess, sys, time
from pathlib import Path

org, project, instances, dev_login, owner, ws_root, cache = sys.argv[1:8]
DRY_RUN = os.environ.get("DISPATCH_DRY_RUN") == "1"

GH_TIMEOUT = 60  # seconds per gh call; a hung call must not block the cron run
GH_ATTEMPTS = 3  # GitHub answers 502/504 on project queries now and then; retry them
GH_BACKOFF = (2, 5)  # seconds before the second and third attempt

# Only what a dispatch needs: this runs 20 times an hour, so it must stay cheap (#44).
ITEMS_QUERY = """query($org: String!, $num: Int!, $after: String) { organization(login: $org) { projectV2(number: $num) {
  id items(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes { id
    status: fieldValueByName(name: "Status") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    instance: fieldValueByName(name: "Instance") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    content { ... on Issue { url number title state body issueType { name } repository { nameWithOwner }
      assignees(first: 3) { nodes { login } } blockedBy(first: 5) { nodes { number state } }
      closedByPullRequestsReferences(first: 1, includeClosedPrs: false) { nodes { number } } } } } } } } }"""
FIELDS_QUERY = """query($org: String!, $num: Int!) { organization(login: $org) { projectV2(number: $num) {
  fields(first: 30) { nodes { ... on ProjectV2SingleSelectField { id name options { id name } } } } } } }"""


def gh(*args):
    """Run a gh call, retrying the transient gateway failures; an exhausted budget ends the run.

    Every call here is either a read or an idempotent field write, so repeating it
    after a 502/504 is safe; without the retry one bad second skips a whole dispatch.
    """
    last = None
    for attempt in range(GH_ATTEMPTS):
        try:
            return subprocess.run(["gh", *args], check=True, capture_output=True, text=True,
                                  timeout=GH_TIMEOUT).stdout
        except subprocess.TimeoutExpired as error:
            last = error
        except subprocess.CalledProcessError as error:
            if "rate limit" in (error.stderr or "").lower() or "RATE_LIMITED" in (error.stdout or ""):
                sys.exit(0)  # the watch reports the budget; the next run starts the card
            last = error
        if attempt < len(GH_BACKOFF):
            time.sleep(GH_BACKOFF[attempt])
    raise last


def project_items():
    """Return the project id and all issue items in project order."""
    items, after, pid = [], None, None
    while True:
        args = ["api", "graphql", "-f", f"query={ITEMS_QUERY}", "-f", f"org={org}", "-F", f"num={project}"]
        board = json.loads(gh(*args + (["-f", f"after={after}"] if after else [])))
        board = board["data"]["organization"]["projectV2"]
        pid = board["id"]
        items += [n for n in board["items"]["nodes"] if (n.get("content") or {}).get("number")]
        if not board["items"]["pageInfo"]["hasNextPage"]:
            return pid, items
        after = board["items"]["pageInfo"]["endCursor"]


def status_of(item):
    return (item.get("status") or {}).get("name")


def allowed_files(body):
    """Return the paths of the task's `Allowed files` line."""
    line = re.search(r"Allowed files:(.*)", body or "")
    return re.findall(r"`([^`]+)`", line.group(1)) if line else []


def overlaps(first, second):
    """True if two lists of paths or globs can touch the same file."""
    return any(a == b or fnmatch.fnmatch(a, b) or fnmatch.fnmatch(b, a) for a in first for b in second)


def field_ids():
    """Return the single-select fields of the project by name."""
    data = json.loads(gh("api", "graphql", "-f", f"query={FIELDS_QUERY}", "-f", f"org={org}", "-F", f"num={project}"))
    nodes = data["data"]["organization"]["projectV2"]["fields"]["nodes"]
    return {f["name"]: f for f in nodes if f.get("name")}


def set_field(pid, item, field, value):
    """Set one single-select field of a project item."""
    option = next(o["id"] for o in field["options"] if o["name"] == value)
    gh("project", "item-edit", "--project-id", pid, "--id", item["id"], "--field-id", field["id"],
       "--single-select-option-id", option)


def start(pid, item, inst, fields):
    """Move one card to Action on an instance and start the one-shot developer job."""
    c = item["content"]
    repo_full, repo = c["repository"]["nameWithOwner"], c["repository"]["nameWithOwner"].split("/")[-1]
    m = re.search(r"Branch:\s*`([^`]+)`(?:\s*\(base:\s*`([^`]+)`\))?", c["body"] or "")
    branch, base = m.group(1), (m.group(2) or "main")
    if DRY_RUN:
        print(f"{inst}: would start {repo_full}#{c['number']} ({branch})")
        return
    ws = f"{ws_root}/{repo}"
    wt = f"{ws}/.worktrees/{inst}"
    subprocess.run(["git", "-C", ws, "fetch", "-q", "upstream"], check=True)
    exists = subprocess.run(["git", "-C", ws, "rev-parse", "-q", "--verify", f"upstream/{branch}"],
                            capture_output=True).returncode == 0
    origin = f"upstream/{branch}" if exists else (base if base.startswith("upstream/") else f"upstream/{base}")
    subprocess.run(["git", "-C", ws, "worktree", "remove", "--force", wt], capture_output=True)
    subprocess.run(["git", "-C", ws, "worktree", "add", "-q", "-B", branch, wt, origin], check=True)
    set_field(pid, item, fields["Instance"], inst)
    set_field(pid, item, fields["Status"], "Action")
    gh("api", "-X", "POST", f"repos/{repo_full}/issues/{c['number']}/assignees", "-f", f"assignees[]={dev_login}")
    rnd = "2+" if exists else "1"
    prompt = (f"Implement task {c['url']} (repo {repo_full}, instance {inst}, round {rnd}). "
              f"Work only in {wt} on branch {branch}. Follow skill sw-developer-workflow; the issue body is the order.")
    subprocess.run(["hermes", "-p", "sw-developer", "cron", "create", "1m", prompt, "--repeat", "1",
                    "--name", f"{inst}-{repo}-{c['number']}", "--skill", "sw-developer-workflow",
                    "--workdir", wt, "--deliver", "bot-chat:sw-lead", "--failure-deliver", "bot-chat:sw-lead"],
                   check=True)
    print(f"{inst}: gestartet {repo_full}#{c['number']} ({branch}, Runde {rnd})")


def report(item, reason, seen, reported):
    """Comment once on a card that cannot start; the reason stays until it is gone."""
    c = item["content"]
    key = f"{c['url']}|{reason}"
    seen[key] = True
    if key in reported:
        return
    print(f"nicht gestartet: {c['repository']['nameWithOwner']}#{c['number']}: {reason}")
    if not DRY_RUN:
        gh("api", f"repos/{c['repository']['nameWithOwner']}/issues/{c['number']}/comments",
           "-f", f"body=Not started: {reason}. It stays on Goal and starts as soon as this is resolved.")


def main():
    state_path = Path(cache) / "dispatch-reported.json"
    try:
        reported = json.loads(state_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        reported = {}
    pid, items = project_items()
    open_items = [i for i in items if i["content"]["state"] == "OPEN"]
    active = [i for i in open_items if status_of(i) == "Action"]
    busy = {(i.get("instance") or {}).get("name") for i in active}
    free = [inst for inst in instances.split() if inst not in busy]
    running = [(i["content"]["repository"]["nameWithOwner"], allowed_files(i["content"]["body"])) for i in active]
    seen, fields = {}, None
    for item in (i for i in open_items if status_of(i) == "Goal"):
        c = item["content"]
        if (c.get("issueType") or {}).get("name") == "Feature":
            report(item, "a feature is never started, pull its tasks", seen, reported)
            continue
        held = owner in {a["login"] for a in c["assignees"]["nodes"]}
        if held and c["closedByPullRequestsReferences"]["nodes"]:
            continue  # the round limit reached: the product owner decides
        blockers = [f"#{b['number']}" for b in c["blockedBy"]["nodes"] if b["state"] == "OPEN"]
        if blockers:
            report(item, f"blocked by {', '.join(blockers)}", seen, reported)
            continue
        files = allowed_files(c["body"])
        if not re.search(r"Branch:\s*`[^`]+`", c["body"] or "") or not files:
            report(item, "the task has no `Branch:` or no `Allowed files` line", seen, reported)
            continue
        repo = c["repository"]["nameWithOwner"]
        if not free or any(r == repo and overlaps(files, other) for r, other in running):
            continue
        current = (item.get("instance") or {}).get("name")
        inst = current if current in free else free[0]
        fields = fields or field_ids()
        start(pid, item, inst, fields)
        free.remove(inst)
        running.append((repo, files))
    if not DRY_RUN:
        state_path.write_text(json.dumps(seen, sort_keys=True))


main()
PY
