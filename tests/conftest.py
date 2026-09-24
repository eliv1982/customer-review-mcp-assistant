"""Shared test setup: everything runs offline against throwaway SQLite files."""

import asyncio
import os
import socket
import sys
import tempfile
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "mcp_server"), str(ROOT / "telegram_bot")]

# telegram_bot.config requires these at import time. load_dotenv() never overrides
# variables that are already set, so the real .env is not used by the tests.
os.environ["TELEGRAM_BOT_TOKEN"] = "test-telegram-token"
os.environ["OPENAI_API_KEY"] = "test-openai-key"
os.environ["OPENAI_MODEL"] = "test-model"
os.environ["MCP_SERVER_URL"] = "http://mcp.test"

import db  # noqa: E402

# tools.py runs init_db() when imported: point it at a throwaway file first so the
# repository's mcp_server/reviews.db is never opened by the test run.
_import_time_dir = tempfile.TemporaryDirectory()
db.DB_PATH = Path(_import_time_dir.name) / "import_time.db"

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Fresh, seeded database per test."""
    path = tmp_path / "reviews.db"
    monkeypatch.setattr(db, "DB_PATH", path)
    db.init_db()
    return path


@pytest.fixture
def http():
    """http("POST", "/call_tool", json=...): request the FastAPI app in-process (no sockets)."""
    from server import app

    def request(method, path, **kwargs):
        async def send():
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
                return await client.request(method, path, **kwargs)

        return asyncio.run(send())

    return request


@pytest.fixture(autouse=True)
def block_network(monkeypatch):
    """Fail loudly if a test tries to reach Telegram, OpenAI or any other host."""
    real_connect = socket.socket.connect

    def guarded_connect(self, address, *args, **kwargs):
        host = address[0] if isinstance(address, tuple) else address
        if host not in _LOCAL_HOSTS:
            raise RuntimeError(f"network access is blocked in tests: {address!r}")
        return real_connect(self, address, *args, **kwargs)

    def guarded_getaddrinfo(host, *args, **kwargs):
        raise RuntimeError(f"DNS lookup is blocked in tests: {host!r}")

    monkeypatch.setattr(socket.socket, "connect", guarded_connect)
    monkeypatch.setattr(socket, "getaddrinfo", guarded_getaddrinfo)
