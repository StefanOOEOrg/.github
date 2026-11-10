"""Job watch (a full run once a developer job ended) and a comment on a PR in a one-card scope."""

import json
from datetime import UTC, datetime

import pytest

from loop import jobwatch, tick
from loop.github_client import GitHubClient, NotAnIssue
from loop.scope import Scope
from loop.sources.jobwatch import ended_jobs


def test_first_look_only_remembers(tmp_path):
    """Without an earlier look nothing counts as ended."""
    assert ended_jobs(tmp_path / "j.json", {"dev-1-repo-1"}) == set()
    assert json.loads((tmp_path / "j.json").read_text()) == ["dev-1-repo-1"]


def test_a_job_gone_since_the_last_look_has_ended(tmp_path):
    """A job enabled before and gone now has ended; a new one has not."""
    state = tmp_path / "j.json"
    ended_jobs(state, {"dev-1-repo-1", "dev-2-repo-2"})
    assert ended_jobs(state, {"dev-2-repo-2", "dev-1-repo-3"}) == {"dev-1-repo-1"}
    assert ended_jobs(state, {"dev-2-repo-2", "dev-1-repo-3"}) == set()


@pytest.mark.parametrize("before, now, runs", [
    (["dev-1-repo-1"], [], [True]),  # ended: one full run
    (["dev-1-repo-1"], ["dev-1-repo-1"], []),  # still at work: no run, no GitHub call
])
def test_jobwatch_runs_the_engine_only_when_a_job_ended(tmp_path, monkeypatch, before, now, runs):
    """The engine runs over the whole board, and only after an end."""
    jobs = tmp_path / "jobs.json"
    jobs.write_text(json.dumps({"jobs": [{"name": n, "enabled": True} for n in now]}))
    (tmp_path / "dev-jobs.json").write_text(json.dumps(before))
    monkeypatch.setattr("loop.config.DEV_JOBS", str(jobs))
    monkeypatch.setattr("loop.config.CACHE_DIR", str(tmp_path))
    called = []
    monkeypatch.setattr(jobwatch, "tick", lambda dry_run, full, sink: called.append(full) or 0)
    assert jobwatch.jobwatch() == 0 and called == runs


def answer(node):
    """A fake gh answering the card query with this node."""
    data = {"data": {"rateLimit": {}, "repository": {"issueOrPullRequest": node}}}
    return lambda args: json.dumps(data)


def test_card_query_on_a_pull_request_number_says_so():
    """A comment on a PR carries the PR number: no GraphQL error, a NotAnIssue."""
    with pytest.raises(NotAnIssue):
        GitHubClient(answer({"__typename": "PullRequest"})).card("O/r", 88)


def test_comment_on_a_pull_request_changes_nothing():
    """The one-card run on a PR number decides nothing instead of failing (exit 1)."""
    client = GitHubClient(answer({"__typename": "PullRequest"}))
    out = tick.decide_scope(client, Scope(("O/r", 88), "issue_comment.created"),
                            datetime(2026, 11, 8, tzinfo=UTC))
    assert not out.starts and not out.board.status and not out.board.add
