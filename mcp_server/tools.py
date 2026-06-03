"""MCP-style tools for customer review management."""

import ast
import operator
from datetime import datetime

from db import get_connection, init_db, row_to_dict

# Safe calculator operators
_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY_OPS = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _fetch_reviews(sql: str, params: tuple = ()) -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute(sql, params).fetchall()
        return [row_to_dict(r) for r in rows]
    finally:
        conn.close()


def list_reviews(limit: int = 10) -> list[dict]:
    return _fetch_reviews(
        "SELECT * FROM reviews ORDER BY id DESC LIMIT ?",
        (limit,),
    )


def find_reviews(query: str, limit: int = 10) -> list[dict]:
    pattern = f"%{query}%"
    return _fetch_reviews(
        """
        SELECT * FROM reviews
        WHERE text LIKE ? OR customer_name LIKE ?
        ORDER BY id DESC LIMIT ?
        """,
        (pattern, pattern, limit),
    )


def find_reviews_by_rating(rating: int, limit: int = 10) -> list[dict]:
    return _fetch_reviews(
        "SELECT * FROM reviews WHERE rating = ? ORDER BY id DESC LIMIT ?",
        (rating, limit),
    )


def find_negative_reviews(limit: int = 10) -> list[dict]:
    return _fetch_reviews(
        "SELECT * FROM reviews WHERE rating <= 2 ORDER BY id DESC LIMIT ?",
        (limit,),
    )


def add_review(
    customer_name: str,
    source: str,
    rating: int,
    text: str,
) -> dict:
    if not 1 <= rating <= 5:
        raise ValueError("Рейтинг должен быть от 1 до 5")

    created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO reviews (customer_name, source, rating, text, status, created_at)
            VALUES (?, ?, ?, ?, 'new', ?)
            """,
            (customer_name, source, rating, text, created_at),
        )
        conn.commit()
        review_id = cursor.lastrowid
        row = conn.execute(
            "SELECT * FROM reviews WHERE id = ?", (review_id,)
        ).fetchone()
        return row_to_dict(row)
    finally:
        conn.close()


def get_review_stats() -> dict:
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        avg_row = conn.execute("SELECT AVG(rating) FROM reviews").fetchone()
        average_rating = round(avg_row[0], 2) if avg_row[0] is not None else 0.0

        positive = conn.execute(
            "SELECT COUNT(*) FROM reviews WHERE rating >= 4"
        ).fetchone()[0]
        neutral = conn.execute(
            "SELECT COUNT(*) FROM reviews WHERE rating = 3"
        ).fetchone()[0]
        negative = conn.execute(
            "SELECT COUNT(*) FROM reviews WHERE rating <= 2"
        ).fetchone()[0]

        by_source_rows = conn.execute(
            "SELECT source, COUNT(*) as count FROM reviews GROUP BY source"
        ).fetchall()
        by_source = {r["source"]: r["count"] for r in by_source_rows}

        by_status_rows = conn.execute(
            "SELECT status, COUNT(*) as count FROM reviews GROUP BY status"
        ).fetchall()
        by_status = {r["status"]: r["count"] for r in by_status_rows}

        return {
            "total_reviews": total,
            "average_rating": average_rating,
            "positive_count": positive,
            "neutral_count": neutral,
            "negative_count": negative,
            "by_source": by_source,
            "by_status": by_status,
        }
    finally:
        conn.close()


def _apply_tone(base: str, tone: str) -> str:
    tone = tone.lower()
    if tone == "warm":
        return f"Здравствуйте! 😊 {base} С уважением и теплом, команда магазина."
    if tone == "professional":
        return f"Уважаемый клиент, {base} С уважением, служба поддержки."
    return f"Здравствуйте! {base} С уважением, команда магазина."


def draft_reply(review_id: int, tone: str = "neutral") -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM reviews WHERE id = ?", (review_id,)
        ).fetchone()
        if row is None:
            raise ValueError(f"Отзыв с id={review_id} не найден")

        review = row_to_dict(row)
        rating = review["rating"]

        if rating <= 2:
            base = (
                "Приносим искренние извинения за доставленные неудобства. "
                "Мы признаём проблему и уже работаем над её устранением. "
                "Пожалуйста, свяжитесь с нами — мы обязательно поможем решить ситуацию."
            )
        elif rating == 3:
            base = (
                "Благодарим вас за обратную связь. "
                "Ваш отзыв поможет нам улучшить сервис и сделать покупки удобнее."
            )
        else:
            base = (
                "Большое спасибо за ваш отзыв! "
                "Мы рады, что вам понравилось. Будем рады видеть вас снова!"
            )

        draft = _apply_tone(base, tone)
        return {"review": review, "draft_reply": draft}
    finally:
        conn.close()


def _safe_eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.Num):  # Python < 3.8 compat
        return float(node.n)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY_OPS:
        return _UNARY_OPS[type(node.op)](_safe_eval_node(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN_OPS:
        left = _safe_eval_node(node.left)
        right = _safe_eval_node(node.right)
        if isinstance(node.op, (ast.Div, ast.FloorDiv)) and right == 0:
            raise ZeroDivisionError("Деление на ноль")
        return _BIN_OPS[type(node.op)](left, right)
    raise ValueError("Недопустимое выражение")


def calculate(expression: str) -> dict:
    try:
        tree = ast.parse(expression.strip(), mode="eval")
        if not isinstance(tree.body, (ast.BinOp, ast.UnaryOp, ast.Constant)):
            if not isinstance(tree.body, ast.Num):
                raise ValueError("Недопустимое выражение")
        result = _safe_eval_node(tree.body)
        if result == int(result):
            result = int(result)
        return {"expression": expression, "result": result}
    except ZeroDivisionError:
        return {"expression": expression, "error": "Деление на ноль"}
    except (SyntaxError, ValueError, TypeError) as e:
        return {"expression": expression, "error": f"Ошибка вычисления: {e}"}


TOOL_FUNCTIONS = {
    "list_reviews": list_reviews,
    "find_reviews": find_reviews,
    "find_reviews_by_rating": find_reviews_by_rating,
    "find_negative_reviews": find_negative_reviews,
    "add_review": add_review,
    "get_review_stats": get_review_stats,
    "draft_reply": draft_reply,
    "calculate": calculate,
}

MCP_TOOLS = [
    {
        "name": "list_reviews",
        "description": "Возвращает последние отзывы клиентов",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Максимальное количество отзывов",
                    "default": 10,
                }
            },
        },
    },
    {
        "name": "find_reviews",
        "description": "Ищет отзывы по частичному совпадению в тексте или имени клиента",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Поисковый запрос"},
                "limit": {
                    "type": "integer",
                    "description": "Максимальное количество результатов",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "find_reviews_by_rating",
        "description": "Возвращает отзывы с конкретной оценкой (1-5)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "rating": {"type": "integer", "description": "Оценка от 1 до 5"},
                "limit": {
                    "type": "integer",
                    "description": "Максимальное количество результатов",
                    "default": 10,
                },
            },
            "required": ["rating"],
        },
    },
    {
        "name": "find_negative_reviews",
        "description": "Возвращает негативные отзывы (оценка 1 или 2)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Максимальное количество результатов",
                    "default": 10,
                }
            },
        },
    },
    {
        "name": "add_review",
        "description": "Добавляет новый отзыв клиента",
        "inputSchema": {
            "type": "object",
            "properties": {
                "customer_name": {"type": "string", "description": "Имя клиента"},
                "source": {
                    "type": "string",
                    "description": "Источник: Telegram, Website, Marketplace, Google Maps",
                },
                "rating": {"type": "integer", "description": "Оценка от 1 до 5"},
                "text": {"type": "string", "description": "Текст отзыва"},
            },
            "required": ["customer_name", "source", "rating", "text"],
        },
    },
    {
        "name": "get_review_stats",
        "description": "Возвращает статистику по отзывам",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "draft_reply",
        "description": "Генерирует черновик ответа на отзыв (rule-based, без LLM)",
        "inputSchema": {
            "type": "object",
            "properties": {
                "review_id": {"type": "integer", "description": "ID отзыва"},
                "tone": {
                    "type": "string",
                    "description": "Тон ответа: neutral, warm, professional",
                    "default": "neutral",
                },
            },
            "required": ["review_id"],
        },
    },
    {
        "name": "calculate",
        "description": "Безопасный калькулятор для арифметических выражений",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": "Математическое выражение, например: 1200 * 0.15",
                }
            },
            "required": ["expression"],
        },
    },
]


def call_tool_by_name(tool_name: str, arguments: dict):
    if tool_name not in TOOL_FUNCTIONS:
        raise ValueError(f"Неизвестный инструмент: {tool_name}")
    func = TOOL_FUNCTIONS[tool_name]
    return func(**arguments)


# Initialize DB on import
init_db()
