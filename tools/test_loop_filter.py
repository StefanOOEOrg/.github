"""Tests for the shadow-mode filter of the webhook route `loop`."""

import io
import json

import loop_filter
import pytest


@pytest.mark.parametrize("payload, expected", [
    ({"zen": "Keep it simple.", "hook_id": 1}, "ping"),
    ({"projects_v2_item": {"content_node_id": "I_1"}, "action": "edited"}, "projects_v2_item"),
    ({"review": {}, "pull_request": {}}, "pull_request_review"),
    ({"comment": {}, "issue": {}}, "issue_comment"),
    ({"pull_request": {}}, "pull_request"),
    ({"issue": {}}, "issues"),
    ({}, "unknown"),
])
def test_event_type_is_derived_from_the_payload(payload, expected):
    assert loop_filter.event_type(payload) == expected


def test_summary_names_repo_and_number():
    payload = {"action": "opened", "issue": {"number": 7}, "repository": {"full_name": "O/R"},
               "sender": {"login": "StefanOOE"}}
    record = loop_filter.summary(payload)
    assert (record["event"], record["subject"], record["sender"]) == ("issues", "O/R#7", "StefanOOE")


def test_summary_lists_changed_fields_of_a_project_item():
    payload = {"action": "edited", "projects_v2_item": {"content_node_id": "I_1"},
               "changes": {"field_value": {"field_name": "Status"}}}
    record = loop_filter.summary(payload)
    assert (record["subject"], record["changed"], record["field"]) == ("I_1", ["field_value"], "Status")


def test_summary_records_the_new_single_select_value():
    payload = {"projects_v2_item": {}, "changes": {"field_value": {"field_name": "Status",
                                                                    "to": {"name": "Goal"}}}}
    assert loop_filter.summary(payload)["to"] == "Goal"


def test_fork_pull_request_is_marked():
    payload = {"pull_request": {"number": 3, "head": {"repo": {"full_name": "x/R"}}},
               "repository": {"full_name": "O/R"}}
    assert loop_filter.summary(payload)["fork"] is True


def test_main_records_and_stays_silent(tmp_path, monkeypatch, capsys):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    monkeypatch.setattr(loop_filter, "__file__", str(scripts / "loop_filter.py"))
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({"issue": {"number": 1}})))
    assert loop_filter.main() == 0
    assert capsys.readouterr().out.strip() == "[SILENT]"
    line = (tmp_path / "cache" / "webhook-events.jsonl").read_text().strip()
    assert json.loads(line)["event"] == "issues"


def test_invalid_json_is_recorded_and_ignored(tmp_path, monkeypatch, capsys):
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    monkeypatch.setattr(loop_filter, "__file__", str(scripts / "loop_filter.py"))
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert loop_filter.main() == 0
    assert capsys.readouterr().out.strip() == "[SILENT]"
    assert '"invalid"' in (tmp_path / "cache" / "webhook-events.jsonl").read_text()
