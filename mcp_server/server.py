"""MCP-style HTTP server for customer review tools."""

from fastapi import FastAPI
from pydantic import BaseModel

from tools import MCP_TOOLS, call_tool_by_name

app = FastAPI(title="Customer Review MCP Server")


class CallToolRequest(BaseModel):
    tool: str
    arguments: dict = {}


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
    try:
        result = call_tool_by_name(request.tool, request.arguments)
        return {"ok": True, "tool": request.tool, "result": result}
    except Exception as e:
        return {"ok": False, "error": str(e)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8008)
