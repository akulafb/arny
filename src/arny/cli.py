"""Command-line interface for Arny (the `arny` script).

`arny "<question>"` is routed to the `ask` command by `main`, because Click
would otherwise read a free-text question as an unknown subcommand.
"""

import os
import sys
from pathlib import Path
from typing import Annotated

from dotenv import load_dotenv
import typer

from arny.synthesizer import answer, gather

# Automatically load .env from current directory, ~/.arny/.env, or ~/.env if present
if not os.environ.get("ARNY_SKIP_DOTENV"):
    for env_path in [Path.cwd() / ".env", Path.home() / ".arny" / ".env", Path.home() / ".env"]:
        if env_path.is_file():
            load_dotenv(env_path)

app = typer.Typer(help="Arny: Life & Activity assistant.", no_args_is_help=True)


@app.callback()
def _root() -> None:
    """Arny: Life & Activity assistant.

    Ask a question with `arny "<question>"`, or run the MCP server with `arny serve`.
    """


@app.command()
def serve() -> None:
    """Run the Arny MCP server over stdio."""
    from arny.server import mcp

    mcp.run()


@app.command()
def ask(
    question: Annotated[list[str], typer.Argument(help="Your question, e.g. what did I work on today?")],
) -> None:
    """Answer a question from Luci, Granola and History (the default for `arny "<question>"`)."""
    from arny.adapters.granola import GranolaAdapter
    from arny.adapters.history import HistoryAdapter
    from arny.adapters.luci import LuciAdapter

    text = " ".join(question)
    found = gather(text, luci=LuciAdapter(), granola=GranolaAdapter.from_env(), history=HistoryAdapter())
    result = answer(text, found.excerpts)
    typer.echo(result.text)
    for warning in found.warnings + result.warnings:
        typer.echo(f"warning: {warning}", err=True)


def route_args(args: list[str]) -> list[str]:
    """Prefix `ask` when the first token is not a subcommand or option."""
    commands = {c.name or c.callback.__name__ for c in app.registered_commands}
    if args and not args[0].startswith("-") and args[0] not in commands:
        return ["ask", *args]
    return args


def main() -> None:
    app(args=route_args(sys.argv[1:]), prog_name="arny")
