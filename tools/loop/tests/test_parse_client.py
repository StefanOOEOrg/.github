"""parse + client against the anonymized fixture of the real board (captured 7.11.2026)."""

import json
from datetime import date
from pathlib import Path

import pytest

from loop.github_client import GitHubClient, GitHubError
from loop.model import Task
from loop.parse import parse_board
from loop.rules.assignee import plan
from loop.rules.status import transition

FIXTURE = Path(__file__).parent / "fixtures" / "board.json"


@pytest.fixture(name="pages")
def fixture_pages():
    """The raw pages of the board query, anonymized."""
    return json.loads(FIXTURE.read_text())


def test_fixture_parses_into_cards_in_board_order(pages):
    """All 23 items of the real board become cards."""
    board = parse_board(pages)
    assert len(board.cards) == 23
    assert {c.state.status for c in board.cards} <= {"Backlog", "Done"}
    assert all(c.ref.repo.startswith("StefanOOEOrg/") for c in board.cards)


def test_rules_run_on_the_real_board_without_surprises(pages):
    """Closed cards get nobody (A1) and at most the move to Done."""
    board = parse_board(pages)
    wants = plan(board)
    assert all(wants[c.key] is None for c in board.cards if not c.state.is_open)
    assert all(transition(c, verify_back_to_action=False) in (None, "Done") for c in board.cards)


def test_client_pages_until_the_last(pages):
    """One page without a next page is the whole board; the first page reads the org views."""
    calls = []

    def run(args):
        calls.append(args)
        return json.dumps({"data": pages[0]})

    assert len(GitHubClient(run).board_pages(date(2026, 11, 7))) == 1
    assert "first=true" in calls[0]


def test_client_raises_on_graphql_errors():
    """A GraphQL error answer is an error, not an empty board."""
    client = GitHubClient(lambda args: json.dumps({"errors": [{"message": "x"}]}))
    with pytest.raises(GitHubError):
        client.board_pages(date.today())


@pytest.mark.parametrize("body, order, files", [
    ("Branch: `wp/x`\nAllowed files: `a.py` `b/*`", True, ("a.py", "b/*")),
    ("Branch: `wp/x` (base: `dev`)", False, ()),
    ("nothing", False, ()),
])
def test_task_order(body, order, files):
    """The task order needs the Branch and the Allowed files line."""
    task = Task(body)
    assert task.has_order is order and task.allowed_files == files
