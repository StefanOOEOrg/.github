"""Scope from HERMES_CRON_EVENT, and the local "already reported" store."""

import json
from datetime import timedelta

import pytest

from loop.rules.checks import Finding
from loop.scope import scope_of
from loop.store import Store
from loop.tests.builders import NOW

PREFIX = "This run was triggered by webhook event 'issues' on route 'loop' (not the schedule).\n\n"


def event(**signals):
    """A trigger context as Hermes passes it: a sentence, then the rendered JSON line."""
    base = {"event": "{event_type}", "action": "{action}", "repo": "{repository.full_name}",
            "issue": "{issue.number}"}
    return PREFIX + json.dumps({**base, **signals})


@pytest.mark.parametrize("context, card", [
    (None, None),  # hourly run or coalesced re-fire: full
    ("not json", None),
    (event(event="issue_comment", action="created", repo="O/r", issue="5"), ("O/r", 5)),
    (event(event="issues", action="opened", repo="O/r", issue="6"), ("O/r", 6)),
    (event(event="issues", action="closed", repo="O/r", issue="6"), None),  # may unblock a card
    (event(event="projects_v2_item", action="edited"), None),  # may start a card
    (event(event="pull_request", action="opened", repo="O/r"), None),
    (event(event="issue_comment", action="created", repo="O/r"), None),  # number unresolved
])
def test_scope_of(context, card):
    """Only events that cannot change another card narrow the run to one card."""
    assert scope_of(context).card == card


def test_notice_printed_once_then_repeated_after_an_hour(tmp_path):
    """REMIND_MINUTES: a still open notice comes again after 60 min."""
    store = Store(tmp_path / "s.json")
    found = [Finding("review:x", "Review wartet")]
    assert store.due_notices(found, NOW, full=True) == ["Review wartet"]
    assert not store.due_notices(found, NOW + timedelta(minutes=30), full=True)
    assert store.due_notices(found, NOW + timedelta(minutes=61), full=True) == [
        "Erinnerung: Review wartet"]


def test_once_notice_is_never_repeated_and_gone_keys_are_forgotten(tmp_path):
    """``once`` stays silent; a full run drops keys no longer due, a card run keeps them."""
    store = Store(tmp_path / "s.json")
    store.due_notices([Finding("orphan:x", "o", once=True), Finding("review:y", "r")], NOW, True)
    assert not store.due_notices([Finding("orphan:x", "o", once=True)], NOW + timedelta(hours=5),
                                 full=False)
    assert "review:y" in store.notices
    store.due_notices([], NOW, full=True)
    assert not store.notices


def test_one_time_comment_comes_back_after_its_reason_was_gone(tmp_path):
    """D12: once while the reason lasts; again after it went away and returned."""
    path = tmp_path / "s.json"
    store = Store(path)
    assert store.first_comment("u|blocked", NOW) and not store.first_comment("u|blocked", NOW)
    store.save(full=True)
    again = Store(path)
    again.save(full=True)  # a full run without that reason
    assert Store(path).first_comment("u|blocked", NOW)


def test_approve_reminder_at_most_every_24_hours(tmp_path):
    """W6: OWNER_REPEAT_HOURS."""
    store = Store(tmp_path / "s.json")
    assert store.reminder_due("k", NOW)
    assert not store.reminder_due("k", NOW + timedelta(hours=23))
    assert store.reminder_due("k", NOW + timedelta(hours=25))


def test_first_run_takes_over_the_old_watch_state(tmp_path):
    """Migration: notices the old watch already sent are not sent again."""
    (tmp_path / "github-watch-state.json").write_text(
        json.dumps({"postmerge:https://x/63": NOW.isoformat()}))
    (tmp_path / "dispatch-reported.json").write_text(
        json.dumps({"https://x/i1|blocked by #2": True}))
    (tmp_path / "approve-reminders.json").write_text(
        json.dumps({"https://x/7": {"head": "h1", "at": NOW.isoformat()}}))
    store = Store(tmp_path / "loop-state.json", legacy=tmp_path)
    assert not store.due_notices([Finding("postmerge:https://x/63", "p", once=True)], NOW, True)
    assert not store.first_comment("https://x/i1|blocked by #2", NOW)
    assert not store.reminder_due("remind:https://x/7@h1", NOW)
