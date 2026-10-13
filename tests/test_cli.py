from unittest.mock import patch

from typer.testing import CliRunner

from arny.cli import app

runner = CliRunner()


def test_serve_runs_the_mcp_server():
    with patch("arny.server.mcp.run") as run:
        result = runner.invoke(app, ["serve"])
    assert result.exit_code == 0, result.output
    run.assert_called_once_with()


def test_arny_mcp_entrypoint_runs_the_mcp_server():
    from arny.server import main

    with patch("arny.server.mcp.run") as run:
        main()
    run.assert_called_once_with()


def test_help_lists_serve_command():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "serve" in result.output


def test_route_args_sends_free_text_to_ask():
    from arny.cli import route_args

    assert route_args(["what did I do?"]) == ["ask", "what did I do?"]
    assert route_args(["serve"]) == ["serve"]
    assert route_args(["ask", "x"]) == ["ask", "x"]
    assert route_args(["--help"]) == ["--help"]
    assert route_args([]) == []


def test_ask_prints_ranked_excerpts_without_llm_key(monkeypatch):
    from arny.synthesizer import Excerpt, Gathered

    for key in ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    found = Gathered(
        excerpts=[Excerpt(source="History", title="Daily", text="arny notes")],
        warnings=["Luci: Luci CLI not found."],
    )
    with patch("arny.cli.gather", return_value=found) as gather:
        result = runner.invoke(app, ["ask", "what", "about", "arny"])
    assert result.exit_code == 0, result.output
    assert gather.call_args.args[0] == "what about arny"
    assert "## History" in result.output
    assert "arny notes" in result.output
    assert "Luci CLI not found" in result.output


def test_help_lists_ask_command():
    result = runner.invoke(app, ["--help"])
    assert "ask" in result.output
