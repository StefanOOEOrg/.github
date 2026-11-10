"""Fixes from the outer-loop issues #66, #72, #75, #80 and #84."""

import json
import subprocess
from datetime import UTC, datetime

import pytest

from loop import github_client, tick
from loop.apply import _stuck_text
from loop.engine import Decisions
from loop.github_client import GitHubClient, GitHubError, NotFound, OffProject
from loop.model import Activity, Ref
from loop.parse import parse_board
from loop.rules.checks import is_stuck
from loop.rules.notices import card_notices, triage_new
from loop.scope import Scope
from loop.tests.builders import LEAD, NOW, OWNER, ago, card, pr

ONE = Scope(("O/r", 5), "issues.opened")


def failing_gh(stderr: str, calls: list):
    """A subprocess.run stand-in that fails like gh with this stderr."""
    def run(args, **_):
        calls.append(args)
        raise subprocess.CalledProcessError(1, ["gh"], stderr=stderr)
    return run


def test_unresolvable_subject_is_not_retried(monkeypatch):
    """#66: 'Could not resolve' is the same on every attempt: NotFound at once."""
    calls = []
    stderr = "gh: Could not resolve to a Repository"
    monkeypatch.setattr(subprocess, "run", failing_gh(stderr, calls))
    with pytest.raises(NotFound):
        github_client.run_gh(["api", "graphql"])
    assert len(calls) == 1


def test_unresolvable_subject_skips_the_one_card_run():
    """#66: the one-card run decides nothing and does not fail."""
    def run(args):
        raise NotFound("gh: Could not resolve to a Repository with the name 'O/r'")
    out = tick.decide_scope(GitHubClient(run), ONE, datetime(2026, 11, 8, tzinfo=UTC))
    assert not out.board.add and not out.board.status and not out.starts


def test_transport_error_still_fails_the_run(monkeypatch):
    """#66: a real GitHub error after the retries is still an error of the run."""
    monkeypatch.setattr(subprocess, "run", failing_gh("HTTP 502", []))
    monkeypatch.setattr(github_client.time, "sleep", lambda s: None)
    with pytest.raises(GitHubError) as raised:
        tick.decide_scope(GitHubClient(), ONE, datetime(2026, 11, 8, tzinfo=UTC))
    assert not isinstance(raised.value, NotFound)


def test_summary_counts_closed_issues():
    """#72: a run that closed issues does not read like a quiet run."""
    out = Decisions()
    out.board.close = [card(1, "Done"), card(2, "Done")]
    assert "2 close(s)" in tick.summary(Scope(None, "full"), out, 0)


@pytest.mark.parametrize("requested, minutes, expected", [
    ((), 20, True),  # open PR, no review request, no job, 15 min passed
    ((LEAD,), 20, False),  # the round was handed to review
    ((), 10, False),  # too early
])
def test_action_with_open_pr_but_no_review_request(requested, minutes, expected):
    """#75: D2 also watches Action with an open PR that never asked for review."""
    given = card(1, "Action", changed=ago(minutes), prs=[pr(requested=requested)])
    assert is_stuck(given, set(), NOW) is expected


def test_stuck_comment_names_what_is_missing():
    """#75: the handover says the review request is missing, not the PR."""
    assert "review request on PR #7" in _stuck_text(card(1, "Action", prs=[pr()]))
    assert "without a PR" in _stuck_text(card(1, "Action"))


def test_merged_work_on_goal_is_not_sent_to_refinement():
    """#80: a merged linked PR turns the refinement request into a question."""
    keys = [f.key.split(":")[0] for f in card_notices(card(1, "Goal", body="",
                                                          prs=[pr(state="MERGED")]))]
    assert keys == ["merged-on-goal"]


def test_unmerged_goal_card_is_still_refined():
    """#80: without a merged PR the Lead refines as before."""
    keys = [f.key.split(":")[0] for f in card_notices(card(1, "Goal", body="",
                                                          prs=[pr(state="CLOSED")]))]
    assert keys == ["refine"]


def lead_card(author: str):
    """An unrefined Triage card with the Lead's turn, filed by ``author``."""
    given = card(1, "Triage", body="")
    return given.__class__(Ref(given.ref.repo, 1, given.ref.url, author=author), given.state,
                           given.task, given.assignees, (), (), Activity())


def test_no_triage_notice_for_the_leads_own_card():
    """#84: the Lead is not told about a card he filed himself."""
    assert triage_new(lead_card(LEAD)) is None
    assert triage_new(lead_card(OWNER)) is not None


def test_author_is_parsed_for_cards_off_the_board():
    """#84: the off-board view carries the author, so apply can skip the Lead's own cards."""
    node = {"number": 3, "url": "u", "author": {"login": LEAD},
            "repository": {"nameWithOwner": "O/r"}, "projectItems": {"nodes": []}}
    page = {"organization": {"projectV2": {"items": {"nodes": []}}},
            "openIssues": {"nodes": [node]}}
    assert parse_board([page]).off_board[0].author == LEAD


def test_issue_off_the_project_carries_its_author():
    """#84: the one-card run adds a missing issue with its author."""
    issue = {"__typename": "Issue", "number": 5, "url": "u", "state": "OPEN",
             "author": {"login": LEAD}, "repository": {"nameWithOwner": "O/r"},
             "projectItems": {"nodes": []}}
    data = {"data": {"rateLimit": {}, "repository": {"issueOrPullRequest": issue}}}
    client = GitHubClient(lambda args: json.dumps(data))
    with pytest.raises(OffProject) as raised:
        client.card("O/r", 5)
    assert raised.value.ref.author == LEAD
    out = tick.decide_scope(client, ONE, datetime(2026, 11, 8, tzinfo=UTC))
    assert out.board.add[0].author == LEAD
