"""Tool dispatch: inputSchema is enforced before any tool function runs."""

import inspect

import pytest

import db
import tools

LIMIT_TOOLS = [
    ("list_reviews", {}),
    ("find_reviews", {"query": "x"}),
    ("find_reviews_by_rating", {"rating": 3}),
    ("find_negative_reviews", {}),
]

VALID_ADD_REVIEW = {
    "customer_name": "Zoe",
    "source": "Telegram",
    "rating": 4,
    "text": "Nice",
}

# (tool, arguments, text the error message must mention)
INVALID_CALLS = [
    ("find_reviews", {}, "query"),  # missing required
    ("draft_reply", {"tone": "warm"}, "review_id"),  # missing required
    ("add_review", {"customer_name": "Zoe"}, "source"),  # missing required
    ("find_reviews", {"query": 5}, "query"),  # wrong type: int for string
    ("draft_reply", {"review_id": "5"}, "review_id"),  # wrong type: string for integer
    ("list_reviews", {"limit": "5"}, "limit"),
    ("list_reviews", {"limit": 2.5}, "limit"),  # float is not an integer
    ("list_reviews", {"limit": True}, "limit"),  # bool is not an integer
    ("list_reviews", {"limit": None}, "limit"),
    ("list_reviews", {"offset": 1}, "offset"),  # unexpected argument
    ("get_review_stats", {"anything": 1}, "anything"),
    ("find_reviews", {"query": "x", "extra": 1}, "extra"),
    ("list_reviews", {"limit": 0}, "limit"),  # range
    ("list_reviews", {"limit": -1}, "limit"),
    ("list_reviews", {"limit": tools.MAX_LIMIT + 1}, "limit"),
    ("find_reviews_by_rating", {"rating": 0}, "rating"),
    ("find_reviews_by_rating", {"rating": 6}, "rating"),
    ("add_review", {**VALID_ADD_REVIEW, "rating": 9}, "rating"),
    ("draft_reply", {"review_id": 0}, "review_id"),
    ("draft_reply", {"review_id": 2**63}, "review_id"),  # cannot be an SQLite INTEGER
]


def test_valid_call_runs_the_tool():
    result = tools.call_tool_by_name("find_reviews_by_rating", {"rating": 5, "limit": 3})
    assert 0 < len(result) <= 3
    assert all(r["rating"] == 5 for r in result)
    assert "total_reviews" in tools.call_tool_by_name("get_review_stats", {})
    assert tools.call_tool_by_name("calculate", {"expression": "2 + 2"})["result"] == 4


@pytest.mark.parametrize("tool, base_args", LIMIT_TOOLS)
@pytest.mark.parametrize("limit", [1, tools.MAX_LIMIT])
def test_limit_bounds_are_inclusive(tool, base_args, limit):
    result = tools.call_tool_by_name(tool, {**base_args, "limit": limit})
    assert len(result) <= limit


def test_unknown_tool_is_rejected():
    with pytest.raises(tools.UnknownToolError, match="Неизвестный инструмент"):
        tools.call_tool_by_name("drop_table", {})
    with pytest.raises(tools.UnknownToolError, match="Неизвестный инструмент"):
        tools.call_tool_by_name("__class__", {})


def test_expected_errors_are_an_explicit_family_not_plain_value_errors():
    for error in (tools.ToolArgumentError, tools.UnknownToolError, tools.ToolDomainError):
        assert issubclass(error, tools.ToolError)
    # The public-safe contract must not depend on ValueError.
    assert not issubclass(tools.ToolError, ValueError)


@pytest.mark.parametrize("tool, arguments, mentions", INVALID_CALLS)
def test_invalid_arguments_are_rejected_with_a_clean_message(tool, arguments, mentions):
    with pytest.raises(tools.ToolArgumentError) as excinfo:
        tools.call_tool_by_name(tool, arguments)
    message = str(excinfo.value)
    assert mentions in message
    for python_internals in ("positional argument", "keyword argument", "TypeError", "()"):
        assert python_internals not in message


@pytest.mark.parametrize("arguments", [[], "limit=5", 5, None])
def test_arguments_must_be_an_object(arguments):
    with pytest.raises(tools.ToolArgumentError):
        tools.call_tool_by_name("list_reviews", arguments)


@pytest.mark.parametrize("tool, arguments, _", INVALID_CALLS)
def test_invalid_arguments_never_reach_the_tool_function(monkeypatch, tool, arguments, _):
    calls = []
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, tool, lambda **kw: calls.append(kw))
    with pytest.raises(tools.ToolArgumentError):
        tools.call_tool_by_name(tool, arguments)
    assert calls == []


def test_valid_arguments_reach_the_tool_function(monkeypatch):
    calls = []
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "list_reviews", lambda **kw: calls.append(kw))
    tools.call_tool_by_name("list_reviews", {"limit": 7})
    assert calls == [{"limit": 7}]


def test_invalid_add_review_writes_nothing():
    conn = db.get_connection()
    before = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    conn.close()
    with pytest.raises(tools.ToolArgumentError):
        tools.call_tool_by_name("add_review", {**VALID_ADD_REVIEW, "rating": 9})
    with pytest.raises(tools.ToolArgumentError):
        tools.call_tool_by_name("add_review", {**VALID_ADD_REVIEW, "surprise": 1})
    conn = db.get_connection()
    after = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    conn.close()
    assert after == before


# --- the published schemas must stay a truthful, validator-supported contract ---


def test_schemas_only_use_features_the_validator_supports():
    placeholders = {"string": "x", "integer": 1}
    for tool in tools.MCP_TOOLS:
        schema = tool["inputSchema"]
        assert set(schema) <= {"type", "properties", "required", "additionalProperties"}
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False, tool["name"]
        assert set(schema.get("required", [])) <= set(schema["properties"])
        for name, spec in schema["properties"].items():
            assert set(spec) <= {"type", "description", "default", "minimum", "maximum"}
            assert spec["type"] in tools._TYPE_CHECKS, (tool["name"], name)
            if "default" in spec:  # a declared default must itself be valid
                arguments = {r: placeholders[schema["properties"][r]["type"]] for r in schema.get("required", [])}
                tools.validate_arguments(schema, {**arguments, name: spec["default"]})


def test_schemas_match_the_tool_function_signatures():
    assert {t["name"] for t in tools.MCP_TOOLS} == set(tools.TOOL_FUNCTIONS)
    for tool in tools.MCP_TOOLS:
        params = inspect.signature(tools.TOOL_FUNCTIONS[tool["name"]]).parameters
        schema = tool["inputSchema"]
        assert set(schema["properties"]) == set(params), tool["name"]
        required = {n for n, p in params.items() if p.default is inspect.Parameter.empty}
        assert set(schema.get("required", [])) == required, tool["name"]


# --- HTTP layer ---


def test_tools_endpoint_publishes_the_enforced_schemas(http):
    published = http("GET", "/tools").json()["tools"]
    assert published == tools.MCP_TOOLS
    limit = next(t for t in published if t["name"] == "list_reviews")["inputSchema"]["properties"]["limit"]
    assert (limit["minimum"], limit["maximum"]) == (1, tools.MAX_LIMIT)


def test_call_tool_success(http):
    body = http("POST", "/call_tool", json={"tool": "get_review_stats", "arguments": {}}).json()
    assert body["ok"] is True
    assert body["tool"] == "get_review_stats"
    assert body["result"]["total_reviews"] > 0


@pytest.mark.parametrize(
    "payload",
    [
        {"tool": "no_such_tool", "arguments": {}},
        {"tool": "list_reviews", "arguments": {"limit": -1}},
        {"tool": "find_reviews", "arguments": {}},
        {"tool": "list_reviews", "arguments": {"limit": "many"}},
    ],
)
def test_call_tool_failure_is_ok_false_with_a_clean_error(http, payload):
    response = http("POST", "/call_tool", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is False
    assert "Traceback" not in body["error"]
    assert "positional argument" not in body["error"]


GENERIC_ERROR = {"ok": False, "error": "Внутренняя ошибка инструмента"}


def test_unexpected_tool_crash_does_not_leak_internals(http, monkeypatch):
    def boom(**_):
        raise RuntimeError("secret internal detail C:\\srv\\app.py")

    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "list_reviews", boom)
    body = http("POST", "/call_tool", json={"tool": "list_reviews", "arguments": {}}).json()
    assert body == GENERIC_ERROR


def test_unexpected_value_error_is_not_treated_as_a_safe_error(http, monkeypatch):
    """A plain ValueError is not part of the public-safe contract: its text stays server-side."""

    def boom(**_):
        raise ValueError("SECRET internal path C:/srv/app.py")

    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "list_reviews", boom)
    response = http("POST", "/call_tool", json={"tool": "list_reviews", "arguments": {}})
    assert response.status_code == 200
    assert response.json() == GENERIC_ERROR
    assert "SECRET" not in response.text
    assert "C:/srv/app.py" not in response.text


def test_unexpected_value_error_from_the_validation_step_is_not_exposed(http, monkeypatch):
    def boom(*_):
        raise ValueError("SECRET internal path C:/srv/app.py")

    monkeypatch.setattr(tools, "validate_arguments", boom)
    response = http("POST", "/call_tool", json={"tool": "list_reviews", "arguments": {}})
    assert response.json() == GENERIC_ERROR
    assert "SECRET" not in response.text


def test_expected_domain_errors_keep_their_useful_message(http):
    body = http("POST", "/call_tool", json={"tool": "draft_reply", "arguments": {"review_id": 10**9}}).json()
    assert body == {"ok": False, "error": f"Отзыв с id={10**9} не найден"}

    body = http("POST", "/call_tool", json={"tool": "no_such_tool", "arguments": {}}).json()
    assert body == {"ok": False, "error": "Неизвестный инструмент: no_such_tool"}

    body = http("POST", "/call_tool", json={"tool": "list_reviews", "arguments": {"limit": 0}}).json()
    assert body == {"ok": False, "error": "Аргумент «limit» должен быть не меньше 1"}


def test_a_tool_function_can_raise_a_safe_error_and_the_client_sees_it(http, monkeypatch):
    def refuse(**_):
        raise tools.ToolDomainError("Нельзя так делать")

    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "list_reviews", refuse)
    body = http("POST", "/call_tool", json={"tool": "list_reviews", "arguments": {}}).json()
    assert body == {"ok": False, "error": "Нельзя так делать"}


# --- "arguments" of any JSON type reaches the validator (no Pydantic HTTP 422) ---


@pytest.mark.parametrize(
    "arguments",
    [[], [1, 2], "limit=5", "", 5, 0, 2.5, True, False],
    ids=["empty-list", "list", "string", "empty-string", "int", "zero", "float", "true", "false"],
)
def test_non_object_arguments_get_the_normal_tool_error(http, monkeypatch, arguments):
    calls = []
    monkeypatch.setitem(tools.TOOL_FUNCTIONS, "list_reviews", lambda **kw: calls.append(kw))

    response = http("POST", "/call_tool", json={"tool": "list_reviews", "arguments": arguments})

    assert response.status_code == 200  # not a Pydantic 422
    assert response.json() == {"ok": False, "error": "Аргументы должны быть JSON-объектом"}
    assert calls == []  # rejected before the tool ran


@pytest.mark.parametrize("payload", [{"tool": "get_review_stats"}, {"tool": "get_review_stats", "arguments": None}])
def test_missing_or_null_arguments_mean_no_arguments(http, payload):
    response = http("POST", "/call_tool", json=payload)
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["result"]["total_reviews"] > 0


def test_missing_arguments_still_fail_validation_for_tools_with_required_ones(http):
    body = http("POST", "/call_tool", json={"tool": "find_reviews"}).json()
    assert body == {"ok": False, "error": "Не указан обязательный аргумент «query»"}
