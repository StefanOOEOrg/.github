"""Round 2+: back to Goal on a change request (#81), back to the own instance, a busy branch."""

import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from loop import starter
from loop.apply import apply
from loop.engine import Decisions
from loop.rules.dispatch import Dispatch, Start, dispatch
from loop.rules.status import transition
from loop.store import Store
from loop.tests.builders import LEAD, NOW, ago, board, card, pr, review
from loop.writer import GitHubWriter

CHANGES = "CHANGES_REQUESTED"
CLONE = Path("/ws/repo-a")
OTHER = "Branch: `b`\nAllowed files: `other.py`"


@pytest.mark.parametrize("prs, expected", [
    ([pr(review(LEAD, CHANGES, "h1"), head="h1")], "Goal"),  # change request on the head
    ([pr(review(LEAD, CHANGES, "h0"), head="h1")], None),  # on a superseded commit
    ([pr(review(LEAD, "APPROVED", "h1"), head="h1")], None),  # approved head
    ([pr(review(LEAD, CHANGES, "h1"), review(LEAD, CHANGES, "h2"), review(LEAD, CHANGES, "h3"),
         head="h3")], None),  # third change request: the round limit, the owner decides
    ([pr(review(LEAD, CHANGES, "h1"), head="h1", state="CLOSED")], None),  # PR no longer open
])
def test_change_request_on_the_head_sends_a_verify_card_to_goal(prs, expected):
    """#81: only the Lead's change request on the current head of an open PR, below the limit."""
    assert transition(card(status="Verify", prs=prs), verify_back_to_action=False) == expected


def run(*cards, jobs=frozenset()):
    """Dispatch with two instances."""
    with patch("loop.config.INSTANCES", ("dev-1", "dev-2")):
        return dispatch(board(*cards), set(jobs), NOW, lambda repo: None)


def test_round_two_waits_for_its_own_busy_instance():
    """D3: the branch is in the worktree of dev-2, so the card does not take the free dev-1."""
    round2 = card(1, "Goal", instance="dev-2", prs=[pr()])
    result = run(round2, jobs={"dev-2-repo-a-1"})
    assert not result.starts and [c.ref.number for c in result.waiting] == [1]


def test_round_two_starts_on_its_own_instance_once_free():
    """D3: its own instance is free: the card goes back to it."""
    result = run(card(1, "Goal", instance="dev-2", prs=[pr()]))
    assert [(s.card.ref.number, s.instance) for s in result.starts] == [(1, "dev-2")]


def test_round_one_takes_any_free_instance_and_the_start_knows_the_busy_ones():
    """Without an open PR the instance it once had is only a preference."""
    result = run(card(1, "Goal", instance="dev-2"), jobs={"dev-2-repo-a-9"})
    assert [(s.instance, s.busy) for s in result.starts] == [("dev-1", frozenset({"dev-2"}))]


def worktrees(*pairs):
    """A fake ``_git`` that lists these (path, branch) worktrees and records every call."""
    calls = []
    listing = "\n\n".join(f"worktree {p}\nHEAD 0\nbranch refs/heads/{b}" for p, b in pairs)

    def fake(*args):
        calls.append(args)
        return subprocess.CompletedProcess(args, 0, listing if "list" in args else "", "")
    fake.calls = calls
    return fake


def test_branch_held_by_a_busy_instance_waits(monkeypatch):
    """The branch is checked out by busy dev-2: BranchInUse, nothing removed."""
    fake = worktrees((CLONE / ".worktrees" / "dev-2", "wp/x"))
    monkeypatch.setattr(starter, "_git", fake)
    with pytest.raises(starter.BranchInUse):
        starter.free_branch(CLONE, "wp/x", CLONE / ".worktrees" / "dev-1", frozenset({"dev-2"}))
    assert not any("remove" in c for c in fake.calls)


def test_stale_worktree_of_an_idle_instance_is_removed(monkeypatch):
    """An idle instance's old worktree holds the branch: it is removed, the start goes on."""
    fake = worktrees((CLONE / ".worktrees" / "dev-2", "wp/x"))
    monkeypatch.setattr(starter, "_git", fake)
    starter.free_branch(CLONE, "wp/x", CLONE / ".worktrees" / "dev-1", frozenset())
    assert any("remove" in c and str(CLONE / ".worktrees" / "dev-2") in c for c in fake.calls)


@pytest.mark.parametrize("holder, error", [
    (CLONE, RuntimeError),  # the clone itself: a real failure for the owner
    (CLONE / ".worktrees" / "dev-1", None),  # the target: recreated anyway
    (None, None),  # nobody
])
def test_other_branch_holders(monkeypatch, holder, error):
    """Only a worktree of the engine's own instances is waited for or cleaned up."""
    monkeypatch.setattr(starter, "_git", worktrees(*([(holder, "wp/x")] if holder else [])))
    target = CLONE / ".worktrees" / "dev-1"
    if error:
        with pytest.raises(error):
            starter.free_branch(CLONE, "wp/x", target, frozenset())
    else:
        starter.free_branch(CLONE, "wp/x", target, frozenset())


def test_waiting_start_writes_nothing_and_comments_nothing(tmp_path, monkeypatch):
    """A branch in use is no failure: no status write, no "Not started" comment."""
    calls = []

    def busy(*_args):
        raise starter.BranchInUse("busy")
    monkeypatch.setattr(starter, "free_branch", busy)
    out = Decisions(dispatch=Dispatch([Start(card(1, "Goal", changed=ago(5)), "dev-1")]))
    writer = GitHubWriter(lambda args: calls.append(args) or "{}")
    lines, log = apply(out, writer, Store(tmp_path / "s.json"), NOW, True)
    assert not calls and not lines and not log
