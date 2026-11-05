#!/usr/bin/env bash
# GitHub watch for the Lead (replaces board-watch.sh). No-agent cron in the sw-lead profile:
#
#   hermes cron create 10m --name github-watch --script github-watch.sh --no-agent \
#     --deliver bot-chat:sw-lead --failure-deliver local
#
# Reports only NEW events (state file), stdout = delivery payload, empty = silent:
#   - PR waiting for the Lead's review (review requested from StefanOOELeadBot)
#   - PR approved by Stefan and not merged yet  -> Lead merges
#   - Stefan requested changes on a PR (once per review id, reminder after 2 h and 24 h)
#   - task "In Progress" for longer than STALE_HOURS without a linked PR -> dev run probably died
# The snapshot file always carries the full current state (read it before answering "status?").
set -euo pipefail

ORG="${GH_ORG:-StefanOOEOrg}"
PROJECT="${GH_PROJECT_NUMBER:?set GH_PROJECT_NUMBER in profiles/sw-lead/.env}"
LEAD="${LEAD_LOGIN:-StefanOOELeadBot}"
OWNER_LOGIN="${OWNER_LOGIN:-StefanOOE}"
STALE_HOURS="${STALE_HOURS:-3}"
PROFILE_DIR="${HERMES_HOME:-$HOME/.hermes/profiles/sw-lead}"
mkdir -p "$PROFILE_DIR/cache"

python3 - "$ORG" "$PROJECT" "$LEAD" "$OWNER_LOGIN" "$STALE_HOURS" "$PROFILE_DIR/cache" <<'PY'
import json, os, re, subprocess, sys, time
from zoneinfo import ZoneInfo
from datetime import datetime, timezone, timedelta
from pathlib import Path

org, project, lead, owner, stale_h, cache = sys.argv[1:7]
cache = Path(cache)

GH_TIMEOUT = 60  # seconds per gh call; a hung call must not block the cron run
GH_ATTEMPTS = 3  # GitHub answers 502/504 on the big project query now and then; retry reads
GH_BACKOFF = (2, 5)  # seconds before the second and third attempt


def gh(*args):
    """Run a read-only ``gh`` call, retrying the transient gateways failures.

    The project query returns a few hundred kilobytes and GitHub occasionally answers
    it with a 502/504 or a reset; a cron run that dies on that reports nothing at all.
    Every call here is a read, so a retry is safe.
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

events = {}
for pr in json.loads(gh("search", "prs", "--owner", org, "--state", "open", "--review-requested", lead,
                        "--json", "url,title,repository,number")):
    events[f"review:{pr['url']}"] = f"Review wartet: {pr['repository']['name']}#{pr['number']} {pr['title'][:80]} {pr['url']}"
for pr in json.loads(gh("search", "prs", "--owner", org, "--state", "open", "--review", "approved",
                        "--json", "url,title,repository,number")):
    reviews = json.loads(gh("pr", "view", pr["url"], "--json", "reviews"))["reviews"]
    if any(r["author"]["login"] == owner and r["state"] == "APPROVED" for r in reviews):
        events[f"merge:{pr['url']}"] = f"Stefan hat approved, mergen: {pr['repository']['name']}#{pr['number']} {pr['url']}"

# Lead approved but forgot `gh pr edit --add-reviewer StefanOOE`: Stefan gets no request and the PR stalls.
PR_QUERY = """query($q: String!) { search(query: $q, type: ISSUE, first: 100) { nodes { ... on PullRequest {
  url number body repository { name }
  reviewRequests(first: 20) { nodes { requestedReviewer { ... on User { login } } } }
  reviews(last: 100) { nodes { author { login } state } } } } } }"""
prs = json.loads(gh("api", "graphql", "-f", f"query={PR_QUERY}", "-f", f"q=is:pr is:open org:{org}"))
for pr in prs["data"]["search"]["nodes"]:
    reviews = [(r["author"] or {}).get("login") for r in pr["reviews"]["nodes"]]
    lead_states = [r["state"] for r in pr["reviews"]["nodes"] if (r["author"] or {}).get("login") == lead]
    requested = {(r["requestedReviewer"] or {}).get("login") for r in pr["reviewRequests"]["nodes"]}
    if lead_states and lead_states[-1] == "APPROVED" and owner not in requested and owner not in reviews:
        events[f"ask-owner:{pr['url']}"] = (f"Lead hat approved, Stefan nicht angefragt: "
                                            f"{pr['repository']['name']}#{pr['number']} {pr['url']}")


def has_closing_line(body: str) -> bool:
    """True if the PR body carries a GitHub closing keyword line (`Closes|Fixes|Resolves #<n>`)."""
    return re.search(r"^\s*(?:closes|fixes|resolves)\s+#\d+", body or "", re.I | re.M) is not None


# Every PR closes its task (PROCESS.md quality gates: the body starts with `Closes #<task>`). Without that line
# neither the assignee sync nor the dispatcher can relate a PR to a task (#16), so each such PR is reported once.
for pr in prs["data"]["search"]["nodes"]:
    if not has_closing_line(pr.get("body")):
        events[f"orphan:{pr['url']}"] = (f"pr: ⚠️ ohne Closes #<task>: "
                                         f"{pr['repository']['name']}#{pr['number']} {pr['url']}")

# Approve reminder (Stefan, 2026-11-04): a PR that waits only for the product owner's approval for more than
# OWNER_WAIT_HOURS gets one @StefanOOE comment per head commit, repeated at most every OWNER_REPEAT_HOURS.
# "Only waits for him" = the Lead's latest review on the current head is APPROVED, CI is green and his review is
# requested. Re-approvals after a push are easy to miss otherwise (#78, #32).
OWNER_WAIT_HOURS, OWNER_REPEAT_HOURS = 2, 24
WAIT_QUERY = """query($q: String!) { search(query: $q, type: ISSUE, first: 100) { nodes { ... on PullRequest {
  url number title headRefOid repository { name nameWithOwner }
  commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
  reviewRequests(first: 20) { nodes { requestedReviewer { ... on User { login } } } }
  reviews(last: 50) { nodes { id author { login } state body submittedAt commit { oid } } } } } } }"""
remind_p = cache / "approve-reminders.json"
try:
    reminded = json.loads(remind_p.read_text())
except (FileNotFoundError, json.JSONDecodeError):
    reminded = {}
waiting = json.loads(gh("api", "graphql", "-f", f"query={WAIT_QUERY}", "-f", f"q=is:pr is:open org:{org}"))
now_utc = datetime.now(timezone.utc)
for pr in waiting["data"]["search"]["nodes"]:
    head = pr["headRefOid"]
    requested = {(r["requestedReviewer"] or {}).get("login") for r in pr["reviewRequests"]["nodes"]}
    on_head = [r for r in pr["reviews"]["nodes"] if (r.get("commit") or {}).get("oid") == head]
    lead_on_head = [r for r in on_head if (r["author"] or {}).get("login") == lead and r["state"] in ("APPROVED", "CHANGES_REQUESTED")]
    rollup = ((pr["commits"]["nodes"] or [{}])[0].get("commit") or {}).get("statusCheckRollup") or {}
    if (owner not in requested or not lead_on_head or lead_on_head[-1]["state"] != "APPROVED"
            or rollup.get("state") not in (None, "SUCCESS")):
        continue
    since = datetime.fromisoformat(lead_on_head[-1]["submittedAt"].replace("Z", "+00:00"))
    last = reminded.get(pr["url"], {})
    if now_utc - since < timedelta(hours=OWNER_WAIT_HOURS):
        continue
    if last.get("head") == head and now_utc - datetime.fromisoformat(last["at"]) < timedelta(hours=OWNER_REPEAT_HOURS):
        continue
    hours = int((now_utc - since).total_seconds() // 3600)
    body = (f"@{owner} this PR has waited {hours} h only for your approval: the Lead approved the current head "
            f"`{head[:7]}`, CI is green. After your approval the Lead merges it.\n\n"
            "<sub>Automatic reminder from github-watch (again after 24 h at the earliest).</sub>")
    try:
        subprocess.run(["gh", "api", f"repos/{pr['repository']['nameWithOwner']}/issues/{pr['number']}/comments",
                        "-f", f"body={body}"], check=True, capture_output=True, text=True, timeout=GH_TIMEOUT)
        reminded[pr["url"]] = {"head": head, "at": now_utc.isoformat()}
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        events[f"remind-failed:{pr['url']}"] = f"Approve-Erinnerung an Stefan fehlgeschlagen: {pr['url']} ({error})"
remind_p.write_text(json.dumps(reminded, sort_keys=True))

# Safety net: every open org issue belongs in the project (auto-add covers one repo per workflow only).
ISSUE_QUERY = """query($q: String!) { search(query: $q, type: ISSUE, first: 100) { nodes { ... on Issue {
  url number title repository { name } projectItems(first: 10) { nodes { project { number } } } } } } }"""
found = json.loads(gh("api", "graphql", "-f", f"query={ISSUE_QUERY}",
                      "-f", f"q=is:issue is:open archived:false org:{org}"))["data"]["search"]["nodes"]
def is_sprint_doc(issue: dict) -> bool:
    """Sprint plan/review issues in .github are documents, not work items."""
    return issue["repository"]["name"] == ".github" and issue["title"].startswith("Sprint ")


missing = [i for i in found if not is_sprint_doc(i) and str(project) not in
           {str(n["project"]["number"]) for n in i["projectItems"]["nodes"]}]
if missing:
    fields = {f["name"]: f for f in json.loads(gh("project", "field-list", project, "--owner", org,
                                                   "--format", "json"))["fields"]}
    triage = next(o["id"] for o in fields["Status"]["options"] if o["name"] == "Triage")
    pid = json.loads(gh("project", "view", project, "--owner", org, "--format", "json"))["id"]
for i in missing:
    item = json.loads(gh("project", "item-add", project, "--owner", org, "--url", i["url"],
                         "--format", "json"))["id"]
    gh("project", "item-edit", "--project-id", pid, "--id", item, "--field-id", fields["Status"]["id"],
       "--single-select-option-id", triage)
    events[f"added:{i['url']}"] = (f"Neu im Project (Triage): {i['repository']['name']}#{i['number']} "
                                   f"{i['title'][:80]} {i['url']}")

# Sprint planning: the product owner sets Iteration; the Lead refines and sets Ready. Report items of the
# current iteration that are still in Triage/Backlog, so the Lead does not have to be poked.
SPRINT_QUERY = """query($org: String!, $num: Int!, $after: String) { organization(login: $org) { projectV2(number: $num) {
  items(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes {
    status: fieldValueByName(name: "Status") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    instance: fieldValueByName(name: "Instance") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    iteration: fieldValueByName(name: "Iteration") { ... on ProjectV2ItemFieldIterationValue { title startDate duration } }
    content { ... on Issue { url number title state body createdAt repository { name } issueType { name } subIssues(first: 1) { totalCount } issueDependenciesSummary { blockedBy }
      assignees(first: 5) { nodes { login } } comments(last: 1) { nodes { id createdAt author { login } } }
      timelineItems(last: 1, itemTypes: [ASSIGNED_EVENT]) { nodes { ... on AssignedEvent { id createdAt actor { login } assignee { ... on User { login } } } } }
      closedByPullRequestsReferences(first: 3, includeClosedPrs: false) { nodes { number state } } } } } } } } }"""
# WATCH_TODAY=YYYY-MM-DD simulates a date for tests; otherwise today in Vienna (iterations are calendar days there)
today = (datetime.fromisoformat(os.environ["WATCH_TODAY"]).date() if os.environ.get("WATCH_TODAY")
         else datetime.now(ZoneInfo("Europe/Vienna")).date())
after = None
sprint_end = {}  # iteration title -> open items on its last day
TRIAGE_HOURS = 2  # items the project workflow parked in Triage longer than this need the Lead
busy, refinable = set(), 0  # instances with a Ready/In Progress task; unrefined tasks in the current iteration
while True:
    args = ["api", "graphql", "-f", f"query={SPRINT_QUERY}", "-f", f"org={org}", "-F", f"num={project}"]
    page = json.loads(gh(*args + (["-f", f"after={after}"] if after else [])))
    page = page["data"]["organization"]["projectV2"]["items"]
    for node in page["nodes"]:
        it, c = node.get("iteration"), node.get("content") or {}
        status = (node.get("status") or {}).get("name")
        # Inbox: everything assigned to the Lead. Unanswered comments of the product owner and his manual
        # assignments are the Lead's next step:
        # decisions are written as comments, and the watch would not see them otherwise (.github#24).
        last_comment = ((c.get("comments") or {}).get("nodes") or [None])[-1]
        if (c.get("state") == "OPEN" and last_comment and (last_comment["author"] or {}).get("login") == owner
                and lead in {a["login"] for a in c["assignees"]["nodes"]}):
            events[f"owner-comment:{last_comment['id']}"] = (f"Inbox – Stefan hat kommentiert, du bist dran: "
                                                             f"{c['repository']['name']}#{c['number']} {c['title'][:70]} {c['url']}")
        assigned = ((c.get("timelineItems") or {}).get("nodes") or [None])[-1]
        if (c.get("state") == "OPEN" and assigned and (assigned.get("actor") or {}).get("login") == owner
                and (assigned.get("assignee") or {}).get("login") == lead
                and not (last_comment and (last_comment["author"] or {}).get("login") == lead
                         and last_comment["createdAt"] > assigned["createdAt"])):
            events[f"owner-assigned:{assigned['id']}"] = (f"Inbox – Stefan hat dir das zugewiesen: "
                                                          f"{c['repository']['name']}#{c['number']} {c['title'][:70]} {c['url']}")
        triage_prs = [pr["number"] for pr in ((c.get("closedByPullRequestsReferences") or {}).get("nodes") or [])
                      if pr["state"] == "OPEN"]
        if status == "Triage" and c.get("state") == "OPEN" and triage_prs:
            events[f"triage-pr:{c['url']}"] = (f"PR #{triage_prs[0]} zu einem Triage-Item – Triage-Karten werden nicht begonnen "
                                             f"(Stefan gibt sie erst frei): {c['repository']['name']}#{c['number']} {c['url']}")
        task_refined = re.search(r"Branch:\s*`[^`]+`", c.get("body") or "") is not None
        feature_split = (c.get("issueType") or {}).get("name") == "Feature" and (c.get("subIssues") or {}).get("totalCount", 0) > 0
        # refined triage items wait for Stefan's review (assigned to him by assignee_sync), not for the Lead
        if (status == "Triage" and c.get("state") == "OPEN" and not is_sprint_doc(c) and not (task_refined or feature_split)
                and datetime.now(timezone.utc) - datetime.fromisoformat(c["createdAt"].replace("Z", "+00:00")) > timedelta(hours=TRIAGE_HOURS)):
            events[f"triage:{c['url']}"] = (f"Seit über {TRIAGE_HOURS} h in Triage – triagieren (Typ, Parent, verfeinern oder Frage an Stefan, dann Backlog): {c['repository']['name']}#{c['number']} {c['title'][:80]} {c['url']}")
        if status in ("Ready", "In Progress") and c.get("state") == "OPEN":
            busy.add((node.get("instance") or {}).get("name"))
        if status in ("In Progress", "In review") and c.get("state") == "OPEN" and (
                not it or not (datetime.fromisoformat(it["startDate"]).date() <= today
                               < datetime.fromisoformat(it["startDate"]).date() + timedelta(days=it["duration"]))):
            events[f"no-iteration:{c['url']}"] = (f"{status} ohne aktuelle Iteration – nur Stefan plant den Sprint, nichts am Sprint vorbei starten: {c['repository']['name']}#{c['number']} {c['title'][:70]} {c['url']}")
        if not it or not c or (c.get("issueType") or {}).get("name") == "Feature":
            continue  # features never go into a sprint
        start = datetime.fromisoformat(it["startDate"]).date()
        end = start + timedelta(days=it["duration"])
        if start <= today < end and today == end - timedelta(days=1):
            open_items = sprint_end.setdefault(it["title"], [])
            if c.get("state") == "OPEN":
                open_items.append(f"{c['repository']['name']}#{c['number']} {c['title'][:50]} ({status or '-'})")
        if c.get("state") != "OPEN":
            continue
        # refined = has the task order's Branch line; refined but blocked tasks wait in Backlog on purpose
        refined = re.search(r"Branch:\s*`[^`]+`", c.get("body") or "") is not None
        startable = (refined and status == "Backlog" and (c.get("issueType") or {}).get("name") != "Feature"
                     and not (c.get("issueDependenciesSummary") or {}).get("blockedBy"))
        if start <= today < end and startable:
            events[f"sprint:{c['url']}"] = (f"Neu im Sprint ({it['title']}), noch nicht verfeinert: "
                                            f"{c['repository']['name']}#{c['number']} {c['title'][:80]} "
                                            f"[verfeinert: Ready setzen oder blocked-by eintragen] {c['url']}")
        if start <= today < end and status in (None, "Triage", "Backlog") and not refined:
            refinable += 1
            events[f"sprint:{c['url']}"] = (f"Neu im Sprint ({it['title']}), noch nicht verfeinert: "
                                            f"{c['repository']['name']}#{c['number']} {c['title'][:80]} {c['url']}")
    if not page["pageInfo"]["hasNextPage"]:
        break
    after = page["pageInfo"]["endCursor"]
for inst in os.environ.get("DEV_INSTANCES", "dev-1").split():
    if inst not in busy and refinable:
        events[f"idle:{inst}"] = (f"Instanz {inst} ist frei, aber in der aktuellen Iteration ist kein Task Ready "
                                  f"({refinable} noch nicht verfeinert) – Sprint-Planning fortsetzen")
for title, open_items in sprint_end.items():
    rest = (f"noch offen ({len(open_items)}): " + "; ".join(open_items)) if open_items else "alles erledigt"
    events[f"sprint-end:{title}"] = (f"Sprint {title} endet heute, {rest} – Review-Issue in .github anlegen, "
                                     "Stefan vorschlagen, was in die nächste Iteration geht")

items = json.loads(gh("project", "item-list", project, "--owner", org, "--format", "json", "-L", "1000"))["items"]
now = datetime.now(timezone.utc)
for i in items:
    c = i.get("content", {})
    if i.get("status") != "In Progress" or c.get("type") != "Issue":
        continue
    issue = json.loads(gh("issue", "view", str(c["number"]), "-R", c["repository"], "--json", "updatedAt,closedByPullRequestsReferences"))
    upd = datetime.fromisoformat(issue["updatedAt"].replace("Z", "+00:00"))
    if not issue.get("closedByPullRequestsReferences") and now - upd > timedelta(hours=float(stale_h)):
        events[f"stale:{c['url']}"] = f"Hängt seit >{stale_h} h in In Progress ohne PR ({i.get('instance')}): {c['url']}"

state_p, snap_p = cache / "github-watch-state.json", cache / "github-watch.md"
# State = {event: last time it was printed}. A bot-chat delivery can fail (SESSION_NOT_OWNED while the
# Lead session is busy) and the script cannot see that, so an event that is still open is printed again
# after REMIND_MINUTES instead of being reported only once.
REMIND_MINUTES = 60
try:
    prev = json.loads(state_p.read_text())
except (FileNotFoundError, json.JSONDecodeError):
    prev = {}
if isinstance(prev, list):  # old format: list of already reported keys
    prev = {k: now.isoformat() for k in prev}
snap_p.write_text(f"# GitHub watch — {now.isoformat(timespec='seconds')}\n\n" +
                  ("\n".join(events.values()) if events else "nichts offen") + "\n")
SPRINT_REMIND_MINUTES = 20  # unrefined sprint tasks block the dev instances, so nag more often


def is_due(key: str, last: str | None) -> bool:
    """New events are due; open ones again after their reminder interval; sprint-end only once."""
    if last is None:
        return True
    if key.startswith("sprint-end:"):
        return False
    minutes = SPRINT_REMIND_MINUTES if key.startswith("sprint:") else REMIND_MINUTES
    return now - datetime.fromisoformat(last) > timedelta(minutes=minutes)


state, planning = {}, []
for k, msg in events.items():
    last = prev.get(k)
    if k.startswith("orphan:"):
        # Once per PR and no reminder: the key lives as long as the body lacks the line and disappears with it
        # (state is rebuilt from `events` every run), so an edited body silences the next run (#16).
        state[k] = last or now.isoformat()
        if last is None:
            print(msg)
        continue
    due = is_due(k, last)
    state[k] = now.isoformat() if due else last
    if not due:
        continue
    if k.startswith("sprint:"):  # bundled below: sprint planning covers all tasks in one run
        planning.append(msg.split("noch nicht verfeinert: ", 1)[-1])
    else:
        print(msg if last is None else f"Erinnerung: {msg}")
if planning:
    unrefined = [m.split("noch nicht verfeinert: ", 1)[-1] for k, m in events.items() if k.startswith("sprint:")]
    print(f"Sprint-Planning nötig: {len(unrefined)} Tasks der aktuellen Iteration brauchen dich (verfeinern bzw. Ready setzen). "
          "Alle in EINEM Lauf planen (Abschnitt 5, Sprint-Planning):\n- " + "\n- ".join(unrefined))
# Stefan's "changes requested" (Sprint 1 retro): the PR's review decision is not enough - it also covers a
# dismissed or stale state, so only his latest review counts. One report per review id; a review that no longer
# sits on the head commit is answered (the Lead pushed) and gets no reminder. An APPROVED writes no key, which
# clears the remembered id.
CHANGES_WAIT_HOURS, CHANGES_REPEAT_HOURS = 2, 24
for pr in waiting["data"]["search"]["nodes"]:
    own = [r for r in pr["reviews"]["nodes"] if (r["author"] or {}).get("login") == owner]
    if not own or own[-1]["state"] != "CHANGES_REQUESTED":
        continue
    review = own[-1]
    key = f"changes_requested:{pr['url']}"
    marked = prev.get(f"{key}:reminded") or {}
    if isinstance(marked, str):  # a bare timestamp is enough for the first reminder
        marked = {"at": marked}
    sent = int(marked.get("reminders", 0))
    at = datetime.fromisoformat(marked["at"]) if marked.get("at") else now
    line = (f"review: 📝 Stefan hat Änderungen verlangt: {pr['repository']['name']}#{pr['number']} "
            f"— {pr['title'][:80]} {pr['url']}")
    first = next((ln.strip() for ln in (review.get("body") or "").splitlines() if ln.strip()), "")
    if first:
        line += f"\n  {first[:200]}"
    if prev.get(key) != review["id"]:  # a new review id is a new event
        print(line)
        sent, at = 0, now
    elif ((review.get("commit") or {}).get("oid") == pr["headRefOid"]
          and now - at >= timedelta(hours=CHANGES_REPEAT_HOURS if sent else CHANGES_WAIT_HOURS)):
        print(f"Erinnerung: {line}")
        sent += 1
        at = now
    state[key] = review["id"]
    state[f"{key}:reminded"] = {"at": at.isoformat(), "reminders": sent}
state_p.write_text(json.dumps(state, sort_keys=True))
PY

# Assignee = whoever acts next (PROCESS.md). Changes go to a log, not to the Lead; a failure is reported.
SYNC="$PROFILE_DIR/skills/personal/sw-lead-workflow/scripts/assignee_sync.py"
if ! python3 "$SYNC" "$ORG" "$PROJECT" >> "$PROFILE_DIR/cache/assignee-sync.log" 2>&1; then
    echo "assignee-sync fehlgeschlagen, siehe cache/assignee-sync.log"
fi
