"""HTTP client for MCP-style server."""

import requests

from config import MCP_SERVER_URL


class MCPClientError(Exception):
    """Base class for errors raised by call_tool()."""


class MCPConnectionError(MCPClientError):
    """The server could not be reached or did not answer with a valid response."""


class MCPToolError(MCPClientError):
    """The server answered normally, but the tool call failed ({"ok": false})."""


def _malformed(reason: str) -> MCPConnectionError:
    # Fixed text only: the raw response body is never echoed to the caller.
    return MCPConnectionError(f"MCP-сервер вернул ответ неожиданного формата ({reason})")


def call_tool(tool_name: str, arguments: dict | None = None) -> dict:
    # Only None means "no arguments"; other falsy values ([], "", 0, False) are sent
    # as they are so the server can reject them.
    payload = {"tool": tool_name, "arguments": {} if arguments is None else arguments}
    base_url = MCP_SERVER_URL.rstrip("/")
    try:
        response = requests.post(
            f"{base_url}/call_tool",
            json=payload,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError) as e:
        # ValueError: body is not JSON (older requests raise it unwrapped).
        raise MCPConnectionError(
            f"Не удалось вызвать инструмент на MCP-сервере ({base_url}): {e}"
        ) from e

    if not isinstance(data, dict):
        raise _malformed("ответ не JSON-объект")
    ok = data.get("ok")
    if not isinstance(ok, bool):
        raise _malformed("поле ok отсутствует или не bool")

    if not ok:
        error = data.get("error")
        if not isinstance(error, str) or not error.strip():
            raise _malformed("ok=false без текста ошибки")
        raise MCPToolError(error)

    if not isinstance(data.get("tool"), str) or data["tool"] != tool_name:
        raise _malformed("поле tool отсутствует или не совпадает с вызванным")
    if "result" not in data:
        raise _malformed("поле result отсутствует")
    return data
