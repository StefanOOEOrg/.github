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
# overlap an Action card waits silently for its turn. A card starts only if both bots can write to its
# repository, and it reaches Action only together with its developer job: a failed start puts it back
# on Goal with a comment (#57). An Action card without a PR and without a scheduled developer job for
# IDLE_MINUTES is reported once and handed to the product owner; it no longer holds its instance.
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
DEV_JOBS="${DEV_JOBS:-$(dirname "$PROFILE_DIR")/sw-developer/cron/jobs.json}"
mkdir -p "$PROFILE_DIR/cache"
# One run at a time: the old cron and the webhook tick (loop-tick.sh) may overlap; the second waits.
if command -v flock >/dev/null; then
  exec 9>"$PROFILE_DIR/cache/dispatch.lock"
  flock -w 600 9 || { echo "dispatch: Lock nach 10 min nicht frei, Lauf übersprungen" >&2; exit 0; }
fi

python3 - "$ORG" "$PROJECT" "$INSTANCES" "$DEV_LOGIN" "$OWNER_LOGIN" "$WS_ROOT" "$PROFILE_DIR/cache" \
  "$DEV_JOBS" <<'PY'
import calendar, fnmatch, json, os, re, subprocess, sys, time
from pathlib import Path

org, project, instances, dev_login, owner, ws_root, cache, dev_jobs = sys.argv[1:9]
DRY_RUN = os.environ.get("DISPATCH_DRY_RUN") == "1"
IDLE_MINUTES = 15  # an Action card without PR and developer job this long is reported (#57)
WRITE = ("admin", "maintain", "write")

GH_TIMEOUT = 60  # seconds per gh call; a hung call must not block the cron run
GH_ATTEMPTS = 3  # GitHub answers 502/504 on project queries now and then; retry them
GH_BACKOFF = (2, 5)  # seconds before the second and third attempt

# Only what a dispatch needs: this runs 20 times an hour, so it must stay cheap (#44).
ITEMS_QUERY = """query($org: String!, $num: Int!, $after: String) { organization(login: $org) { projectV2(number: $num) {
  id items(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes { id
    status: fieldValueByName(name: "Status") { ... on ProjectV2ItemFieldSingleSelectValue { name updatedAt } }
    instance: fieldValueByName(name: "Instance") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    content { ... on Issue { id url number title state body issueType { name } repository { nameWithOwner }
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


def write_access(repo_full, cache_):
    """Return None if both bots can write to the repository, else the reason it cannot start."""
    if repo_full not in cache_:
        try:
            lead = json.loads(gh("api", f"repos/{repo_full}")).get("permissions") or {}
            dev = json.loads(gh("api", f"repos/{repo_full}/collaborators/{dev_login}/permission"))
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            print(f"Rechte nicht lesbar: {repo_full}: {(getattr(error, 'stderr', None) or error)!s:.200}")
            cache_[repo_full] = f"the bot permissions on {repo_full} cannot be read"
            return cache_[repo_full]
        missing = [who for who, ok in (("the Lead bot", lead.get("push")),
                                       (dev_login, dev.get("permission") in WRITE)) if not ok]
        cache_[repo_full] = f"{' and '.join(missing)} cannot write to {repo_full}" if missing else None
    return cache_[repo_full]


def start(pid, item, inst, fields):
    """Move one card to Action on an instance together with its one-shot developer job.

    Returns None on success, else the step that failed; the card is then back on Goal (#57).
    """
    c = item["content"]
    repo_full, repo = c["repository"]["nameWithOwner"], c["repository"]["nameWithOwner"].split("/")[-1]
    m = re.search(r"Branch:\s*`([^`]+)`(?:\s*\(base:\s*`([^`]+)`\))?", c["body"] or "")
    branch, base = m.group(1), (m.group(2) or "main")
    if DRY_RUN:
        print(f"{inst}: would start {repo_full}#{c['number']} ({branch})")
        return None
    ws = f"{ws_root}/{repo}"
    wt = f"{ws}/.worktrees/{inst}"
    step = "preparing the worktree"
    try:
        subprocess.run(["git", "-C", ws, "fetch", "-q", "upstream"], check=True, capture_output=True, text=True)
        exists = subprocess.run(["git", "-C", ws, "rev-parse", "-q", "--verify", f"upstream/{branch}"],
                                capture_output=True).returncode == 0
        origin = f"upstream/{branch}" if exists else (base if base.startswith("upstream/") else f"upstream/{base}")
        subprocess.run(["git", "-C", ws, "worktree", "remove", "--force", wt], capture_output=True)
        subprocess.run(["git", "-C", ws, "worktree", "add", "-q", "-B", branch, wt, origin], check=True,
                       capture_output=True, text=True)
        step = "assigning the developer"
        gh("api", "-X", "POST", f"repos/{repo_full}/issues/{c['number']}/assignees", "-f", f"assignees[]={dev_login}")
        if owner in {a["login"] for a in c["assignees"]["nodes"]}:  # a restart after the owner held it
            gh("api", "-X", "DELETE", f"repos/{repo_full}/issues/{c['number']}/assignees", "-f", f"assignees[]={owner}")
        step = "setting instance and status"
        set_field(pid, item, fields["Instance"], inst)
        set_field(pid, item, fields["Status"], "Action")
        step = "creating the developer job"
        rnd = "2+" if exists else "1"
        prompt = (f"Implement task {c['url']} (repo {repo_full}, instance {inst}, round {rnd}). "
                  f"Work only in {wt} on branch {branch}. Follow skill sw-developer-workflow; the issue body is the order.")
        subprocess.run(["hermes", "-p", "sw-developer", "cron", "create", "1m", prompt, "--repeat", "1",
                        "--name", f"{inst}-{repo}-{c['number']}", "--skill", "sw-developer-workflow",
                        "--workdir", wt, "--deliver", "bot-chat:sw-lead", "--failure-deliver", "bot-chat:sw-lead"],
                       check=True, capture_output=True, text=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError) as error:
        detail = (getattr(error, "stderr", None) or str(error)).strip().splitlines()[-1:]
        print(f"{inst}: Start fehlgeschlagen {repo_full}#{c['number']} beim {step}: {' '.join(detail)}")
        if step in ("setting instance and status", "creating the developer job"):
            set_field(pid, item, fields["Status"], "Goal")
        return step
    print(f"{inst}: gestartet {repo_full}#{c['number']} ({branch}, Runde {rnd}){goal_to_action(item)}")
    return None


def goal_to_action(item):
    """Log the seconds from the move to Goal to this start: the Status value's updatedAt is that move."""
    moved = (item.get("status") or {}).get("updatedAt")
    if not moved:
        return ""
    seconds = round(time.time() - calendar.timegm(time.strptime(moved, "%Y-%m-%dT%H:%M:%SZ")))
    c = item["content"]
    with (Path(cache) / "goal-to-action.log").open("a") as log:
        log.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {c['repository']['nameWithOwner']}#{c['number']} {seconds}\n")
    return f", Goal→Action {seconds} s"


def scheduled_jobs():
    """Return the names of the developer jobs that are still scheduled, or None if unknown."""
    try:
        jobs = json.loads(Path(dev_jobs).read_text()).get("jobs") or []
    except (OSError, json.JSONDecodeError):
        return None
    return {j.get("name") or "" for j in jobs if j.get("enabled")}


def idle(item, jobs):
    """True for an Action card without a linked PR and without a scheduled developer job."""
    c = item["content"]
    suffix = f"-{c['repository']['nameWithOwner'].split('/')[-1]}-{c['number']}"
    return not c["closedByPullRequestsReferences"]["nodes"] and not any(n.endswith(suffix) for n in jobs)


def check_idle(active, reported, seen):
    """Report Action cards idle for IDLE_MINUTES and hand them to the product owner (#57).

    Returns the idle cards already handed over: they no longer hold an instance.
    """
    jobs = scheduled_jobs()
    if jobs is None:
        return []
    since_path = Path(cache) / "dispatch-idle.json"
    try:
        since = json.loads(since_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        since = {}
    now, idle_since, handed = time.time(), {}, []
    for item in (i for i in active if idle(i, jobs)):
        c = item["content"]
        idle_since[c["url"]] = since.get(c["url"], now)
        if now - idle_since[c["url"]] < IDLE_MINUTES * 60:
            continue
        handed.append(item)
        reason = f"on Action for {IDLE_MINUTES} minutes without a PR and without a developer job"
        if report(item, reason, seen, reported, f"@{owner} ") and not DRY_RUN:
            gh("api", "-X", "POST", f"repos/{c['repository']['nameWithOwner']}/issues/{c['number']}/assignees",
               "-f", f"assignees[]={owner}")
    if not DRY_RUN:
        since_path.write_text(json.dumps(idle_since, sort_keys=True))
    return handed


def report(item, reason, seen, reported, mention=""):
    """Comment once on a card that cannot start or run; True if this run reported it."""
    c = item["content"]
    key = f"{c['url']}|{reason}"
    seen[key] = True
    if key in reported:
        return False
    print(f"{'hängt' if mention else 'nicht gestartet'}: {c['repository']['nameWithOwner']}#{c['number']}: {reason}")
    if not DRY_RUN:
        text = (f"{mention}Stuck: {reason}. Move it back to Goal to start it again." if mention
                else f"Not started: {reason}. It stays on Goal and starts as soon as this is resolved.")
        gh("api", f"repos/{c['repository']['nameWithOwner']}/issues/{c['number']}/comments", "-f", f"body={text}")
    return True


def main():
    state_path = Path(cache) / "dispatch-reported.json"
    try:
        reported = json.loads(state_path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        reported = {}
    pid, items = project_items()
    open_items = [i for i in items if i["content"]["state"] == "OPEN"]
    active = [i for i in open_items if status_of(i) == "Action"]
    seen, fields, access = {}, None, {}
    handed = check_idle(active, reported, seen)
    active = [i for i in active if i not in handed]
    busy = {(i.get("instance") or {}).get("name") for i in active}
    free = [inst for inst in instances.split() if inst not in busy]
    running = [(i["content"]["repository"]["nameWithOwner"], allowed_files(i["content"]["body"])) for i in active]
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
        denied = write_access(repo, access)
        if denied:
            report(item, denied, seen, reported)
            continue
        current = (item.get("instance") or {}).get("name")
        inst = current if current in free else free[0]
        fields = fields or field_ids()
        failed = start(pid, item, inst, fields)
        if failed:
            report(item, f"the start failed while {failed}, see the dispatcher log", seen, reported)
            continue
        free.remove(inst)
        running.append((repo, files))
    if not DRY_RUN:
        state_path.write_text(json.dumps(seen, sort_keys=True))


main()
PY
