"""L0 protocol backbone: a tiny synchronous MCP stdio client.

The platform's north star is "every layer speaks MCP." This helper spawns an MCP
server over stdio, calls one tool, and returns the parsed JSON result — synchronously,
so adapters don't have to be async.

If the `mcp` SDK isn't installed, `available()` returns False and adapters fall back
to their CLI path. That keeps the loop bootable with zero extra installs while MCP
remains the default, dogfooded transport.
"""
from __future__ import annotations

import json
from typing import Any


def available() -> bool:
    try:
        import mcp  # noqa: F401
        return True
    except Exception:
        return False


def call_tool(server_cmd: list[str], tool: str, arguments: dict) -> Any:
    """Spawn `server_cmd` as a stdio MCP server, call `tool(arguments)`, return JSON.

    Raises if the SDK is missing — callers should gate on `available()` first.
    """
    import anyio
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    async def _run() -> Any:
        params = StdioServerParameters(command=server_cmd[0], args=server_cmd[1:])
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool, arguments)
                return _parse(result)

    return anyio.run(_run)


def _parse(result: Any) -> Any:
    """Pull the JSON payload out of an MCP CallToolResult."""
    content = getattr(result, "content", None) or []
    for block in content:
        text = getattr(block, "text", None)
        if text:
            try:
                return json.loads(text)
            except json.JSONDecodeError:
                return {"text": text}
    sc = getattr(result, "structuredContent", None)
    if sc:
        return sc
    return {}
