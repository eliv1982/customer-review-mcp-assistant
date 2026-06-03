"""SQLite database for customer reviews."""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent / "reviews.db"

SOURCES = ["Telegram", "Website", "Marketplace", "Google Maps"]

SEED_REVIEWS = [
    ("Иван Петров", "Google Maps", 5, "Отличный сервис, всё быстро и качественно!", "new"),
    ("Мария Сидорова", "Website", 4, "Хороший товар, доставка в срок.", "answered"),
    ("Алексей Козлов", "Marketplace", 2, "Доставка задержалась на неделю, очень недоволен.", "new"),
    ("Елена Новикова", "Telegram", 1, "Товар не соответствует описанию, требую возврат.", "new"),
    ("Дмитрий Волков", "Google Maps", 5, "Рекомендую всем, лучший магазин в городе!", "answered"),
    ("Ольга Морозова", "Website", 3, "Нормально, но есть куда расти.", "new"),
    ("Сергей Лебедев", "Marketplace", 4, "Качество на высоте, цена адекватная.", "answered"),
    ("Анна Кузнецова", "Telegram", 2, "Доставка задержалась на три дня, поддержка не отвечала.", "new"),
    ("Павел Соколов", "Google Maps", 5, "Превосходное обслуживание, буду заказывать снова.", "answered"),
    ("Наталья Попова", "Website", 1, "Ужасное качество упаковки, товар пришёл повреждённым.", "new"),
    ("Андрей Фёдоров", "Marketplace", 3, "Средне, ожидал большего за эту цену.", "new"),
    ("Татьяна Орлова", "Telegram", 4, "Быстрая доставка, вежливый курьер.", "answered"),
    ("Михаил Зайцев", "Google Maps", 2, "Долго ждал ответ от поддержки по возврату.", "new"),
    ("Юлия Смирнова", "Website", 5, "Всё супер, спасибо за подарок к заказу!", "answered"),
    ("Виктор Егоров", "Marketplace", 3, "Товар ок, но доставка могла быть быстрее.", "new"),
    ("Екатерина Власова", "Telegram", 5, "Отличная консультация в чате, помогли выбрать размер.", "answered"),
    ("Роман Никитин", "Google Maps", 1, "Никогда больше не закажу здесь, полный разочарование.", "new"),
    ("Светлана Белова", "Website", 4, "Хороший ассортимент, удобный сайт.", "answered"),
    ("Игорь Крылов", "Marketplace", 2, "Пришёл не тот цвет, обмен затянулся.", "new"),
    ("Людмила Громова", "Telegram", 5, "Заказываю уже третий раз, всегда довольна!", "answered"),
    ("Константин Данилов", "Google Maps", 3, "Неплохо, но упаковка могла быть лучше.", "new"),
    ("Вера Степанова", "Website", 2, "Доставка в другой город заняла две недели.", "new"),
    ("Георгий Макаров", "Marketplace", 4, "Качественный продукт, рекомендую.", "answered"),
    ("Алина Романова", "Telegram", 1, "Оплата прошла, заказ так и не пришёл.", "new"),
    ("Борис Тихонов", "Google Maps", 4, "Хорошие цены и акции, буду следить за новинками.", "answered"),
    ("Дарья Комарова", "Website", 5, "Идеальное соотношение цена-качество!", "answered"),
    ("Фёдор Гусев", "Marketplace", 3, "Обычный магазин, ничего особенного.", "new"),
    ("Полина Ларина", "Telegram", 4, "Удобно заказывать через бота, доставка на следующий день.", "answered"),
    ("Станислав Медведев", "Google Maps", 2, "Курьер опоздал на два часа без предупреждения.", "new"),
    ("Кристина Андреева", "Website", 5, "Лучший опыт онлайн-покупок за последний год!", "answered"),
    ("Владимир Сорокин", "Marketplace", 1, "Товар бракованный, возврат денег отказали.", "new"),
    ("Оксана Жукова", "Telegram", 3, "Нормальный сервис, доставка иногда задерживается.", "new"),
]


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    conn = get_connection()
    try:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                customer_name TEXT NOT NULL,
                source TEXT NOT NULL,
                rating INTEGER NOT NULL,
                text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'new',
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()

        count = conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
        if count == 0:
            _seed_reviews(conn)
    finally:
        conn.close()


def _seed_reviews(conn: sqlite3.Connection) -> None:
    base_date = datetime.now()
    for i, (name, source, rating, text, status) in enumerate(SEED_REVIEWS):
        created_at = (base_date - timedelta(days=i % 14, hours=i % 24)).strftime(
            "%Y-%m-%d %H:%M:%S"
        )
        conn.execute(
            """
            INSERT INTO reviews (customer_name, source, rating, text, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, source, rating, text, status, created_at),
        )
    conn.commit()


def row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)
