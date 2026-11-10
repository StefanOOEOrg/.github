"""checks (D2, W5, W6, W12, W13) and inbox notices (W1..W4, W8, W9, W11, W15)."""

import pytest

from loop.model import Activity
from loop.rules.checks import approve_reminder, card_findings, is_stuck, orphan_pr
from loop.rules.notices import card_notices, owner_review_due, post_merge, pr_notices
from loop.tests.builders import LEAD, NOW, OWNER, ago, card, pr, review

GITHUB = "StefanOOEOrg/.github"


@pytest.mark.parametrize("given, jobs, expected", [
    (card(1, "Action", changed=ago(20)), set(), True),  # 15 min passed
    (card(1, "Action", changed=ago(10)), set(), False),  # too early
    (card(1, "Action", changed=ago(20)), {"dev-1-repo-a-1"}, False),  # job scheduled
    (card(1, "Action", changed=ago(20), prs=[pr(requested=(LEAD,))]), set(), False),  # in review
    (card(1, "Action", changed=ago(20)), None, False),  # job list unknown
    (card(1, "Goal", changed=ago(20)), set(), False),
])
def test_is_stuck(given, jobs, expected):
    """D2: Action without PR and without job for 15 min since it got Action."""
    assert is_stuck(given, jobs, NOW) is expected


def test_board_contradictions():
    """W12: PR on a Triage card; W13: Verify without PR."""
    assert "Triage-Karte" in card_findings(card(1, "Triage", prs=[pr()]))[0].text
    assert "Verify ohne" in card_findings(card(1, "Verify"))[0].text
    assert not card_findings(card(1, "Verify", prs=[pr()]))


def test_orphan_pr_without_closing_line():
    """W5: once, and never for the outer loop repository."""
    assert orphan_pr(pr(body="no link")).once is True
    assert orphan_pr(pr(body="Closes #3")) is None
    assert orphan_pr(pr(body="no link", repo=GITHUB)) is None


@pytest.mark.parametrize("given, expected", [
    (pr(review(LEAD, "APPROVED", minutes_ago=180), requested=(OWNER,)), True),
    (pr(review(LEAD, "APPROVED", minutes_ago=60), requested=(OWNER,)), False),  # under 2 h
    (pr(review(LEAD, "APPROVED", minutes_ago=180)), False),  # owner not requested
    (pr(review(LEAD, "APPROVED", "old", 180), requested=(OWNER,)), False),  # not the head
    (pr(review(LEAD, "APPROVED", minutes_ago=180), requested=(OWNER,), ci="FAILURE"), False),
])
def test_approve_reminder(given, expected):
    """W6: Lead approved the head, CI green, owner requested, 2 h passed."""
    assert (approve_reminder(given, NOW) is not None) is expected


@pytest.mark.parametrize("given, prefix", [
    (pr(requested=(LEAD,)), "review:"),  # W1
    (pr(review(OWNER, "APPROVED")), "merge:"),  # W2
    (pr(review(OWNER, "CHANGES_REQUESTED")), "changes:"),  # W3 on the head
])
def test_pr_notices(given, prefix):
    """W1..W3: exactly the notice the PR state asks for."""
    assert [f.key.split(":")[0] + ":" for f in pr_notices(given)] == [prefix]


def test_owner_changes_on_an_old_head_are_not_repeated():
    """W3: only on the current head."""
    assert not pr_notices(pr(review(OWNER, "CHANGES_REQUESTED", commit="old")))


def test_card_notices():
    """W8 owner commented, W9 owner assigned the Lead, W11 Goal without task order."""
    commented = card(1, "Triage", assignees=[LEAD],
                     activity=Activity(commented_by=OWNER, commented_at=NOW))
    assigned = card(2, "Triage", assignees=[LEAD], activity=Activity(OWNER, LEAD, ago(5)))
    answered = card(3, "Triage", assignees=[LEAD],
                    activity=Activity(OWNER, LEAD, ago(5), LEAD, ago(1)))
    assert card_notices(commented)[0].key.startswith("owner-comment:")
    assert card_notices(assigned)[0].key.startswith("owner-assigned:")
    assert not card_notices(answered)
    assert card_notices(card(4, "Goal", body="no order"))[0].key.startswith("refine:")
    assert not card_notices(card(5, "Goal", body="no order", issue_type="Feature"))


def test_post_merge_is_once():
    """W15: reported a single time."""
    assert post_merge(pr(state="MERGED", repo=GITHUB)).once is True


def test_new_triage_card_is_reported_once_to_the_lead():
    """A card put on Triage by hand (not by the engine) tells the Lead once."""
    new = card(5, "Triage", body="question")
    assert [f.key for f in card_notices(new) if f.once] == ["triage-new:https://x/i5"]


@pytest.mark.parametrize("given", [
    card(5, "Triage"),  # refined already
    card(5, "Triage", body="q", assignees=[OWNER],
         activity=Activity(assigned_by=OWNER, assigned_to=OWNER, assigned_at=ago(1))),  # held
    card(5, "Triage", body="q", activity=Activity(assigned_by=OWNER, assigned_to=LEAD,
                                                  assigned_at=ago(1))),  # W9 tells him
])
def test_no_triage_new_notice_when_not_needed(given):
    """Refined, held by the owner, or already assigned to the Lead: no extra notice."""
    assert not [f for f in card_notices(given) if f.key.startswith("triage-new:")]


def test_owner_comment_in_triage_reaches_the_lead():
    """Ping-pong: the owner's comment in Triage is the Lead's turn, whoever is assigned."""
    act = Activity(commented_by=OWNER, commented_at=ago(1), edited_by=LEAD, edited_at=ago(9))
    given = card(6, "Triage", assignees=[OWNER], activity=act)
    assert any(f.text.startswith("Inbox – Stefan hat kommentiert") for f in card_notices(given))


@pytest.mark.parametrize("given, expected", [
    (pr(review(LEAD, "APPROVED")), True),  # Lead approved the head, owner not asked
    (pr(review(LEAD, "APPROVED"), requested=(OWNER,)), False),  # already asked
    (pr(review(LEAD, "APPROVED", commit="old")), False),  # approval on an older head
    (pr(review(LEAD, "CHANGES_REQUESTED")), False),
    (pr(review(OWNER, "CHANGES_REQUESTED", minutes_ago=30),
        review(LEAD, "APPROVED", minutes_ago=5)), True),  # new approval after his change request
    (pr(review(LEAD, "APPROVED", minutes_ago=30), review(OWNER, "APPROVED", minutes_ago=5)),
     False),  # the owner reviewed since
    (pr(review(LEAD, "APPROVED"), repo="StefanOOEOrg/.github"), False),  # outer loop
])
def test_owner_review_is_requested_by_the_engine(given, expected):
    """W4: the engine asks the owner once the Lead approved the current head."""
    assert owner_review_due(given) is expected
