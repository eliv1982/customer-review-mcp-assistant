"""LLM router: decides which MCP tool to call from user text."""

import json
import logging

from openai import OpenAI, OpenAIError

from config import OPENAI_API_KEY, OPENAI_MODEL

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Ты — помощник для работы с отзывами клиентов.
Ты можешь использовать MCP-style tools:

* list_reviews — показать последние отзывы;
* find_reviews — найти отзывы по тексту или имени клиента;
* find_reviews_by_rating — найти отзывы по конкретной оценке;
* find_negative_reviews — показать негативные отзывы;
* add_review — добавить отзыв;
* get_review_stats — показать статистику;
* draft_reply — подготовить черновик ответа на отзыв;
* calculate — посчитать выражение.

Когда пользователь просит действие с отзывами, верни ТОЛЬКО валидный JSON без markdown:
{
"tool": "название_инструмента",
"arguments": {}
}

Если инструмент не нужен, верни ТОЛЬКО валидный JSON:
{
"tool": null,
"answer": "обычный ответ пользователю"
}

Примеры:
"покажи последние отзывы" → {"tool": "list_reviews", "arguments": {"limit": 10}}
"найди отзывы про доставку" → {"tool": "find_reviews", "arguments": {"query": "доставка", "limit": 10}}
"покажи негативные отзывы" → {"tool": "find_negative_reviews", "arguments": {"limit": 10}}
"покажи отзывы с оценкой 1" → {"tool": "find_reviews_by_rating", "arguments": {"rating": 1, "limit": 10}}
"добавь отзыв: Анна, Telegram, 2, доставка задержалась на три дня" → {"tool": "add_review", "arguments": {"customer_name": "Анна", "source": "Telegram", "rating": 2, "text": "доставка задержалась на три дня"}}
"подготовь ответ на отзыв 5 в тёплом тоне" → {"tool": "draft_reply", "arguments": {"review_id": 5, "tone": "warm"}}
"какой средний рейтинг и сколько негативных отзывов" → {"tool": "get_review_stats", "arguments": {}}
"сколько будет 1200 * 0.15" → {"tool": "calculate", "arguments": {"expression": "1200 * 0.15"}}

Ограничения аргументов: limit — целое число от 1 до 50; rating — целое число от 1 до 5.
Не вызывай несуществующие tools. Не придумывай данные из базы."""

VALID_TOOLS = {
    "list_reviews",
    "find_reviews",
    "find_reviews_by_rating",
    "find_negative_reviews",
    "add_review",
    "get_review_stats",
    "draft_reply",
    "calculate",
}


def _parse_json_response(content: str) -> dict | None:
    text = content.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
        text = text.strip()
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def route_user_message(user_text: str) -> dict:
    client = OpenAI(api_key=OPENAI_API_KEY)

    try:
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_text},
            ],
            temperature=0,
            response_format={"type": "json_object"},
        )
        content = response.choices[0].message.content or ""
    except OpenAIError:
        # Details stay in the log: SDK messages can contain API-key fragments.
        logger.exception("OpenAI API error")
        return {
            "tool": None,
            "answer": "Не удалось обратиться к OpenAI API. Попробуйте позже.",
        }

    parsed = _parse_json_response(content)
    if not isinstance(parsed, dict):
        return {
            "tool": None,
            "answer": "Не удалось разобрать ответ. Попробуйте переформулировать запрос.",
        }

    tool = parsed.get("tool")
    if tool is None:
        answer = parsed.get("answer")
        if not isinstance(answer, str) or not answer.strip():
            answer = "Я могу помочь с отзывами: показать список, найти, добавить, статистику или черновик ответа."
        return {"tool": None, "answer": answer}

    if not isinstance(tool, str) or tool not in VALID_TOOLS:
        return {
            "tool": None,
            "answer": "Не удалось выбрать инструмент для запроса. Попробуйте другой запрос.",
        }

    arguments = parsed.get("arguments")
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        return {
            "tool": None,
            "answer": "Не удалось разобрать аргументы. Попробуйте переформулировать запрос.",
        }

    # Argument types and ranges are enforced by the MCP server, not here.
    return {"tool": tool, "arguments": arguments}
