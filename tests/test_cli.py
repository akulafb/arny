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
