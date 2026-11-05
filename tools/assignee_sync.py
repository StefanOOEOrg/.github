#!/usr/bin/env python3
"""Keep exactly one assignee on every task in the org project: whoever acts next.

Rule (PROCESS.md, "Assignee = whoever acts next"):
    open PR, review requested from the Lead          -> Lead
    open PR, product owner approved                  -> Lead (merge)
    open PR, Lead approved                           -> product owner
    open PR, Lead requested changes                  -> Developer
    no open PR, status Ready / In Progress           -> Developer
    Triage, refined (Branch line / feature with sub-issues) -> product owner: reviews the refinement and
                                                        moves it to Backlog or into an iteration himself
    Triage, not refined                              -> Lead, unless the product owner holds it (open question)
    Backlog in the current iteration                 -> Lead (sprint planning, sets Ready)
    other Backlog / no status                        -> nobody (waits for sprint planning), or the product
                                                        owner while a question of his is pending
    issue closed                                     -> nobody
A manual assignment of the product owner wins over these rules while the item is in Triage, Backlog or
In review - also when a PR is open (PROCESS.md, "Assignee = inbox").
Called from github-watch.sh on every run; idempotent, only changes what differs.
Usage: assignee_sync.py <org> <project-number> [--dry-run]
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

LEAD, DEV, OWNER = "StefanOOELeadBot", "StefanOOEDevBot", "StefanOOE"
GH_TIMEOUT = 60  # seconds per gh call; a hung call must not block the cron run
GH_ATTEMPTS = 3  # GitHub answers 502/504 on the big project query now and then; retry reads
GH_BACKOFF = (2, 5)  # seconds before the second and third attempt
ASSIGN_PERMISSIONS = {"TRIAGE", "WRITE", "MAINTAIN", "ADMIN"}
QUERY = """query($org: String!, $num: Int!, $after: String) {
  organization(login: $org) { projectV2(number: $num) { items(first: 100, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes {
      status: fieldValueByName(name: "Status") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
      iteration: fieldValueByName(name: "Iteration") { ... on ProjectV2ItemFieldIterationValue { startDate duration } }
      content { ... on Issue {
        number state body issueType { name } subIssues(first: 1) { totalCount }
        repository { nameWithOwner viewerPermission }
        assignees(first: 10) { nodes { login } }
        timelineItems(last: 1, itemTypes: [ASSIGNED_EVENT]) { nodes { ... on AssignedEvent { actor { login } assignee { ... on User { login } } } } }
        closedByPullRequestsReferences(first: 5, includeClosedPrs: false) { nodes {
          state
          reviewRequests(first: 10) { nodes { requestedReviewer { ... on User { login } } } }
          reviews(last: 50) { nodes { author { login } state } }
        } }
      } }
    } } } } }"""


def gh(*args: str) -> str:
    """Run gh and return stdout, retrying the transient gateway failures.

    The project query returns a few hundred kilobytes; GitHub answers it with a
    502/504 now and then. Every call in this script is a read, so a retry is safe.
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


def project_items(org: str, number: int) -> list[dict]:
    """Return all project items whose content is an issue."""
    items, after = [], None
    while True:
        args = ["api", "graphql", "-f", f"query={QUERY}", "-F", f"num={number}", "-f", f"org={org}"]
        if after:
            args += ["-f", f"after={after}"]
        page = json.loads(gh(*args))["data"]["organization"]["projectV2"]["items"]
        items += [n for n in page["nodes"] if n.get("content") and "number" in n["content"]]
        if not page["pageInfo"]["hasNextPage"]:
            return items
        after = page["pageInfo"]["endCursor"]


def last_state(reviews: list[dict], login: str) -> str | None:
    """Return the latest APPROVED / CHANGES_REQUESTED state of one reviewer."""
    states = [r["state"] for r in reviews if (r["author"] or {}).get("login") == login
              and r["state"] in ("APPROVED", "CHANGES_REQUESTED")]
    return states[-1] if states else None


def is_refined(issue: dict) -> bool:
    """A task is refined when it carries the task order's Branch line; a feature when it has sub-issues."""
    if (issue.get("issueType") or {}).get("name") == "Feature":
        return issue["subIssues"]["totalCount"] > 0
    return re.search(r"Branch:\s*`[^`]+`", issue.get("body") or "") is not None


def in_current_iteration(item: dict, today: date) -> bool:
    """True when the item's iteration covers today (calendar days in Vienna)."""
    it = item.get("iteration")
    if not it:
        return False
    start = datetime.fromisoformat(it["startDate"]).date()
    return start <= today < start + timedelta(days=it["duration"])


def next_actor(item: dict) -> str | None:
    """Return the login that acts next on this item, or None for nobody."""
    issue = item["content"]
    if issue["state"] != "OPEN":
        return None
    current = {a["login"] for a in issue["assignees"]["nodes"]}
    status = (item.get("status") or {}).get("name")
    # A manual assignment of the product owner wins while the item is in Triage, Backlog or In review
    # (PROCESS.md, "Assignee = inbox") - also when a PR is open, which is what "In review" means.
    manual = ((issue.get("timelineItems") or {}).get("nodes") or [None])[-1]
    if (manual and (manual.get("actor") or {}).get("login") == OWNER and status in ("Triage", "Backlog", "In review", None)
            and (manual.get("assignee") or {}).get("login") in current):
        return manual["assignee"]["login"]  # the product owner assigned this by hand: his decision wins
    prs = [p for p in issue["closedByPullRequestsReferences"]["nodes"] if p["state"] == "OPEN"]
    if prs:
        pr = prs[0]
        requested = {(r["requestedReviewer"] or {}).get("login") for r in pr["reviewRequests"]["nodes"]}
        reviews = pr["reviews"]["nodes"]
        if LEAD in requested:
            return LEAD
        if last_state(reviews, OWNER) == "APPROVED":
            return LEAD
        lead = last_state(reviews, LEAD)
        if lead == "APPROVED":
            return OWNER
        if lead == "CHANGES_REQUESTED":
            return DEV
        return LEAD
    if status in ("Ready", "In Progress"):
        return DEV
    if status == "Done":
        return None
    refined = is_refined(issue)
    if status == "Triage":
        return OWNER if refined or OWNER in current else LEAD
    if in_current_iteration(item, datetime.now(ZoneInfo("Europe/Vienna")).date()):
        return LEAD  # Stefan released it into the sprint: the Lead plans it and sets Ready
    return OWNER if OWNER in current else None


def sync(org: str, number: int, dry_run: bool) -> list[str]:
    """Apply the rule to every item and return one line per change."""
    changes = []
    for item in project_items(org, number):
        issue = item["content"]
        if issue["repository"]["viewerPermission"] not in ASSIGN_PERMISSIONS:
            continue  # the Lead has read access only here (e.g. a private repo without collaborator)
        want = next_actor(item)
        have = {a["login"] for a in issue["assignees"]["nodes"]}
        add = {want} - have if want else set()
        remove = have - {want}
        if not add and not remove:
            continue
        repo, num = issue["repository"]["nameWithOwner"], issue["number"]
        changes.append(f"{repo}#{num}: {','.join(sorted(have)) or '-'} -> {want or '-'}")
        if dry_run:
            continue
        path = f"repos/{repo}/issues/{num}/assignees"
        try:
            if remove:
                gh("api", "-X", "DELETE", path, *[x for r in sorted(remove) for x in ("-f", f"assignees[]={r}")])
            if add:
                gh("api", "-X", "POST", path, *[x for a in sorted(add) for x in ("-f", f"assignees[]={a}")])
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            # one repository without access (e.g. the Lead is no collaborator) must not stop the others
            stderr = getattr(error, "stderr", "") or ""
            changes[-1] = f"FAILED {changes[-1]}: {stderr.strip()[:120]}"
    return changes


if __name__ == "__main__":
    for line in sync(sys.argv[1], int(sys.argv[2]), "--dry-run" in sys.argv[3:]):
        print(line)
