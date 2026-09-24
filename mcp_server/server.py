"""MCP-style HTTP server for customer review tools."""

import logging
from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel

from tools import MCP_TOOLS, ToolError, call_tool_by_name

logger = logging.getLogger(__name__)

app = FastAPI(title="Customer Review MCP Server")


class CallToolRequest(BaseModel):
    tool: str
    # Any JSON value is accepted here on purpose: a non-object must reach the tool
    # validator and get the normal {"ok": false} answer, not a Pydantic HTTP 422.
    # A missing or null "arguments" means "no arguments" ({}).
    arguments: Any = None


@app.get("/")
def root():
    return {
        "service": "customer-review-mcp-assistant",
        "status": "ok",
    }


@app.get("/tools")
def get_tools():
    return {"tools": MCP_TOOLS}


@app.post("/call_tool")
def call_tool(request: CallToolRequest):
    arguments = {} if request.arguments is None else request.arguments
    try:
        result = call_tool_by_name(request.tool, arguments)
        return {"ok": True, "tool": request.tool, "result": result}
    except ToolError as e:
        # Only this explicit family is safe to show; its message is written for clients.
        return {"ok": False, "error": str(e)}
    except Exception:
        # Anything else (ValueError included) may carry paths, SQL or secrets.
        logger.exception("Tool %s failed", request.tool)
        return {"ok": False, "error": "Внутренняя ошибка инструмента"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8008)
