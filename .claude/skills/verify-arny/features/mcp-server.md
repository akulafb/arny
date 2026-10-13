# Feature: FastMCP Core Server

## Sub-features
- Server identity: name `arny`, instructions configured.
- Core tools: `ping` returns "pong", `status` returns server status dictionary.

## How to get to it (user POV)
- Launched as an MCP server over stdio via `arny serve` or `arny-mcp`.
- Connected to via Claude Code, Raycast, Cursor, or FastMCP client.

## Driving it with pytest / Client
```bash
uv run python -c "
import asyncio
from fastmcp import Client
from arny.server import mcp

async def test():
    async with Client(mcp) as client:
        tools = await client.list_tools()
        names = [t.name for t in tools]
        assert 'ping' in names
        assert 'status' in names
        ping_res = await client.call_tool('ping', {})
        assert ping_res.data == 'pong'

asyncio.run(test())
"
```

## Gotchas
- Pydantic models returned by tools serialize as structured content dicts over the MCP protocol.
