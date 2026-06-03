"""Configuration from the repository root .env file."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT_DIR / ".env"

load_dotenv(ENV_PATH)

OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://127.0.0.1:8008")


def _require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name} не задан. "
            f"Добавьте его в файл {ENV_PATH} "
            f"(можно скопировать из {ROOT_DIR / '.env.example'})."
        )
    return value


TELEGRAM_BOT_TOKEN = _require_env("TELEGRAM_BOT_TOKEN")
OPENAI_API_KEY = _require_env("OPENAI_API_KEY")
