#!/usr/bin/env bash
# GitHub watch for the Lead. No-agent cron in the sw-lead profile:
#
#   hermes cron create 10m --name github-watch --script github-watch.sh --no-agent \
#     --deliver bot-chat:sw-lead --failure-deliver local
#
# The assignee says who acts next, so the watch reports the Lead's inbox and only what the assignee
# cannot show. Open events repeat every hour; stdout = delivery payload, empty = silent.
#   Inbox: review requested, ready to merge, Stefan's changes, comment or assignment, unrefined Triage
#   Checks: stalled Action card, Verify without PR, PR on a Triage card, PR without Closes line,
#           issue missing from the project, merged .github PR to review afterwards, retro due
#   Stefan: approve reminder as a comment on the PR
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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

org, project, lead, owner, stale_h, cache = sys.argv[1:7]
cache = Path(cache)

GH_TIMEOUT = 60  # seconds per gh call; a hung call must not block the cron run
GH_ATTEMPTS = 3  # GitHub answers 502/504 on the big project query now and then; retry reads
GH_BACKOFF = (2, 5)  # seconds before the second and third attempt
REMIND_MINUTES = 60  # a delivery can fail unseen, so an open event is printed again
ONCE = ("orphan:", "postmerge:", "retro:")  # reported a single time, no reminder
TRIAGE_HOURS = 2  # unrefined items longer in Triage need the Lead
OWNER_WAIT_HOURS, OWNER_REPEAT_HOURS = 2, 24  # approve reminder: first after, then at most every
RETRO_START, RETRO_DAYS = date(2026, 11, 14), 14  # fixed retro rhythm, every two weeks
OUTER_LOOP_REPO = ".github"  # maintained directly; the Lead reviews after the merge
BUDGET_STATE = "github-budget-reported"

PR_QUERY = """query($q: String!) { search(query: $q, type: ISSUE, first: 100) { nodes { ... on PullRequest {
  url number title body headRefOid repository { name nameWithOwner }
  commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
  reviewRequests(first: 10) { nodes { requestedReviewer { ... on User { login } } } }
  reviews(last: 30) { nodes { id author { login } state body submittedAt commit { oid } } } } } } }"""
ISSUE_QUERY = """query($q: String!) { search(query: $q, type: ISSUE, first: 100) { nodes { ... on Issue {
  url number title repository { name } projectItems(first: 5) { nodes { project { number } } } } } } }"""
BOARD_QUERY = """query($org: String!, $num: Int!, $after: String) { organization(login: $org) { projectV2(number: $num) {
  items(first: 100, after: $after) { pageInfo { hasNextPage endCursor } nodes {
    status: fieldValueByName(name: "Status") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    instance: fieldValueByName(name: "Instance") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
    content { ... on Issue { url number title state body createdAt updatedAt repository { name }
      issueType { name } subIssues(first: 1) { totalCount }
      assignees(first: 5) { nodes { login } } comments(last: 1) { nodes { id createdAt author { login } } }
      timelineItems(last: 1, itemTypes: [ASSIGNED_EVENT]) { nodes { ... on AssignedEvent { id createdAt actor { login } assignee { ... on User { login } } } } }
      closedByPullRequestsReferences(first: 3, includeClosedPrs: false) { nodes { number } } } } } } } } }"""


class BudgetExhausted(Exception):
    """The GraphQL budget of the token is used up (#44)."""


def gh(*args):
    """Run a read-only ``gh`` call, retrying the transient gateway failures.

    The project query is big and GitHub occasionally answers it with a 502/504 or a reset; a cron
    run that dies on that reports nothing at all. Every call here is a read, so a retry is safe.
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
                raise BudgetExhausted from error
            last = error
        if attempt < len(GH_BACKOFF):
            time.sleep(GH_BACKOFF[attempt])
    raise last


def slug(item):
    return f"{item['repository']['name']}#{item['number']}"


def login(node):
    return (node.get("author") or node.get("actor") or {}).get("login")


def latest_state(reviews, who):
    """Return the reviewer's latest deciding review, or None."""
    own = [r for r in reviews if login(r) == who and r["state"] in ("APPROVED", "CHANGES_REQUESTED")]
    return own[-1] if own else None


def has_closing_line(body):
    """True if the PR body carries a GitHub closing keyword (`close|fix|resolve` + `#<n>`, anywhere)."""
    return re.search(r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\b\s*:?\s*#\d+", body or "", re.I) is not None


def pr_events(prs, events):
    """Report the open PRs: the Lead's inbox and PRs without a closing line."""
    for pr in prs:
        name = f"{slug(pr)} {pr['title'][:70]} {pr['url']}"
        requested = {(r["requestedReviewer"] or {}).get("login") for r in pr["reviewRequests"]["nodes"]}
        reviews = pr["reviews"]["nodes"]
        own, by_lead = latest_state(reviews, owner), latest_state(reviews, lead)
        if lead in requested:
            events[f"review:{pr['url']}"] = f"Inbox – Review wartet: {name}"
        if own and own["state"] == "APPROVED":
            events[f"merge:{pr['url']}"] = f"Inbox – Stefan hat approved, mergen: {name}"
        if own and own["state"] == "CHANGES_REQUESTED" and (own.get("commit") or {}).get("oid") == pr["headRefOid"]:
            first = next((ln.strip() for ln in (own.get("body") or "").splitlines() if ln.strip()), "")
            events[f"changes:{own['id']}"] = f"Inbox – Stefan will Änderungen: {name}\n  {first[:200]}".rstrip()
        if by_lead and by_lead["state"] == "APPROVED" and owner not in requested and not own:
            events[f"ask-owner:{pr['url']}"] = f"Inbox – Lead hat approved, Stefan anfragen: {name}"
        if not has_closing_line(pr.get("body")):
            events[f"orphan:{pr['url']}"] = f"pr: ⚠️ ohne Closes-Zeile: {slug(pr)} {pr['url']}"


def remind_owner(prs, events):
    """Comment on a PR that waits only for the product owner's approval (#78, #32)."""
    path = cache / "approve-reminders.json"
    try:
        reminded = json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        reminded = {}
    now = datetime.now(timezone.utc)
    for pr in prs:
        head = pr["headRefOid"]
        requested = {(r["requestedReviewer"] or {}).get("login") for r in pr["reviewRequests"]["nodes"]}
        on_head = [r for r in pr["reviews"]["nodes"] if (r.get("commit") or {}).get("oid") == head]
        by_lead = latest_state(on_head, lead)
        rollup = ((pr["commits"]["nodes"] or [{}])[0].get("commit") or {}).get("statusCheckRollup") or {}
        if owner not in requested or not by_lead or by_lead["state"] != "APPROVED" \
                or rollup.get("state") not in (None, "SUCCESS"):
            continue
        since = datetime.fromisoformat(by_lead["submittedAt"].replace("Z", "+00:00"))
        last = reminded.get(pr["url"], {})
        if now - since < timedelta(hours=OWNER_WAIT_HOURS):
            continue
        if last.get("head") == head and now - datetime.fromisoformat(last["at"]) < timedelta(hours=OWNER_REPEAT_HOURS):
            continue
        hours = int((now - since).total_seconds() // 3600)
        body = (f"@{owner} this PR has waited {hours} h only for your approval: the Lead approved the current head "
                f"`{head[:7]}`, CI is green. After your approval the Lead merges it.\n\n"
                "<sub>Automatic reminder from github-watch (again after 24 h at the earliest).</sub>")
        try:
            subprocess.run(["gh", "api", f"repos/{pr['repository']['nameWithOwner']}/issues/{pr['number']}/comments",
                            "-f", f"body={body}"], check=True, capture_output=True, text=True, timeout=GH_TIMEOUT)
            reminded[pr["url"]] = {"head": head, "at": now.isoformat()}
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            events[f"remind-failed:{pr['url']}"] = f"Approve-Erinnerung an Stefan fehlgeschlagen: {pr['url']} ({error})"
    path.write_text(json.dumps(reminded, sort_keys=True))


def is_doc(issue):
    """Sprint and retro issues in .github are documents, not work items."""
    return issue["repository"]["name"] == OUTER_LOOP_REPO and issue["title"].startswith(("Sprint ", "Retro "))


def add_missing(events):
    """Safety net: every open org issue belongs in the project (auto-add covers one repo per workflow only)."""
    found = json.loads(gh("api", "graphql", "-f", f"query={ISSUE_QUERY}",
                          "-f", f"q=is:issue is:open archived:false org:{org}"))["data"]["search"]["nodes"]
    missing = [i for i in found if not is_doc(i)
               and str(project) not in {str(n["project"]["number"]) for n in i["projectItems"]["nodes"]}]
    if not missing:
        return
    fields = {f["name"]: f for f in json.loads(gh("project", "field-list", project, "--owner", org,
                                                   "--format", "json"))["fields"]}
    triage = next(o["id"] for o in fields["Status"]["options"] if o["name"] == "Triage")
    pid = json.loads(gh("project", "view", project, "--owner", org, "--format", "json"))["id"]
    for i in missing:
        item = json.loads(gh("project", "item-add", project, "--owner", org, "--url", i["url"],
                             "--format", "json"))["id"]
        gh("project", "item-edit", "--project-id", pid, "--id", item, "--field-id", fields["Status"]["id"],
           "--single-select-option-id", triage)
        events[f"added:{i['url']}"] = f"Neu im Project (Triage): {slug(i)} {i['title'][:80]} {i['url']}"


def board_items():
    """Yield the open issues on the board with their status and instance."""
    after = None
    while True:
        args = ["api", "graphql", "-f", f"query={BOARD_QUERY}", "-f", f"org={org}", "-F", f"num={project}"]
        page = json.loads(gh(*args + (["-f", f"after={after}"] if after else [])))
        page = page["data"]["organization"]["projectV2"]["items"]
        for node in page["nodes"]:
            if (node.get("content") or {}).get("state") == "OPEN":
                yield node
        if not page["pageInfo"]["hasNextPage"]:
            return
        after = page["pageInfo"]["endCursor"]


def refined(issue):
    """A task is refined with its Branch line, a feature with sub-issues."""
    if (issue.get("issueType") or {}).get("name") == "Feature":
        return issue["subIssues"]["totalCount"] > 0
    return re.search(r"Branch:\s*`[^`]+`", issue.get("body") or "") is not None


def card_events(node, events, now):
    """Report one open card: the Lead's inbox and the states the assignee cannot show."""
    c, status = node["content"], (node.get("status") or {}).get("name")
    name = f"{slug(c)} {c['title'][:70]} {c['url']}"
    prs = [p["number"] for p in c["closedByPullRequestsReferences"]["nodes"]]
    assignees = {a["login"] for a in c["assignees"]["nodes"]}
    comment = (c["comments"]["nodes"] or [None])[-1]
    assigned = (c["timelineItems"]["nodes"] or [None])[-1]
    if comment and login(comment) == owner and lead in assignees:
        events[f"owner-comment:{comment['id']}"] = f"Inbox – Stefan hat kommentiert: {name}"
    answered = comment and login(comment) == lead and assigned and comment["createdAt"] > assigned["createdAt"]
    if assigned and login(assigned) == owner and (assigned.get("assignee") or {}).get("login") == lead and not answered:
        events[f"owner-assigned:{assigned['id']}"] = f"Inbox – Stefan hat dir das zugewiesen: {name}"
    age = now - datetime.fromisoformat(c["createdAt"].replace("Z", "+00:00"))
    if status == "Triage" and not is_doc(c) and not refined(c) and age > timedelta(hours=TRIAGE_HOURS):
        events[f"triage:{c['url']}"] = f"Inbox – seit über {TRIAGE_HOURS} h in Triage, verfeinern: {name}"
    if status == "Triage" and prs:
        events[f"triage-pr:{c['url']}"] = f"PR #{prs[0]} zu einer Triage-Karte, die nicht begonnen werden darf: {name}"
    if status == "Verify" and not prs:
        events[f"board:{c['url']}"] = f"board: ⚠️ steht auf Verify ohne verlinkten PR: {name}"
    idle = now - datetime.fromisoformat(c["updatedAt"].replace("Z", "+00:00"))
    if status == "Action" and not prs and idle > timedelta(hours=float(stale_h)):
        instance = (node.get("instance") or {}).get("name")
        events[f"stale:{c['url']}"] = f"Hängt seit >{stale_h} h auf Action ohne PR ({instance}): {name}"


def post_merge_events(events, today):
    """The Lead reviews a merged .github PR afterwards: that repository is the outer loop."""
    since = (today - timedelta(days=1)).isoformat()
    merged = json.loads(gh("search", "prs", "--repo", f"{org}/{OUTER_LOOP_REPO}", "--merged", "--merged-at", f">={since}",
                           "--json", "url,number,title"))
    for pr in merged:
        events[f"postmerge:{pr['url']}"] = f"Inbox – nach dem Merge prüfen: #{pr['number']} {pr['title'][:70]} {pr['url']}"


def is_due(key, last, now):
    if last is None:
        return True
    if key.startswith(ONCE):
        return False
    return now - datetime.fromisoformat(last) > timedelta(minutes=REMIND_MINUTES)


def collect(today):
    """Return all current events."""
    events = {}
    prs = json.loads(gh("api", "graphql", "-f", f"query={PR_QUERY}", "-f", f"q=is:pr is:open org:{org}"))
    prs = prs["data"]["search"]["nodes"]
    pr_events(prs, events)
    remind_owner(prs, events)
    add_missing(events)
    now = datetime.now(timezone.utc)
    for node in board_items():
        card_events(node, events, now)
    post_merge_events(events, today)
    days = (today - RETRO_START).days
    if days >= 0 and days % RETRO_DAYS == 0:
        events[f"retro:{today}"] = f"Retro fällig: Issue „Retro {today}“ in .github anlegen (PROCESS.md, Continuous improvement)"
    return events


def budget_notice(now):
    """Say once an hour that the run was skipped, instead of a traceback every ten minutes."""
    path = cache / BUDGET_STATE
    try:
        last = datetime.fromisoformat(path.read_text().strip())
    except (FileNotFoundError, ValueError):
        last = None
    if last is None or now - last > timedelta(minutes=REMIND_MINUTES):
        print("GitHub-GraphQL-Budget des Lead-Tokens ist aufgebraucht: Watch und Dispatcher pausieren bis zum Reset.")
        path.write_text(now.isoformat())


def main():
    today = (date.fromisoformat(os.environ["WATCH_TODAY"]) if os.environ.get("WATCH_TODAY")
             else datetime.now(ZoneInfo("Europe/Vienna")).date())
    now = datetime.now(timezone.utc)
    try:
        events = collect(today)
    except BudgetExhausted:
        budget_notice(now)
        return
    state_p, snap_p = cache / "github-watch-state.json", cache / "github-watch.md"
    try:
        prev = json.loads(state_p.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        prev = {}
    snap_p.write_text(f"# GitHub watch — {now.isoformat(timespec='seconds')}\n\n" +
                      ("\n".join(events.values()) if events else "nichts offen") + "\n")
    state = {}
    for key, message in events.items():
        last = prev.get(key)
        due = is_due(key, last, now)
        state[key] = now.isoformat() if due else last
        if due:
            print(message if last is None else f"Erinnerung: {message}")
    state_p.write_text(json.dumps(state, sort_keys=True))


main()
PY

# Assignee = whoever acts next (PROCESS.md). Changes go to a log, not to the Lead; a failure is reported.
SYNC="$PROFILE_DIR/scripts/assignee_sync.py"
if ! python3 "$SYNC" "$ORG" "$PROJECT" >> "$PROFILE_DIR/cache/assignee-sync.log" 2>&1; then
    echo "assignee-sync fehlgeschlagen, siehe cache/assignee-sync.log"
fi
