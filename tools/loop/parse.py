"""Turn GraphQL answers into the model. Pure: dicts in, dataclasses out."""

from __future__ import annotations

from datetime import datetime

from loop import config
from loop.model import (
    Activity,
    Blocker,
    Board,
    Card,
    CardState,
    PullRequest,
    Ref,
    Review,
    Task,
)

WRITE_PERMISSIONS = {"TRIAGE", "WRITE", "MAINTAIN", "ADMIN"}


def when(value: str | None) -> datetime | None:
    """Parse a GitHub timestamp (``2026-11-07T16:00:00Z``), None stays None."""
    return datetime.fromisoformat(value) if value else None


def _login(node: dict | None) -> str | None:
    return (node or {}).get("login")


def _review(node: dict) -> Review:
    body = (node.get("body") or "").splitlines()
    first = next((line.strip() for line in body if line.strip()), "")
    commit = (node.get("commit") or {}).get("oid", "")
    return Review(_login(node.get("author")) or "", node["state"], commit,
                  when(node.get("submittedAt")), first)


def parse_pr(node: dict) -> PullRequest:
    """One PullRequest node of the PR fragment."""
    reviews = tuple(_review(r) for r in (node.get("reviews") or {}).get("nodes", []))
    requests = (node.get("reviewRequests") or {}).get("nodes", [])
    requested = frozenset(filter(None, (_login(n.get("requestedReviewer")) for n in requests)))
    commits = (node.get("commits") or {}).get("nodes") or [{}]
    rollup = ((commits[0] or {}).get("commit") or {}).get("statusCheckRollup") or {}
    ref = Ref(node["repository"]["nameWithOwner"], node["number"], node.get("url", ""),
              _login(node.get("headRepositoryOwner")) or "")
    return PullRequest(ref, node.get("state", "OPEN"), node.get("headRefOid", ""),
                       node.get("body") or "", requested, reviews, rollup.get("state"))


def _activity(issue: dict) -> Activity:
    assigned = ((issue.get("timelineItems") or {}).get("nodes") or [None])[-1] or {}
    comment = ((issue.get("comments") or {}).get("nodes") or [None])[-1] or {}
    return Activity(_login(assigned.get("actor")), _login(assigned.get("assignee")),
                    when(assigned.get("createdAt")), _login(comment.get("author")),
                    when(comment.get("createdAt")))


def _reopened(issue: dict) -> datetime | None:
    node = ((issue.get("reopened") or {}).get("nodes") or [None])[-1] or {}
    return when(node.get("createdAt"))


def parse_card(item: dict, issue: dict) -> Card:
    """One project item (Status, Instance) and its issue."""
    repo = issue["repository"]
    status = item.get("status") or {}
    ref = Ref(repo["nameWithOwner"], issue["number"], issue.get("url", ""),
              writable=repo.get("viewerPermission") in WRITE_PERMISSIONS)
    state = CardState(issue["state"] == "OPEN", status.get("name"), when(status.get("updatedAt")),
                      (item.get("instance") or {}).get("name"), when(issue.get("closedAt")),
                      item.get("id", ""), _reopened(issue))
    task = Task(issue.get("body") or "", (issue.get("issueType") or {}).get("name"),
                (issue.get("subIssues") or {}).get("totalCount", 0))
    blockers = tuple(Blocker(b["repository"]["nameWithOwner"], b["number"], b["state"] == "OPEN")
                     for b in (issue.get("blockedBy") or {}).get("nodes", []))
    linked = (issue.get("closedByPullRequestsReferences") or {}).get("nodes", [])
    prs = tuple(parse_pr(p) for p in linked)
    assignees = frozenset(a["login"] for a in (issue.get("assignees") or {}).get("nodes", []))
    return Card(ref, state, task, assignees, blockers, prs, _activity(issue))


def parse_board(pages: list[dict]) -> Board:
    """Every page of the board query, first page with the org-wide views."""
    cards = []
    for page in pages:
        for node in page["organization"]["projectV2"]["items"]["nodes"]:
            issue = node.get("content") or {}
            if issue.get("number"):  # draft items and PRs on the board are not cards
                cards.append(parse_card(node, issue))
    first = pages[0] if pages else {}
    open_prs = tuple(parse_pr(n) for n in (first.get("openPrs") or {}).get("nodes", []) if n)
    merged = tuple(parse_pr(n) for n in (first.get("merged") or {}).get("nodes", []) if n)
    off_board = tuple(Ref(n["repository"]["nameWithOwner"], n["number"], n.get("url", ""))
                      for n in (first.get("openIssues") or {}).get("nodes", [])
                      if n and _missing(n))
    return Board(tuple(cards), open_prs, merged, off_board)


def _missing(issue: dict) -> bool:
    """W7: an open org issue that is not on our project (the outer loop repo stays off)."""
    if issue["repository"]["nameWithOwner"].split("/")[-1] == config.OUTER_LOOP_REPO:
        return False
    projects = {n["project"]["number"] for n in (issue.get("projectItems") or {}).get("nodes", [])}
    return config.PROJECT_NUMBER not in projects
