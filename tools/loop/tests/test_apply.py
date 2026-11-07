"""decide() + apply(): the writes the engine makes, against a recording GitHub fake."""

import json
import subprocess

import pytest

from loop import starter
from loop.access import access_checker
from loop.apply import apply
from loop.engine import decide
from loop.rules.checks import Finding
from loop.store import Store
from loop.tests.builders import DEV, LEAD, NOW, OWNER, ago, board, card, pr, review
from loop.writer import GitHubWriter

FIELDS = {"data": {"organization": {"projectV2": {"id": "P", "fields": {"nodes": [
    {"id": "FS", "name": "Status", "options": [{"id": f"o{s}", "name": s} for s in
                                               ("Triage", "Goal", "Action", "Verify", "Done")]},
    {"id": "FI", "name": "Instance", "options": [{"id": "odev-1", "name": "dev-1"}]}]}}}}}


def recorder():
    """Stands in for gh: answers the field query, records every other call in ``.calls``."""
    calls = []

    def fake_gh(args):
        if "query=" in " ".join(args) and "fields(first" in " ".join(args):
            return json.dumps(FIELDS)
        calls.append(" ".join(args))
        return json.dumps({"id": "NEW"})
    fake_gh.calls = calls
    return fake_gh


def run(*cards, store_dir, dry=False):
    """Decide over the board and apply against a recorder; return (recorder, lines)."""
    rec = recorder()
    out = decide(board(*cards), set(), NOW, lambda repo: None)
    store = Store(store_dir / "s.json")
    lines, _ = apply(out, GitHubWriter(rec, dry_run=dry), store, NOW, True)
    store.save(full=True)
    return rec, lines


def test_status_and_assignee_writes(tmp_path):
    """Action with a PR -> Verify; the PR's reviewer (Lead) becomes the only assignee."""
    moved = card(2, "Action", assignees=[DEV], prs=[pr(requested=(LEAD,))])
    rec, _ = run(moved, store_dir=tmp_path)
    joined = "\n".join(rec.calls)
    assert "o=oVerify" in joined
    assert "DELETE" in joined and f"assignees[]={DEV}" in joined and f"assignees[]={LEAD}" in joined


def test_nothing_to_do_means_no_write(tmp_path):
    """A card already as it should be causes no call at all."""
    rec, lines = run(card(1, "Backlog"), store_dir=tmp_path)
    assert not rec.calls and not lines


def test_round_limit_comment_once(tmp_path):
    """A3: handing a card to the owner at the round limit comments once."""
    three = [review(LEAD, "CHANGES_REQUESTED")] * 3
    limited = card(3, "Verify", assignees=[DEV], prs=[pr(*three)])
    rec, _ = run(limited, store_dir=tmp_path)
    assert sum("round limit reached" in c for c in rec.calls) == 1
    rec, _ = run(limited, store_dir=tmp_path)
    assert not any("round limit" in c for c in rec.calls)


def test_stuck_card_is_handed_over(tmp_path):
    """D2: comment and assign the owner."""
    rec, _ = run(card(4, "Action", assignees=[DEV], changed=ago(30)), store_dir=tmp_path)
    assert any("Stuck:" in c for c in rec.calls)
    assert any(f"POST repos/StefanOOEOrg/repo-a/issues/4/assignees -f assignees[]={OWNER}" in c
               for c in rec.calls)


def test_dry_run_writes_nothing(tmp_path):
    """--dry-run: decisions logged, no call made."""
    rec, _ = run(card(2, "Action", prs=[pr()]), store_dir=tmp_path, dry=True)
    assert not rec.calls


def test_start_reverts_to_goal_when_the_job_cannot_be_created(tmp_path, monkeypatch):
    """D10 / #57: no Action without a job."""
    rec = recorder()
    monkeypatch.setattr(starter, "prepare_worktree", lambda c, i: ("/tmp/wt", False))

    def fail(*args, **kwargs):
        raise subprocess.CalledProcessError(1, "hermes", stderr="boom")
    monkeypatch.setattr(starter, "create_job", fail)
    out = decide(board(card(5, "Goal")), set(), NOW, lambda repo: None)
    lines, log = apply(out, GitHubWriter(rec), Store(tmp_path / "s.json"), NOW, True)
    statuses = [c for c in rec.calls if "o=o" in c]
    assert statuses[-1].endswith("o=oGoal") and not log and not lines
    assert any("the start failed while creating the developer job" in c for c in rec.calls)


def test_new_issue_is_added_on_triage(tmp_path):
    """W7: added, Triage, one line for the Lead."""
    rec = recorder()
    out = decide(board(), set(), NOW, lambda repo: None)
    out.board.add = [card(9).ref]
    lines, _ = apply(out, GitHubWriter(rec), Store(tmp_path / "s.json"), NOW, True)
    assert any("item-add" in c for c in rec.calls) and lines[0].startswith("Neu im Project")


@pytest.mark.parametrize("lead, dev, expected", [
    ({"push": True}, "write", None), ({"push": False}, "write", "the Lead bot cannot write"),
    ({"push": True}, "read", "StefanOOEDevBot cannot write")])
def test_access(lead, dev, expected):
    """D9: both bots need write access."""
    answers = iter([json.dumps({"permissions": lead}), json.dumps({"permission": dev})])
    result = access_checker(lambda args: next(answers))("O/r")
    assert result is None if expected is None else expected in result


def test_notices_go_to_stdout_lines(tmp_path):
    """Notices are the Lead's lines."""
    out = decide(board(), set(), NOW, lambda repo: None)
    out.notices = [Finding("review:x", "Inbox – Review wartet")]
    lines, _ = apply(out, GitHubWriter(recorder()), Store(tmp_path / "s.json"), NOW, True)
    assert lines == ["Inbox – Review wartet"]
