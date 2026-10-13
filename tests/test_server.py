from fastmcp import Client

from arny import __version__
from arny.server import mcp


def test_server_is_named_arny():
    assert mcp.name == "arny"


async def test_ping_tool_returns_pong():
    async with Client(mcp) as client:
        result = await client.call_tool("ping", {})
    assert not result.is_error
    assert result.data == "pong"


async def test_status_tool_reports_server_state():
    async with Client(mcp) as client:
        result = await client.call_tool("status", {})
    assert not result.is_error
    assert result.structured_content == {
        "name": "arny",
        "version": __version__,
        "status": "ok",
    }


async def test_server_lists_ping_and_status_tools():
    async with Client(mcp) as client:
        tools = await client.list_tools()
    assert {"ping", "status"} <= {t.name for t in tools}
