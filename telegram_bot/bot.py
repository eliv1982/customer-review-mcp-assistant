"""Telegram bot for customer review assistant."""

import asyncio
import html
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message

from config import TELEGRAM_BOT_TOKEN
from llm_router import route_user_message
from mcp_client import MCPConnectionError, MCPToolError, call_tool

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

START_TEXT = (
    "👋 Привет! Я помощник для работы с отзывами клиентов.\n\n"
    "Примеры запросов:\n"
    "• покажи последние отзывы\n"
    "• найди отзывы про доставку\n"
    "• покажи негативные отзывы\n"
    "• покажи статистику отзывов\n"
    "• добавь отзыв: Анна, Telegram, 2, доставка задержалась\n"
    "• подготовь ответ на отзыв 5 в тёплом тоне"
)


MAX_ERROR_LEN = 300


def _esc(value) -> str:
    """Escape a dynamic value for Telegram's HTML parse mode.

    Telegram only requires &, < and > to be escaped in text, so quotes stay as is.
    """
    return html.escape(str(value), quote=False)


def _stars(rating: int) -> str:
    return "⭐" * rating + "☆" * (5 - rating)


def _format_review(review: dict) -> str:
    return (
        f"🆔 <b>ID:</b> {_esc(review['id'])}\n"
        f"👤 <b>Клиент:</b> {_esc(review['customer_name'])}\n"
        f"📍 <b>Источник:</b> {_esc(review['source'])}\n"
        f"⭐ <b>Рейтинг:</b> {_stars(review['rating'])} ({_esc(review['rating'])}/5)\n"
        f"📝 <b>Текст:</b> {_esc(review['text'])}\n"
        f"📌 <b>Статус:</b> {_esc(review['status'])}\n"
        f"🕐 <b>Дата:</b> {_esc(review['created_at'])}"
    )


def _format_reviews_list(reviews: list) -> str:
    if not reviews:
        return "Отзывы не найдены."
    parts = [f"📋 <b>Найдено отзывов:</b> {len(reviews)}\n"]
    for i, review in enumerate(reviews, 1):
        parts.append(f"\n——— <b>#{i}</b> ———\n{_format_review(review)}")
    return "\n".join(parts)


def _format_stats(stats: dict) -> str:
    by_source = "\n".join(
        f"  • {_esc(src)}: {_esc(cnt)}" for src, cnt in stats.get("by_source", {}).items()
    )
    by_status = "\n".join(
        f"  • {_esc(st)}: {_esc(cnt)}" for st, cnt in stats.get("by_status", {}).items()
    )
    return (
        "📊 <b>Статистика отзывов</b>\n\n"
        f"📦 <b>Всего отзывов:</b> {_esc(stats['total_reviews'])}\n"
        f"⭐ <b>Средний рейтинг:</b> {_esc(stats['average_rating'])}\n\n"
        f"😊 <b>Положительные (4-5):</b> {_esc(stats['positive_count'])}\n"
        f"😐 <b>Нейтральные (3):</b> {_esc(stats['neutral_count'])}\n"
        f"😞 <b>Негативные (1-2):</b> {_esc(stats['negative_count'])}\n\n"
        f"<b>По источникам:</b>\n{by_source or '  —'}\n\n"
        f"<b>По статусам:</b>\n{by_status or '  —'}"
    )


def _format_draft_reply(data: dict) -> str:
    review = data["review"]
    draft = data["draft_reply"]
    return (
        "✉️ <b>Черновик ответа</b>\n\n"
        f"<b>Исходный отзыв:</b>\n{_format_review(review)}\n\n"
        f"<b>Черновик ответа:</b>\n{_esc(draft)}"
    )


def _format_calculate(data: dict) -> str:
    if "error" in data:
        return f"❌ {_esc(data['error'])}"
    return f"🧮 <b>{_esc(data['expression'])}</b> = <b>{_esc(data['result'])}</b>"


def format_tool_result(tool_name: str, result) -> str:
    if tool_name == "get_review_stats":
        return _format_stats(result)
    if tool_name == "draft_reply":
        return _format_draft_reply(result)
    if tool_name == "calculate":
        return _format_calculate(result)
    if tool_name == "add_review":
        return "✅ <b>Отзыв добавлен!</b>\n\n" + _format_review(result)
    if isinstance(result, list):
        return _format_reviews_list(result)
    return _esc(result)


async def cmd_start(message: Message) -> None:
    await message.answer(START_TEXT)


async def handle_message(message: Message) -> None:
    user_text = (message.text or "").strip()
    if not user_text:
        await message.answer("Отправьте текстовый запрос.")
        return

    await message.bot.send_chat_action(message.chat.id, "typing")

    routing = route_user_message(user_text)

    if routing.get("tool") is None:
        await message.answer(routing.get("answer", "Не удалось обработать запрос."))
        return

    tool_name = routing["tool"]
    arguments = routing.get("arguments", {})

    try:
        response = call_tool(tool_name, arguments)
        formatted = format_tool_result(tool_name, response.get("result"))
        await message.answer(formatted, parse_mode="HTML")
    except MCPConnectionError:
        logger.exception("MCP server is unreachable")
        await message.answer(
            "⚠️ Не удалось связаться с сервером отзывов.\n\n"
            "Убедитесь, что MCP-сервер запущен:\n"
            "<code>cd mcp_server &amp;&amp; python server.py</code>",
            parse_mode="HTML",
        )
    except MCPToolError as e:
        logger.warning("MCP tool %s failed: %s", tool_name, e)
        await message.answer(
            f"⚠️ Инструмент не смог выполнить запрос: {_esc(str(e)[:MAX_ERROR_LEN])}",
            parse_mode="HTML",
        )


async def main() -> None:
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    dp = Dispatcher()
    dp.message.register(cmd_start, CommandStart())
    dp.message.register(handle_message, F.text)

    logger.info("Bot started")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
