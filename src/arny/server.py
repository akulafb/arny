"""FastMCP server for Arny."""

from fastmcp import FastMCP
from pydantic import BaseModel

from arny import __version__
from arny.tools import granola as granola_tools
from arny.tools import luci as luci_tools

mcp = FastMCP("arny", instructions="Life & Activity MCP Server", version=__version__)


class ServerStatus(BaseModel):
    name: str
    version: str
    status: str


@mcp.tool()
def ping() -> str:
    """Check that the server is reachable."""
    return "pong"


@mcp.tool()
def status() -> ServerStatus:
    """Report the server name, version and health."""
    return ServerStatus(name=mcp.name, version=__version__, status="ok")


luci_tools.register(mcp)
granola_tools.register(mcp)


def main() -> None:
    """Run the MCP server over stdio (the `arny-mcp` script)."""
    mcp.run()
