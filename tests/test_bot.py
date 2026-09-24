"""Telegram bot: HTML output safety and error handling. No Telegram API calls."""

import asyncio
import re
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest

import bot
import tools
from mcp_client import MCPConnectionError, MCPToolError

ALLOWED_TAGS = {"b", "code"}  # the only tags the application itself emits

NASTY = [
    "<script>alert(1)</script>",
    "Tom & Jerry",
    "a < b > c",
    'He said "hi" & it\'s <fine>',
    "<b>not bold</b>",
    "</b><i>x</i>",
    "&lt;already escaped&gt; &amp; &#60;",
]


class _Collector(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.tags, self.text, self.stack, self.problems = [], [], [], []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        self.stack.append(tag)

    def handle_endtag(self, tag):
        if not self.stack or self.stack.pop() != tag:
            self.problems.append(f"unbalanced </{tag}>")

    def handle_data(self, data):
        self.text.append(data)


def parse_html(html_text):
    """Returns (visible_text, tags) and asserts the markup is Telegram-safe."""
    # every & must start a valid entity (Telegram rejects stray ones)
    assert not re.search(r"&(?!(?:amp|lt|gt|quot|#\d+|#x[0-9a-fA-F]+);)", html_text), html_text
    collector = _Collector()
    collector.feed(html_text)
    collector.close()
    assert not collector.problems and not collector.stack, html_text
    assert set(collector.tags) <= ALLOWED_TAGS, f"unexpected tags: {set(collector.tags)}"
    return "".join(collector.text), collector.tags


def make_review(**overrides):
    review = {
        "id": 7,
        "customer_name": "Иван",
        "source": "Website",
        "rating": 4,
        "text": "Хороший товар",
        "status": "new",
        "created_at": "2025-01-01 10:00:00",
    }
    return {**review, **overrides}


def test_normal_review_keeps_its_formatting_and_text():
    visible, tags = parse_html(bot._format_review(make_review()))
    assert tags.count("b") == 7
    for expected in ("Иван", "Website", "Хороший товар", "new", "4/5", "2025-01-01 10:00:00"):
        assert expected in visible


@pytest.mark.parametrize("nasty", NASTY)
def test_review_fields_are_escaped(nasty):
    review = make_review(customer_name=nasty, source=nasty, text=nasty, status=nasty)
    visible, tags = parse_html(bot._format_review(review))
    assert visible.count(nasty) == 4  # shown literally, nothing interpreted
    assert set(tags) == {"b"}


@pytest.mark.parametrize("nasty", NASTY)
def test_review_list_is_escaped(nasty):
    reviews = [make_review(text=nasty), make_review(customer_name=nasty)]
    visible, _ = parse_html(bot.format_tool_result("find_reviews", reviews))
    assert visible.count(nasty) == 2


@pytest.mark.parametrize("nasty", NASTY)
def test_add_review_confirmation_shows_saved_values_escaped(nasty):
    saved = tools.call_tool_by_name(
        "add_review",
        {"customer_name": nasty, "source": nasty, "rating": 2, "text": nasty},
    )
    visible, tags = parse_html(bot.format_tool_result("add_review", saved))
    assert visible.startswith("✅ Отзыв добавлен!")
    assert visible.count(nasty) == 3  # name, source, text: round-tripped through SQLite
    assert set(tags) == {"b"}


@pytest.mark.parametrize("nasty", NASTY)
def test_draft_reply_is_escaped(nasty):
    data = {"review": make_review(text=nasty, customer_name=nasty), "draft_reply": nasty}
    visible, _ = parse_html(bot.format_tool_result("draft_reply", data))
    assert visible.count(nasty) == 3


@pytest.mark.parametrize("nasty", NASTY)
def test_stats_keys_are_escaped(nasty):
    stats = {
        "total_reviews": 3,
        "average_rating": 3.5,
        "positive_count": 1,
        "neutral_count": 1,
        "negative_count": 1,
        "by_source": {nasty: 2},
        "by_status": {nasty: 1},
    }
    visible, _ = parse_html(bot.format_tool_result("get_review_stats", stats))
    assert visible.count(nasty) == 2


@pytest.mark.parametrize("nasty", NASTY)
def test_calculate_expression_and_error_are_escaped(nasty):
    ok, _ = parse_html(bot.format_tool_result("calculate", {"expression": nasty, "result": 5}))
    assert nasty in ok
    failed, tags = parse_html(bot.format_tool_result("calculate", {"expression": nasty, "error": nasty}))
    assert failed == f"❌ {nasty}"
    assert tags == []


def test_real_calculator_syntax_error_is_valid_telegram_html():
    # Python's message is "invalid syntax (<unknown>, line 1)": raw, this is an unsupported tag.
    visible, _ = parse_html(bot.format_tool_result("calculate", tools.calculate("1 +")))
    assert "<unknown>" in visible


def test_unknown_result_shape_falls_back_to_escaped_text():
    visible, tags = parse_html(bot.format_tool_result("other", {"note": "<i>x</i> & y"}))
    assert "<i>x</i> & y" in visible
    assert tags == []


# --- handle_message: error paths ---


class FakeMessage:
    def __init__(self, text="покажи отзывы"):
        self.text = text
        self.chat = SimpleNamespace(id=1)
        self.answers = []

        async def send_chat_action(*_):
            pass

        self.bot = SimpleNamespace(send_chat_action=send_chat_action)

    async def answer(self, text, **kwargs):
        self.answers.append((text, kwargs))


@pytest.fixture
def run_handler(monkeypatch):
    def run(routing, call_tool):
        monkeypatch.setattr(bot, "route_user_message", lambda _text: routing)
        monkeypatch.setattr(bot, "call_tool", call_tool)
        message = FakeMessage()
        asyncio.run(bot.handle_message(message))
        assert len(message.answers) == 1
        return message.answers[0]

    return run


LIST_ROUTING = {"tool": "list_reviews", "arguments": {}}


def raises(exc):
    def call_tool(*_args, **_kwargs):
        raise exc

    return call_tool


def test_successful_result_is_sent_as_html(run_handler):
    text, kwargs = run_handler(
        LIST_ROUTING, lambda *_: {"ok": True, "result": [make_review(text="<b>x</b> & y")]}
    )
    assert kwargs == {"parse_mode": "HTML"}
    visible, _ = parse_html(text)
    assert "<b>x</b> & y" in visible


def test_connection_error_asks_to_check_the_server_and_hides_internals(run_handler):
    internals = (
        "HTTPConnectionPool(host='127.0.0.1', port=8008): Max retries exceeded with url: "
        "/call_tool Traceback sk-secret"
    )
    text, kwargs = run_handler(LIST_ROUTING, raises(MCPConnectionError(internals)))
    assert kwargs == {"parse_mode": "HTML"}
    visible, tags = parse_html(text)
    assert "MCP-сервер запущен" in visible
    assert "cd mcp_server && python server.py" in visible  # static text, correctly escaped
    assert "code" in tags
    for leaked in ("HTTPConnectionPool", "Max retries", "127.0.0.1", "8008", "Traceback", "secret"):
        assert leaked not in text


def test_tool_error_is_shown_sanitized_and_is_not_reported_as_unreachable(run_handler):
    error = MCPToolError("Аргумент «limit» должен быть не больше 50 <script>alert(1)</script> & co")
    text, kwargs = run_handler(LIST_ROUTING, raises(error))
    assert kwargs == {"parse_mode": "HTML"}
    visible, tags = parse_html(text)
    assert "limit" in visible and "<script>alert(1)</script> & co" in visible
    assert tags == []
    for wrong in ("связаться", "запущен", "server.py"):
        assert wrong not in text


def test_long_tool_error_is_truncated(run_handler):
    text, _ = run_handler(LIST_ROUTING, raises(MCPToolError("x" * 5000)))
    assert len(text) < bot.MAX_ERROR_LEN + 100


def test_routing_answer_without_tool_is_sent_as_plain_text(run_handler):
    routing = {"tool": None, "answer": "1 < 2 & <b>plain</b>"}
    text, kwargs = run_handler(routing, raises(AssertionError("must not be called")))
    assert (text, kwargs) == ("1 < 2 & <b>plain</b>", {})
