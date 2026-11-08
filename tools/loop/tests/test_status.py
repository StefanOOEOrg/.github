"""status(card): one test per transition of the state machine (design doc, Zustandsautomat)."""

import pytest

from loop.rules.status import archive_due, close_due, transition
from loop.tests.builders import LEAD, NOW, ago, card, pr, review

DAY = 24 * 60


@pytest.mark.parametrize("given, expected", [
    (card(status=None), "Triage"),  # item added to the project
    (card(status="Done", changed=ago(60), reopened_at=ago(5)), "Triage"),  # reopened
    (card(status="Done", changed=ago(5), reopened_at=ago(60)), None),  # by hand: closed instead
    (card(status="Done", changed=ago(5)), None),  # by hand, never reopened
    (card(status="Action", prs=[pr(requested=(LEAD,))]), "Verify"),  # PR linked, review asked
    (card(status="Action", changed=ago(60), prs=[pr(review(LEAD, "APPROVED", minutes_ago=5))]),
     "Verify"),  # reviewed since the start
    (card(status="Action", prs=[pr()]), None),  # round 2: the PR is open, the round is not done
    (card(status="Action", changed=ago(5), prs=[pr(review(LEAD, "CHANGES_REQUESTED",
                                                       minutes_ago=60))]), None),  # old review
    (card(status="Verify", is_open=False), "Done"),  # issue closed
    (card(status="Action", is_open=False), "Done"),  # closed from anywhere
    (card(status="Done", is_open=False), None),
    (card(status="Triage"), None),  # hand transitions stay the owner's
    (card(status="Backlog"), None),
    (card(status="Goal"), None),  # Goal -> Action is the dispatcher's start, not status()
    (card(status="Action"), None),  # no PR yet
    (card(status="Verify", prs=[pr()]), None),
])
def test_transition(given, expected):
    """Every controller transition, and no move of a hand-set status."""
    assert transition(given, verify_back_to_action=False) == expected


@pytest.mark.parametrize("prs, switch, expected", [
    ([pr(state="CLOSED")], True, "Action"),  # proposal: PR closed without merge
    ([pr(state="CLOSED")], False, None),  # switch off: no change
    ([pr(state="MERGED")], True, None),  # merged: the issue closes, Done follows
    ([], True, None),  # Verify without any PR: a check, not a transition
])
def test_verify_back_to_action_only_behind_the_switch(prs, switch, expected):
    """Verify -> Action is a proposal and stays off unless switched on."""
    assert transition(card(status="Verify", prs=prs), verify_back_to_action=switch) == expected


@pytest.mark.parametrize("days, expected", [(13, False), (14, True), (30, True)])
def test_archive_after_14_days_closed(days, expected):
    """A closed Done card is archived after 14 days."""
    closed = card(status="Done", is_open=False, closed_at=ago(days * DAY))
    assert archive_due(closed, NOW) is expected


def test_open_done_card_is_not_archived():
    """An open card on Done is a gap for the owner, not an archive case."""
    assert archive_due(card(status="Done", closed_at=ago(30 * DAY)), NOW) is False


@pytest.mark.parametrize("given, expected", [
    (card(status="Done", changed=ago(5)), True),  # moved to Done by hand
    (card(status="Done", changed=ago(5), reopened_at=ago(60)), True),  # reopened long before
    (card(status="Done", changed=ago(60), reopened_at=ago(5)), False),  # reopened: Triage
    (card(status="Done", is_open=False), False),  # already closed
    (card(status="Verify"), False),
])
def test_close_issue_moved_to_done_by_hand(given, expected):
    """Done + open: the latest reopen decides between reopened (Triage) and closing the issue."""
    assert close_due(given) is expected
