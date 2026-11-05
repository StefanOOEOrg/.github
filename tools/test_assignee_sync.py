"""Tests for the assignee rules, above all the blockers of the current iteration."""

import assignee_sync as sync
import pytest
from assignee_sync import DEV, LEAD, OWNER

REPO = "StefanOOEOrg/.github"


def card(number, status, blocked_by=(), body="Branch: `wp/x`", manual=None, state="OPEN"):
    """Build one project item as the project query returns it."""
    blockers = [{"number": n, "state": "OPEN", "repository": {"nameWithOwner": REPO}} for n in blocked_by]
    events = [{"actor": {"login": OWNER}, "assignee": {"login": manual}}] if manual else []
    return {
        "status": {"name": status} if status else None,
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


def pr(*states):
    """Build an open PR with the Lead's reviews in order."""
    reviews = [{"author": {"login": LEAD}, "state": state} for state in states]
    return {"number": 7, "state": "OPEN", "reviewRequests": {"nodes": []}, "reviews": {"nodes": reviews}}


@pytest.mark.parametrize("status, body, expected", [
    ("Triage", "not refined", LEAD),
    ("Triage", "Branch: `wp/x`", OWNER),
    ("Backlog", "Branch: `wp/x`", None),
    ("Goal", "Branch: `wp/x`", DEV),
    ("Action", "Branch: `wp/x`", DEV),
])
def test_status_rules(status, body, expected):
    assert wants(card(1, status, body=body))[1] == expected


def test_backlog_blocker_of_a_pulled_card_goes_to_the_product_owner():
    assert wants(card(1, "Goal", blocked_by=[2]), card(2, "Backlog")) == {1: OWNER, 2: OWNER}


def test_blocked_card_follows_whoever_acts_on_its_blocker():
    assert wants(card(1, "Goal", blocked_by=[2]), card(2, "Verify")) == {1: LEAD, 2: LEAD}


def test_blocker_chain_is_followed_to_its_end():
    result = wants(card(1, "Goal", blocked_by=[2]), card(2, "Goal", blocked_by=[3]), card(3, "Triage"))
    assert result == {1: OWNER, 2: OWNER, 3: OWNER}


def test_dependency_cycle_ends():
    result = wants(card(1, "Goal", blocked_by=[2]), card(2, "Goal", blocked_by=[1]))
    assert result == {1: DEV, 2: DEV}


def test_blocker_missing_from_the_board_goes_to_the_product_owner():
    assert wants(card(1, "Goal", blocked_by=[99]))[1] == OWNER


def test_backlog_card_blocked_by_another_stays_with_nobody():
    assert wants(card(1, "Backlog", blocked_by=[2]), card(2, "Action"))[1] is None


def test_manual_assignment_keeps_a_blocker_with_the_chosen_person():
    result = wants(card(1, "Goal", blocked_by=[2]), card(2, "Backlog", manual=LEAD))
    assert result[2] == LEAD


def test_manual_assignment_wins_on_verify():
    item = card(1, "Verify", manual=LEAD)
    item["content"]["closedByPullRequestsReferences"]["nodes"] = [pr("APPROVED")]
    assert wants(item)[1] == LEAD


def test_change_request_goes_to_the_developer():
    item = card(1, "Verify")
    item["content"]["closedByPullRequestsReferences"]["nodes"] = [pr("CHANGES_REQUESTED")]
    assert wants(item)[1] == DEV


def test_third_change_request_goes_to_the_product_owner():
    item = card(1, "Verify")
    item["content"]["closedByPullRequestsReferences"]["nodes"] = [pr(*["CHANGES_REQUESTED"] * 3)]
    assert wants(item)[1] == OWNER
    assert sync.round_limit_reached(item["content"]) == 7


def test_approval_after_three_rounds_is_no_round_limit():
    item = card(1, "Verify")
    item["content"]["closedByPullRequestsReferences"]["nodes"] = [pr(*["CHANGES_REQUESTED"] * 3, "APPROVED")]
    assert sync.round_limit_reached(item["content"]) is None


@pytest.mark.parametrize("status", [None, "Done"])
def test_open_item_outside_the_flow_goes_to_the_product_owner(status):
    assert wants(card(1, status))[1] == OWNER


def test_closed_item_has_no_assignee():
    assert wants(card(1, "Done", state="CLOSED"))[1] is None
