"""D11: a failed start comments once, goes to the Lead, is skipped until the card changes."""

import pytest

from loop import starter
from loop.apply import apply
from loop.engine import decide
from loop.model import Activity, Task
from loop.parse import parse_card
from loop.rules.assignee import next_actor
from loop.rules.dispatch import dispatch
from loop.rules.failed_start import MARKER, failed_start_text, start_failed
from loop.scope import Scope
from loop.store import Store
from loop.tests.builders import DEV, LEAD, NOW, ORDER, OWNER, ago, board, card
from loop.tests.test_apply import recorder
from loop.tick import summary
from loop.writer import GitHubWriter

HELD = "branch wp/x is checked out in /tmp/docs126"


MARKED = Task(ORDER, last_comment=failed_start_text("preparing the worktree", HELD))


def failed(**extra) -> Activity:
    """The engine's failed-start comment 5 minutes ago, plus ``extra`` activity."""
    return Activity(**{"commented_by": LEAD, "commented_at": ago(5), **extra})


@pytest.mark.parametrize(("activity", "changed", "expected"), [
    (failed(), ago(60), True),
    (failed(assigned_by=LEAD, assigned_to=LEAD, assigned_at=ago(4)), ago(60), True),  # own
    (failed(edited_by=OWNER, edited_at=ago(1)), ago(60), False),
    (failed(), ago(1), False),  # status changed after the comment
    (failed(assigned_by=OWNER, assigned_to=DEV, assigned_at=ago(1)), ago(60), False),
    (failed(assigned_by=LEAD, assigned_to=DEV, assigned_at=ago(1)), ago(60), False),
    (Activity(), ago(60), False),
])
def test_skip_lasts_until_the_card_changes(activity, changed, expected):
    """Only the engine's own comment and its own assignment of the Lead keep the skip."""
    assert start_failed(card(126, activity=activity, changed=changed, task=MARKED)) is expected


def test_a_newer_comment_ends_the_skip():
    """The latest comment is no longer the engine's marker."""
    answered = card(126, activity=failed(commented_by=OWNER), task=Task(ORDER, last_comment="ok"))
    assert not start_failed(answered)


def test_failed_card_goes_to_the_lead_and_is_skipped():
    """A11 and the dispatcher: the next Goal card gets the instance."""
    stuck = card(126, activity=failed(), changed=ago(60), task=MARKED)
    assert next_actor(stuck) == LEAD
    starts = dispatch(board(stuck, card(127)), set(), NOW, lambda repo: None).starts
    assert [s.card.ref.number for s in starts] == [127]


def test_comment_names_the_holder_and_carries_the_marker():
    """The cause with the path of the worktree that holds the branch, and the skip marker."""
    text = failed_start_text("preparing the worktree", HELD)
    assert "/tmp/docs126" in text and text.endswith(MARKER)


def run_starts(cards, tmp_path, monkeypatch, failing=(126,)):
    """Decide and apply; the worktree of the ``failing`` cards cannot be prepared."""
    def prepare(item, instance, _busy):
        if item.ref.number in failing:
            raise RuntimeError(HELD)
        return f"/ws/{instance}", False
    monkeypatch.setattr(starter, "prepare_worktree", prepare)
    monkeypatch.setattr(starter, "create_job", lambda *args: None)
    rec = recorder()
    out = decide(board(*cards), set(), NOW, lambda repo: None)
    lines, log = apply(out, GitHubWriter(rec), Store(tmp_path / "s.json"), NOW, True)
    return rec, out, lines, log


def test_failed_start_comments_assigns_and_starts_the_next_card(tmp_path, monkeypatch):
    """One comment with marker, the Lead assigned, and #127 starts on the freed dev-1."""
    rec, out, lines, log = run_starts([card(126), card(127)], tmp_path, monkeypatch)
    comments = [c for c in rec.calls if "issues/126/comments" in c]
    assert len(comments) == 1 and MARKER in comments[0] and "/tmp/docs126" in comments[0]
    assert any("issues/126/assignees" in c and f"assignees[]={LEAD}" in c and "POST" in c
               for c in rec.calls)
    assert [s.card.ref.number for s in out.dispatch.started] == [127]
    assert [s.card.ref.number for s in out.dispatch.failed] == [126]
    assert log == ["dev-1: gestartet StefanOOEOrg/repo-a#127"]
    assert lines[0].startswith("Start fehlgeschlagen: StefanOOEOrg/repo-a#126")
    assert "1 start(s), 1 failed start(s)" in summary(Scope(None, "full"), out, len(lines))


def test_next_run_skips_the_failed_card_without_a_new_comment(tmp_path, monkeypatch):
    """The marker is the latest comment: no retry, no comment, #127 starts."""
    marked = card(126, assignees=[LEAD], activity=failed(), changed=ago(60), task=MARKED)
    rec, out, _, _ = run_starts([marked, card(127)], tmp_path, monkeypatch)
    assert not any("issues/126" in c for c in rec.calls)
    assert [s.card.ref.number for s in out.dispatch.started] == [127] and not out.dispatch.failed


def test_a_change_on_the_card_retries_the_start(tmp_path, monkeypatch):
    """After a newer comment the dispatcher tries it again, and it starts."""
    answered = card(126, assignees=[LEAD], changed=ago(60), activity=Activity(
        commented_by=OWNER, commented_at=ago(1)), task=Task(ORDER, last_comment="removed it"))
    _, out, lines, _ = run_starts([answered], tmp_path, monkeypatch, failing=())
    assert [s.card.ref.number for s in out.dispatch.started] == [126]
    assert not any(line.startswith("Start fehlgeschlagen") for line in lines)


def test_parse_reads_the_latest_comment_text():
    """The board query's latest comment body reaches ``Task.last_comment``."""
    issue = {"number": 126, "state": "OPEN", "repository": {"nameWithOwner": "o/r"},
             "comments": {"nodes": [{"createdAt": "2026-11-11T07:44:00Z",
                                     "author": {"login": LEAD}, "body": f"x\n{MARKER}"}]}}
    parsed = parse_card({"status": {"name": "Goal"}}, issue)
    assert MARKER in parsed.task.last_comment and parsed.activity.commented_by == LEAD
