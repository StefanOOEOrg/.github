"""dispatch(board): D1, D3..D9, built for n instances."""

from unittest.mock import patch

import pytest

from loop.rules.dispatch import dispatch, overlaps
from loop.tests.builders import NOW, OWNER, ago, board, card, pr

ALL_WRITE = {}.get  # every repo: both bots can write
OTHER = "Branch: `b`\nAllowed files: `other.py`"
SRC = "Branch: `a`\nAllowed files: `src/*`"


def starts(result):
    """(number, instance) of every start."""
    return [(s.card.ref.number, s.instance) for s in result.starts]


def run(*cards, instances=("dev-1",), access=ALL_WRITE):
    """Dispatch these cards with no developer job scheduled."""
    with patch("loop.config.INSTANCES", instances):
        return dispatch(board(*cards), set(), NOW, access)


def test_first_startable_goal_card_starts_on_the_free_instance():
    """D1, D3: the first Goal card in board order takes the free instance."""
    assert starts(run(card(1, "Goal"), card(2, "Goal"))) == [(1, "dev-1")]


def test_one_start_per_free_instance_with_n_instances():
    """D1: built for n instances, one start per free instance."""
    result = run(card(1, "Goal"), card(2, "Goal", body=OTHER), instances=("dev-1", "dev-2"))
    assert starts(result) == [(1, "dev-1"), (2, "dev-2")]


def test_busy_instance_waits():
    """D1: a running Action card holds its instance."""
    result = run(card(1, "Action", instance="dev-1", changed=ago(1)), card(2, "Goal"))
    assert not starts(result) and [c.ref.number for c in result.waiting] == [2]


def test_stuck_action_card_frees_its_instance():
    """D2: a stuck Action card no longer holds its instance."""
    stuck = card(1, "Action", instance="dev-1", changed=ago(20))
    assert starts(run(stuck, card(2, "Goal"))) == [(2, "dev-1")]


def test_previous_instance_is_preferred():
    """D3: a card goes back to the instance it had, if that one is free."""
    result = run(card(1, "Goal", instance="dev-2"), instances=("dev-1", "dev-2"))
    assert starts(result) == [(1, "dev-2")]


@pytest.mark.parametrize("given, reason", [
    (card(1, "Goal", issue_type="Feature"), "a feature is never started"),  # D4
    (card(1, "Goal", blocked_by=[5]), "blocked by #5"),  # D6
    (card(1, "Goal", body="no order"), "no `Branch:`"),  # D7
])
def test_card_that_cannot_start_gets_its_reason(given, reason):
    """D4, D6, D7: no start, the reason is reported."""
    result = run(given)
    assert not starts(result) and reason in result.blocked[0][1]


def test_round_limit_card_held_by_the_owner_is_skipped():
    """D5: the owner decides, the dispatcher stays silent."""
    result = run(card(1, "Goal", assignees=[OWNER], prs=[pr()]))
    assert not starts(result) and not result.blocked and not result.waiting


def test_overlapping_files_wait_silently():
    """D8: overlapping Allowed files in the same repo wait for their turn."""
    running = card(1, "Action", instance="dev-1", changed=ago(1), body=SRC)
    result = run(running, card(2, "Goal"), instances=("dev-1", "dev-2"))
    assert not starts(result) and [c.ref.number for c in result.waiting] == [2]


def test_missing_write_access_is_reported():
    """D9: a bot without write access stops the start with a reason."""
    result = run(card(1, "Goal"), access=lambda repo: f"StefanOOEDevBot cannot write to {repo}")
    assert not starts(result) and "cannot write" in result.blocked[0][1]


@pytest.mark.parametrize("first, second, expected", [
    (["src/a.py"], ["src/a.py"], True), (["src/*"], ["src/a.py"], True),
    (["src/a.py"], ["src/*"], True), (["src/a.py"], ["docs/b.md"], False)])
def test_overlaps(first, second, expected):
    """D8: equal paths and globs in both directions overlap."""
    assert overlaps(first, second) is expected
