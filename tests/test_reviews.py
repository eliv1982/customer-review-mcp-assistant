"""Review tools against a temporary SQLite database."""

from pathlib import Path

import pytest

import db
import tools

ROOT_DB = Path(__file__).resolve().parents[1] / "mcp_server" / "reviews.db"

SAMPLE = [
    ("Alice", "Website", 5, "Great service, thanks"),
    ("Bob", "Telegram", 1, "Delivery was late"),
    ("Carol", "Marketplace", 2, "Box arrived damaged"),
    ("Dan", "Google Maps", 3, "Okay"),
    ("Eve", "Website", 4, "Fast delivery"),
]


@pytest.fixture
def sample():
    """Replace the seed data with five known reviews; returns them oldest first."""
    conn = db.get_connection()
    conn.execute("DELETE FROM reviews")
    conn.commit()
    conn.close()
    return [tools.add_review(*row) for row in SAMPLE]


def names(reviews):
    return [r["customer_name"] for r in reviews]


def count_rows():
    conn = db.get_connection()
    try:
        return conn.execute("SELECT COUNT(*) FROM reviews").fetchone()[0]
    finally:
        conn.close()


def test_tests_use_a_temporary_database(temp_db):
    assert db.DB_PATH == temp_db
    assert db.DB_PATH != ROOT_DB


def test_add_review_stores_and_returns_the_row(sample):
    review = tools.add_review("Zoe", "Telegram", 4, "Nice")
    assert review["id"] > sample[-1]["id"]
    assert (review["customer_name"], review["source"], review["rating"]) == (
        "Zoe",
        "Telegram",
        4,
    )
    assert review["text"] == "Nice"
    assert review["status"] == "new"
    assert review["created_at"]
    assert tools.list_reviews(1) == [review]


@pytest.mark.parametrize("rating", [1, 5])
def test_add_review_accepts_rating_boundaries(rating):
    assert tools.add_review("Zoe", "Telegram", rating, "ok")["rating"] == rating


@pytest.mark.parametrize("rating", [0, 6, -1, 100])
def test_add_review_rejects_invalid_rating_without_inserting(rating):
    before = count_rows()
    with pytest.raises(tools.ToolArgumentError, match="1 до 5"):
        tools.add_review("Zoe", "Telegram", rating, "bad")
    assert count_rows() == before


def test_list_reviews_is_newest_first_and_honours_limit(sample):
    assert names(tools.list_reviews(3)) == ["Eve", "Dan", "Carol"]
    assert len(tools.list_reviews(100)) == 5


def test_find_reviews_matches_text_or_customer_name(sample):
    assert names(tools.find_reviews("delivery")) == ["Eve", "Bob"]
    assert names(tools.find_reviews("alice")) == ["Alice"]  # name, ASCII case-insensitive
    assert tools.find_reviews("no such thing") == []
    assert names(tools.find_reviews("delivery", limit=1)) == ["Eve"]


def test_find_reviews_by_rating_filters_exactly(sample):
    assert names(tools.find_reviews_by_rating(2)) == ["Carol"]
    assert tools.find_reviews_by_rating(5, limit=10)[0]["customer_name"] == "Alice"


def test_find_negative_reviews_returns_only_ratings_1_and_2(sample):
    negative = tools.find_negative_reviews()
    assert names(negative) == ["Carol", "Bob"]
    assert all(r["rating"] <= 2 for r in negative)


def test_negative_limit_is_rejected_instead_of_returning_everything(sample):
    # Raw SQLite treats LIMIT -1 as "no limit"; the public tool contract must not.
    for tool in ("list_reviews", "find_negative_reviews"):
        with pytest.raises(tools.ToolArgumentError, match="limit"):
            tools.call_tool_by_name(tool, {"limit": -1})


def test_review_stats(sample):
    stats = tools.get_review_stats()
    assert stats["total_reviews"] == 5
    assert stats["average_rating"] == 3.0
    assert (stats["positive_count"], stats["neutral_count"], stats["negative_count"]) == (2, 1, 2)
    assert stats["by_source"] == {
        "Website": 2,
        "Telegram": 1,
        "Marketplace": 1,
        "Google Maps": 1,
    }
    assert stats["by_status"] == {"new": 5}


def test_draft_reply_depends_on_rating_and_tone(sample):
    bob, eve = sample[1], sample[4]
    negative = tools.draft_reply(bob["id"], "warm")
    positive = tools.draft_reply(eve["id"])
    assert negative["review"] == bob
    assert "извинения" in negative["draft_reply"]
    assert "😊" in negative["draft_reply"]
    assert "Большое спасибо" in positive["draft_reply"]


def test_draft_reply_unknown_review_id(sample):
    with pytest.raises(tools.ToolDomainError, match="не найден"):
        tools.draft_reply(10**9)
