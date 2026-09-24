"""HTTP client: connection failures and tool failures are different errors."""

import json

import pytest
import requests

import mcp_client
from mcp_client import MCPClientError, MCPConnectionError, MCPToolError


def make_response(status=200, body=None, raw=None):
    response = requests.Response()
    response.status_code = status
    response._content = raw if raw is not None else json.dumps(body).encode()
    return response


@pytest.fixture
def post(monkeypatch):
    """Replace requests.post; set `post.result` to a response or an exception."""
    calls = []

    def fake_post(url, json=None, timeout=None):
        calls.append({"url": url, "json": json, "timeout": timeout})
        if isinstance(fake_post.result, Exception):
            raise fake_post.result
        return fake_post.result

    fake_post.calls = calls
    monkeypatch.setattr(mcp_client.requests, "post", fake_post)
    return fake_post


def test_successful_response_is_returned(post):
    body = {"ok": True, "tool": "list_reviews", "result": [{"id": 1}]}
    post.result = make_response(body=body)

    assert mcp_client.call_tool("list_reviews", {"limit": 1}) == body
    assert post.calls == [
        {
            "url": "http://mcp.test/call_tool",
            "json": {"tool": "list_reviews", "arguments": {"limit": 1}},
            "timeout": 15,
        }
    ]


@pytest.mark.parametrize(
    "failure",
    [
        requests.ConnectionError("connection refused"),
        requests.Timeout("timed out"),
        make_response(status=500, body={"detail": "boom"}),
        make_response(status=404, body={"detail": "Not Found"}),
        make_response(raw=b"<html>not json</html>"),
        make_response(body=["not", "an", "object"]),
    ],
    ids=["refused", "timeout", "http-500", "http-404", "non-json", "non-object"],
)
def test_transport_failures_are_connection_errors(post, failure):
    post.result = failure
    with pytest.raises(MCPConnectionError):
        mcp_client.call_tool("list_reviews")


def test_ok_false_is_a_tool_error_not_a_connection_error(post):
    post.result = make_response(body={"ok": False, "error": "Отзыв с id=9 не найден"})
    with pytest.raises(MCPToolError, match="id=9 не найден") as excinfo:
        mcp_client.call_tool("draft_reply", {"review_id": 9})
    assert not isinstance(excinfo.value, MCPConnectionError)


@pytest.mark.parametrize(
    "body",
    [
        {"ok": False},
        {"ok": False, "error": None},
        {"ok": False, "error": ""},
        {"ok": False, "error": "   "},
        {"ok": False, "error": 500},
        {"ok": False, "error": ["boom"]},
    ],
    ids=["no-error", "null-error", "empty-error", "blank-error", "int-error", "list-error"],
)
def test_ok_false_without_a_usable_error_string_is_a_protocol_error(post, body):
    post.result = make_response(body=body)
    with pytest.raises(MCPConnectionError) as excinfo:
        mcp_client.call_tool("list_reviews")
    assert not isinstance(excinfo.value, MCPToolError)


# --- response envelope: anything structurally wrong must not reach the formatters ---

MALFORMED_ENVELOPES = [
    ("list", ["ok", True]),
    ("string", "ok"),
    ("number", 1),
    ("null", None),
    ("missing-ok", {"tool": "list_reviews", "result": []}),
    ("ok-string", {"ok": "yes", "tool": "list_reviews", "result": []}),
    ("ok-int-1", {"ok": 1, "tool": "list_reviews", "result": []}),
    ("ok-int-0", {"ok": 0, "error": "boom"}),
    ("ok-null", {"ok": None, "tool": "list_reviews", "result": []}),
    ("missing-result", {"ok": True, "tool": "list_reviews"}),
    ("missing-tool", {"ok": True, "result": []}),
    ("tool-null", {"ok": True, "tool": None, "result": []}),
    ("tool-not-string", {"ok": True, "tool": 5, "result": []}),
    ("tool-mismatch", {"ok": True, "tool": "find_reviews", "result": []}),
]


@pytest.mark.parametrize("body", [b for _, b in MALFORMED_ENVELOPES], ids=[i for i, _ in MALFORMED_ENVELOPES])
def test_malformed_envelopes_are_protocol_errors(post, body):
    post.result = make_response(body=body)
    with pytest.raises(MCPConnectionError) as excinfo:
        mcp_client.call_tool("list_reviews")
    assert not isinstance(excinfo.value, MCPToolError)


def test_protocol_error_does_not_echo_the_response_body(post):
    post.result = make_response(body={"ok": "yes", "secret": "sk-topsecret /srv/app.py", "result": []})
    with pytest.raises(MCPConnectionError) as excinfo:
        mcp_client.call_tool("list_reviews")
    assert "sk-topsecret" not in str(excinfo.value)
    assert "/srv/app.py" not in str(excinfo.value)


@pytest.mark.parametrize("result", [[], 0, 0.0, "", False, {}, None])
def test_valid_falsy_results_are_accepted(post, result):
    body = {"ok": True, "tool": "list_reviews", "result": result}
    post.result = make_response(body=body)
    assert mcp_client.call_tool("list_reviews") == body


def test_extra_envelope_fields_are_tolerated(post):
    body = {"ok": True, "tool": "list_reviews", "result": [], "extra": 1}
    post.result = make_response(body=body)
    assert mcp_client.call_tool("list_reviews") == body


# --- request arguments: only None means "no arguments" ---


def test_none_arguments_are_sent_as_an_empty_object(post):
    post.result = make_response(body={"ok": True, "tool": "get_review_stats", "result": {}})
    mcp_client.call_tool("get_review_stats")
    mcp_client.call_tool("get_review_stats", None)
    assert [c["json"] for c in post.calls] == [{"tool": "get_review_stats", "arguments": {}}] * 2


@pytest.mark.parametrize("arguments", [[], "", 0, False, {}], ids=["list", "string", "zero", "false", "dict"])
def test_falsy_arguments_are_sent_unchanged(post, arguments):
    post.result = make_response(body={"ok": True, "tool": "list_reviews", "result": []})
    mcp_client.call_tool("list_reviews", arguments)
    sent = post.calls[0]["json"]["arguments"]
    assert sent == arguments and type(sent) is type(arguments)


def test_non_object_arguments_round_trip_as_a_tool_error(monkeypatch, http):
    """Client -> real app: [] is not silently turned into {}; the server rejects it as a tool error."""

    def post_to_app(url, json=None, timeout=None):
        served = http("POST", "/call_tool", json=json)
        return make_response(status=served.status_code, raw=served.content)

    monkeypatch.setattr(mcp_client.requests, "post", post_to_app)

    for bad in ([], "", 0, False, "limit=5"):
        with pytest.raises(MCPToolError, match="JSON-объектом"):
            mcp_client.call_tool("list_reviews", bad)


# --- base URL ---


@pytest.mark.parametrize("base", ["http://127.0.0.1:8008", "http://127.0.0.1:8008/", "http://127.0.0.1:8008///"])
def test_trailing_slash_in_the_server_url_is_normalized(post, monkeypatch, base):
    monkeypatch.setattr(mcp_client, "MCP_SERVER_URL", base)
    post.result = make_response(body={"ok": True, "tool": "list_reviews", "result": []})
    mcp_client.call_tool("list_reviews")
    assert post.calls[0]["url"] == "http://127.0.0.1:8008/call_tool"


def test_error_classes_are_distinct_siblings():
    assert issubclass(MCPConnectionError, MCPClientError)
    assert issubclass(MCPToolError, MCPClientError)
    assert not issubclass(MCPToolError, MCPConnectionError)
    assert not issubclass(MCPConnectionError, MCPToolError)


def test_server_side_validation_error_reaches_the_client_as_a_tool_error(monkeypatch, http):
    """Client -> real FastAPI app (in-process): a schema violation is not 'server down'."""

    def post_to_app(url, json=None, timeout=None):
        served = http("POST", "/call_tool", json=json)
        return make_response(status=served.status_code, raw=served.content)

    monkeypatch.setattr(mcp_client.requests, "post", post_to_app)

    with pytest.raises(MCPToolError, match="limit"):
        mcp_client.call_tool("list_reviews", {"limit": -1})
    assert mcp_client.call_tool("list_reviews", {"limit": 2})["ok"] is True
