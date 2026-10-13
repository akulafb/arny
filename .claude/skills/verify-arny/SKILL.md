---
name: verify-arny
description: "Verify Arny CLI and FastMCP server operations, tools, and behavior in the current checkout."
---

# Verify Arny

Scripted verification for Arny: FastMCP server inspection, tool execution, and CLI command validation.

## Launch
FastMCP stdio server and CLI commands run on-demand in the local virtual environment:
```bash
uv run python -c "from arny.server import mcp; print(mcp.name)"
```

## Doctor
Check that dependencies are installed and test suite runs cleanly:
```bash
uv sync
uv run pytest -q
```

## Drive
Run specific FastMCP tools or CLI invocations:
```bash
# Verify CLI help
uv run arny --help

# Verify FastMCP in-process tool discovery & invocation
uv run python -c "
import asyncio
from fastmcp import Client
from arny.server import mcp

async def test():
    async with Client(mcp) as client:
        tools = await client.list_tools()
        print('Tools:', [t.name for t in tools])
        res = await client.call_tool('ping', {})
        print('Ping result:', res.data)
        assert res.data == 'pong'

asyncio.run(test())
"
```

## Evidence
- Captured stdout/stderr from test runs or tool executions.
- Exit code 0 for all checks.

## Cleanup
No persistent daemon to terminate; scratch processes exit on command completion.
