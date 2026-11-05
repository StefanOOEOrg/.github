"""Tests for the assignee rules, above all the blockers of the current iteration."""

from datetime import date, timedelta

import pytest

import assignee_sync as sync
from assignee_sync import DEV, LEAD, OWNER

REPO = "StefanOOEOrg/.github"
TODAY = date(2026, 11, 5)
ITERATION = {"startDate": "2026-10-31", "duration": 14}


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    """Freeze the calendar day the iteration checks use."""
    monkeypatch.setattr(sync, "vienna_today", lambda: TODAY)


def card(number, status, iteration=ITERATION, blocked_by=(), body="Branch: `wp/x`", manual=None, state="OPEN"):
    """Build one project item as the project query returns it."""
    blockers = [{"number": n, "state": "OPEN", "repository": {"nameWithOwner": REPO}} for n in blocked_by]
    events = [{"actor": {"login": OWNER}, "assignee": {"login": manual}}] if manual else []
    return {
        "status": {"name": status} if status else None,
        "iteration": iteration,
        "content": {
            "number": number, "state": state, "body": body, "issueType": {"name": "Task"},
            "subIssues": {"totalCount": 0}, "blockedBy": {"nodes": blockers},
            "repository": {"nameWithOwner": REPO, "viewerPermission": "WRITE"},
            "assignees": {"nodes": [{"login": manual}] if manual else []},
            "timelineItems": {"nodes": events}, "closedByPullRequestsReferences": {"nodes": []},
        },
    }


def wants(*items):
    """Return the planned actor per issue number."""
    return {key[1]: actor for key, actor in sync.plan(list(items)).items()}


@pytest.mark.parametrize("status, body, expected", [
    ("Triage", "not refined", LEAD),
    ("Triage", "Branch: `wp/x`", OWNER),
    ("Backlog", "Branch: `wp/x`", LEAD),
    ("Ready", "Branch: `wp/x`", DEV),
    ("In Progress", "Branch: `wp/x`", DEV),
])
def test_status_rules(status, body, expected):
    assert wants(card(1, status, body=body))[1] == expected


def test_backlog_outside_the_iteration_waits_for_nobody_in_particular():
    assert wants(card(1, "Backlog", iteration=None))[1] is None


def test_blocker_outside_the_iteration_goes_to_the_product_owner():
    result = wants(card(1, "Backlog", blocked_by=[2]), card(2, "Backlog", iteration=None))
    assert result == {1: OWNER, 2: OWNER}


def test_blocked_card_follows_whoever_acts_on_its_blocker():
    assert wants(card(1, "Backlog", blocked_by=[2]), card(2, "In Progress")) == {1: DEV, 2: DEV}


def test_blocker_chain_is_followed_to_its_end():
    result = wants(card(1, "Backlog", blocked_by=[2]), card(2, "Backlog", blocked_by=[3]), card(3, "Ready"))
    assert result == {1: DEV, 2: DEV, 3: DEV}


def test_dependency_cycle_ends():
    result = wants(card(1, "Backlog", blocked_by=[2]), card(2, "Backlog", blocked_by=[1]))
    assert result == {1: LEAD, 2: LEAD}


def test_blocker_missing_from_the_project_leaves_the_card_with_the_lead():
    assert wants(card(1, "Backlog", blocked_by=[99]))[1] == LEAD


def test_manual_assignment_wins_over_a_blocker():
    assert wants(card(1, "Backlog", blocked_by=[2], manual=LEAD), card(2, "Ready"))[1] == LEAD


def test_manual_assignment_keeps_a_blocker_with_the_chosen_person():
    result = wants(card(1, "Backlog", blocked_by=[2]), card(2, "Backlog", iteration=None, manual=LEAD))
    assert result[2] == LEAD


@pytest.mark.parametrize("status", [None, "Done"])
def test_open_item_outside_the_flow_goes_to_the_product_owner(status):
    assert wants(card(1, status))[1] == OWNER


def test_closed_item_has_no_assignee():
    assert wants(card(1, "Done", state="CLOSED"))[1] is None


def test_finished_iteration_counts_as_outside():
    past = {"startDate": str(TODAY - timedelta(days=30)), "duration": 14}
    assert wants(card(1, "Backlog", iteration=past))[1] is None
