"""Telegram bot for customer review assistant."""

import asyncio
import logging

from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message

from config import TELEGRAM_BOT_TOKEN
from llm_router import route_user_message
from mcp_client import MCPClientError, call_tool

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


def _stars(rating: int) -> str:
    return "⭐" * rating + "☆" * (5 - rating)


def _format_review(review: dict) -> str:
    return (
        f"🆔 <b>ID:</b> {review['id']}\n"
        f"👤 <b>Клиент:</b> {review['customer_name']}\n"
        f"📍 <b>Источник:</b> {review['source']}\n"
        f"⭐ <b>Рейтинг:</b> {_stars(review['rating'])} ({review['rating']}/5)\n"
        f"📝 <b>Текст:</b> {review['text']}\n"
        f"📌 <b>Статус:</b> {review['status']}\n"
        f"🕐 <b>Дата:</b> {review['created_at']}"
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
        f"  • {src}: {cnt}" for src, cnt in stats.get("by_source", {}).items()
    )
    by_status = "\n".join(
        f"  • {st}: {cnt}" for st, cnt in stats.get("by_status", {}).items()
    )
    return (
        "📊 <b>Статистика отзывов</b>\n\n"
        f"📦 <b>Всего отзывов:</b> {stats['total_reviews']}\n"
        f"⭐ <b>Средний рейтинг:</b> {stats['average_rating']}\n\n"
        f"😊 <b>Положительные (4-5):</b> {stats['positive_count']}\n"
        f"😐 <b>Нейтральные (3):</b> {stats['neutral_count']}\n"
        f"😞 <b>Негативные (1-2):</b> {stats['negative_count']}\n\n"
        f"<b>По источникам:</b>\n{by_source or '  —'}\n\n"
        f"<b>По статусам:</b>\n{by_status or '  —'}"
    )


def _format_draft_reply(data: dict) -> str:
    review = data["review"]
    draft = data["draft_reply"]
    return (
        "✉️ <b>Черновик ответа</b>\n\n"
        f"<b>Исходный отзыв:</b>\n{_format_review(review)}\n\n"
        f"<b>Черновик ответа:</b>\n{draft}"
    )


def _format_calculate(data: dict) -> str:
    if "error" in data:
        return f"❌ {data['error']}"
    return f"🧮 <b>{data['expression']}</b> = <b>{data['result']}</b>"


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
    return str(result)


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
    except MCPClientError as e:
        logger.exception("MCP client error")
        await message.answer(
            f"⚠️ Не удалось связаться с сервером отзывов.\n\n"
            f"Убедитесь, что MCP-сервер запущен:\n"
            f"<code>cd mcp_server && python server.py</code>\n\n"
            f"Ошибка: {e}",
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
