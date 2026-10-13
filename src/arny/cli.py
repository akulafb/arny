"""Command-line interface for Arny (the `arny` script)."""

import typer

app = typer.Typer(help="Arny: Life & Activity assistant.", no_args_is_help=True)


@app.callback()
def _root() -> None:
    """Arny: Life & Activity assistant."""


@app.command()
def serve() -> None:
    """Run the Arny MCP server over stdio."""
    from arny.server import mcp

    mcp.run()


def main() -> None:
    app()
