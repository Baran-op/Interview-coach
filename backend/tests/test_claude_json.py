import pytest

from backend import claude_json, feedback


def test_extract_json_plain_and_fenced():
    assert claude_json.extract_json('{"a": 1}') == {"a": 1}
    assert claude_json.extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert claude_json.extract_json('Here you go: {"a": {"b": 2}} done') == {"a": {"b": 2}}


@pytest.mark.parametrize("bad", ["no json", "{broken", ""])
def test_extract_json_errors(bad):
    with pytest.raises(claude_json.ClaudeJSONError):
        claude_json.extract_json(bad)


def test_report_schema_matches_criteria():
    answer = feedback.REPORT_SCHEMA["properties"]["answers"]["items"]
    assert set(answer["properties"]["scores"]["required"]) == set(feedback.CRITERIA)


def test_pick_result_order():
    assert claude_json.pick_result({"a": 1}, {"b": 2}, '{"c": 3}', None) == {"a": 1}
    assert claude_json.pick_result(None, {"b": 2}, '{"c": 3}', "err") == {"b": 2}
    assert claude_json.pick_result(None, None, '{"c": 3}', "err") == {"c": 3}


def test_pick_result_error_when_nothing_usable():
    with pytest.raises(claude_json.ClaudeJSONError, match="error_max_turns"):
        claude_json.pick_result(None, None, "", "Claude returned an error (error_max_turns)")
