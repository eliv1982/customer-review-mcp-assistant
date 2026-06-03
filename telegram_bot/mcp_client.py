"""HTTP client for MCP-style server."""

import requests

from config import MCP_SERVER_URL


class MCPClientError(Exception):
    pass


def get_tools() -> list[dict]:
    try:
        response = requests.get(f"{MCP_SERVER_URL}/tools", timeout=10)
        response.raise_for_status()
        data = response.json()
        return data.get("tools", [])
    except requests.RequestException as e:
        raise MCPClientError(
            f"Не удалось подключиться к MCP-серверу ({MCP_SERVER_URL}): {e}"
        ) from e


def call_tool(tool_name: str, arguments: dict | None = None) -> dict:
    payload = {"tool": tool_name, "arguments": arguments or {}}
    try:
        response = requests.post(
            f"{MCP_SERVER_URL}/call_tool",
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        if not data.get("ok"):
            raise MCPClientError(data.get("error", "Неизвестная ошибка MCP-сервера"))
        return data
    except requests.RequestException as e:
        raise MCPClientError(
            f"Не удалось вызвать инструмент на MCP-сервере: {e}"
        ) from e
