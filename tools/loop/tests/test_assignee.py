"""assignee(card): A1..A10 and the blocker rules P1..P3, one row each."""

import pytest

from loop.model import Activity
from loop.rules.assignee import next_actor, plan, round_limit_pr
from loop.tests.builders import DEV, LEAD, OWNER, REPO, board, card, pr, review

BY_OWNER = Activity(assigned_by=OWNER, assigned_to=LEAD)
THREE_ROUNDS = [review(LEAD, "CHANGES_REQUESTED")] * 3


@pytest.mark.parametrize("given, expected", [
    (card(is_open=False), None),  # A1
    (card(status="Triage", assignees=[LEAD], activity=BY_OWNER), LEAD),  # A2
    (card(status="Verify", assignees=[LEAD], activity=BY_OWNER, prs=[pr()]), LEAD),  # A2 > A3
    (card(status="Goal", assignees=[LEAD], activity=BY_OWNER), DEV),  # A2 not on Goal
    (card(status="Verify", prs=[pr(requested=(LEAD,))]), LEAD),  # A3 review requested
    (card(status="Verify", prs=[pr(review(OWNER, "APPROVED"))]), LEAD),  # A3 merge
    (card(status="Verify", prs=[pr(review(LEAD, "APPROVED"))]), OWNER),  # A3 owner approves
    (card(status="Verify", prs=[pr(review(LEAD, "CHANGES_REQUESTED"))]), DEV),  # A3 changes
    (card(status="Verify", prs=[pr(*THREE_ROUNDS)]), OWNER),  # A3 round limit
    (card(status="Verify", prs=[pr()]), LEAD),  # A3 otherwise
    (card(status="Goal", body="no order"), LEAD),  # A4 refine
    (card(status="Action", assignees=[OWNER]), OWNER),  # A5 handed over as stuck
    (card(status="Goal"), DEV),  # A6
    (card(status="Action"), DEV),  # A6
    (card(status="Verify"), LEAD),  # A7 Verify without PR
    (card(status="Done"), OWNER),  # A8 open but Done
    (card(status=None), OWNER),  # A8 no status
    (card(status="Triage"), OWNER),  # A9 refined
    (card(status="Triage", body="question"), LEAD),  # A9 not refined
    (card(status="Triage", body="question", assignees=[OWNER]), OWNER),  # A9 owner holds it
    (card(status="Backlog"), None),  # A10
    (card(status="Backlog", assignees=[OWNER]), OWNER),  # A10 owner holds it
])
def test_next_actor(given, expected):
    """Exactly one rule decides; the first matching one wins."""
    assert next_actor(given) == expected


def test_parked_backlog_blocker_goes_to_the_owner():
    """P1: only the owner can pull a parked blocker, so both go to him."""
    wants = plan(board(card(1, "Goal", blocked_by=[2]), card(2, "Backlog")))
    assert wants == {(REPO, 1): OWNER, (REPO, 2): OWNER}


def test_blocker_missing_from_the_board_goes_to_the_owner():
    """P2: nobody else would see a blocker that is not on the board."""
    assert plan(board(card(1, "Goal", blocked_by=[99])))[(REPO, 1)] == OWNER


def test_blocked_card_follows_the_chain_to_its_end():
    """P3: a blocked card follows whoever acts on the end of its blocker chain."""
    wants = plan(board(card(1, "Goal", blocked_by=[2]), card(2, "Goal", blocked_by=[3]),
                       card(3, "Triage", body="question")))
    assert wants[(REPO, 1)] == LEAD


def test_dependency_cycle_ends():
    """P3: MAX_BLOCKER_CHAIN ends a cycle."""
    wants = plan(board(card(1, "Goal", blocked_by=[2]), card(2, "Goal", blocked_by=[1])))
    assert wants[(REPO, 1)] == DEV


def test_round_limit_pr_names_the_pr():
    """A3: the PR on which the Lead reached the round limit."""
    assert round_limit_pr(card(status="Verify", prs=[pr(*THREE_ROUNDS, number=12)])) == 12
    once = card(status="Verify", prs=[pr(review(LEAD, "CHANGES_REQUESTED"))])
    assert round_limit_pr(once) is None
