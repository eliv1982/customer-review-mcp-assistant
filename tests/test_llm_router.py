"""LLM router: no network, the OpenAI client is faked or served by httpx.MockTransport."""

import json
from types import SimpleNamespace

import httpx
import openai
import pytest

import llm_router
import tools


@pytest.fixture
def model(monkeypatch):
    """Fake OpenAI client. Set `model.content` (str) or `model.error` (exception)."""
    state = SimpleNamespace(content="", error=None, requests=[])

    class FakeCompletions:
        def create(self, **kwargs):
            state.requests.append(kwargs)
            if state.error is not None:
                raise state.error
            message = SimpleNamespace(content=state.content)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    class FakeOpenAI:
        def __init__(self, api_key=None):
            self.chat = SimpleNamespace(completions=FakeCompletions())

    monkeypatch.setattr(llm_router, "OpenAI", FakeOpenAI)
    return state


def route(model, content):
    model.content = content
    return llm_router.route_user_message("любой запрос")


def test_valid_json_selects_the_tool(model):
    routing = route(model, '{"tool": "find_reviews", "arguments": {"query": "доставка", "limit": 10}}')
    assert routing == {"tool": "find_reviews", "arguments": {"query": "доставка", "limit": 10}}


def test_request_uses_json_mode_and_configured_model(model):
    route(model, '{"tool": "get_review_stats", "arguments": {}}')
    (request,) = model.requests
    assert request["model"] == "test-model"
    assert request["temperature"] == 0
    assert request["response_format"] == {"type": "json_object"}
    assert [m["role"] for m in request["messages"]] == ["system", "user"]
    assert request["messages"][1]["content"] == "любой запрос"


@pytest.mark.parametrize(
    "content",
    [
        '```json\n{"tool": "get_review_stats", "arguments": {}}\n```',
        '```\n{"tool": "get_review_stats", "arguments": {}}\n```',
        '```json\n{"tool": "get_review_stats", "arguments": {}}',  # closing fence missing
    ],
)
def test_fenced_json_is_accepted(model, content):
    assert route(model, content) == {"tool": "get_review_stats", "arguments": {}}


def test_missing_arguments_default_to_empty(model):
    assert route(model, '{"tool": "get_review_stats"}') == {"tool": "get_review_stats", "arguments": {}}
    assert route(model, '{"tool": "get_review_stats", "arguments": null}')["arguments"] == {}


def test_no_tool_answer_is_passed_through(model):
    assert route(model, '{"tool": null, "answer": "Привет!"}') == {"tool": None, "answer": "Привет!"}


@pytest.mark.parametrize("content", ['{"tool": null}', '{"tool": null, "answer": 5}', '{"tool": null, "answer": ""}'])
def test_no_tool_without_a_usable_answer_gets_a_default_text(model, content):
    routing = route(model, content)
    assert routing["tool"] is None
    assert isinstance(routing["answer"], str) and routing["answer"].strip()


@pytest.mark.parametrize(
    "content",
    ["", "not json at all", "{", '{"tool": "list_reviews"', "[]", "[1, 2]", '"list_reviews"', "42", "null"],
)
def test_malformed_model_output_degrades_to_a_plain_answer(model, content):
    routing = route(model, content)
    assert routing["tool"] is None
    assert isinstance(routing["answer"], str) and routing["answer"]


@pytest.mark.parametrize(
    "tool",
    ["drop_table", "LIST_REVIEWS", "list_reviews ", "", "__import__", ["list_reviews"], {"a": 1}, 5, True],
)
def test_tool_outside_valid_tools_is_rejected(model, tool):
    routing = route(model, json.dumps({"tool": tool, "arguments": {}}))
    assert routing["tool"] is None
    assert "arguments" not in routing


@pytest.mark.parametrize("arguments", [[1, 2], "limit=5", 5, True])
def test_non_object_arguments_are_rejected(model, arguments):
    routing = route(model, json.dumps({"tool": "list_reviews", "arguments": arguments}))
    assert routing["tool"] is None


def test_router_forwards_arguments_unchecked_so_the_server_must_validate(model):
    routing = route(model, '{"tool": "list_reviews", "arguments": {"limit": -1, "surprise": true}}')
    assert routing["tool"] == "list_reviews"
    assert routing["arguments"] == {"limit": -1, "surprise": True}
    with pytest.raises(tools.ToolArgumentError):
        tools.call_tool_by_name(routing["tool"], routing["arguments"])


@pytest.mark.parametrize(
    "error",
    [
        openai.OpenAIError("Incorrect API key provided: sk-proj-abc123SECRETKEY. See https://platform.openai.com"),
        openai.APIConnectionError(
            message="Connection error to sk-proj-abc123SECRETKEY",
            request=httpx.Request("POST", "https://api.openai.com/v1/chat/completions"),
        ),
    ],
    ids=["OpenAIError", "APIConnectionError"],
)
def test_openai_errors_do_not_leak_details_to_the_user(model, error):
    model.error = error
    routing = llm_router.route_user_message("покажи отзывы")
    assert routing["tool"] is None
    for leaked in ("sk-", "SECRET", "abc123", "platform.openai.com", "Incorrect API key"):
        assert leaked not in routing["answer"]


def test_valid_tools_match_the_server_tools_and_the_prompt():
    """The router keeps its own tool list (by design); this catches drift."""
    assert llm_router.VALID_TOOLS == set(tools.TOOL_FUNCTIONS)
    for name in llm_router.VALID_TOOLS:
        assert name in llm_router.SYSTEM_PROMPT


def test_real_sdk_client_request_and_response_shape(monkeypatch):
    """Runs the real OpenAI SDK against httpx.MockTransport: proves the client-object /
    Chat Completions call used by the router works with the installed SDK, offline."""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["path"] = request.url.path
        seen["authorization"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        completion = {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": "test-model",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": '{"tool": "find_negative_reviews", "arguments": {"limit": 5}}',
                    },
                }
            ],
        }
        return httpx.Response(200, json=completion)

    real_openai = llm_router.OpenAI
    monkeypatch.setattr(
        llm_router,
        "OpenAI",
        lambda api_key: real_openai(
            api_key=api_key, http_client=httpx.Client(transport=httpx.MockTransport(handler))
        ),
    )

    routing = llm_router.route_user_message("покажи негативные отзывы")

    assert routing == {"tool": "find_negative_reviews", "arguments": {"limit": 5}}
    assert seen["path"].endswith("/chat/completions")
    assert seen["authorization"] == "Bearer test-openai-key"
    assert seen["body"]["model"] == "test-model"
    assert seen["body"]["temperature"] == 0
    assert seen["body"]["response_format"] == {"type": "json_object"}
    assert seen["body"]["messages"][-1] == {"role": "user", "content": "покажи негативные отзывы"}
