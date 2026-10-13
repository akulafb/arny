"""End-to-end tests: run the installed `arny` / `arny-mcp` scripts as subprocesses.

External tools are faked: a stub `luci` script, a Granola export folder and a
temporary ~/.Life. No real user data and no network is touched.
"""

import os
import subprocess
import sys
from pathlib import Path

import pytest
from fastmcp import Client
from fastmcp.client.transports import StdioTransport

BIN = Path(sys.executable).parent
LLM_KEYS = ("GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "ARNY_LLM_PROVIDER")

FAKE_LUCI = """#!{python}
import json, sys
if sys.argv[1] == "search":
    print(json.dumps({{"results": [{{
        "captureId": 7, "timestamp": 1760300000000, "app": "Code",
        "windowTitle": "arny/cli.py", "text": "editing the arny synthesizer", "score": 0.9
    }}]}}))
else:
    print(json.dumps({{"segments": []}}))
"""


def _env(tmp_path: Path, *, luci: bool = True, life: bool = True) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k not in LLM_KEYS}
    env["ARNY_SKIP_DOTENV"] = "1"
    env["FB_MODE_PATH"] = str(tmp_path / "runs-missing")
    env["GRANOLA_CLI_PATH"] = str(tmp_path / "no-granola")
    env["LUCI_PATH"] = str(tmp_path / "no-luci")
    env["LIFE_PATH"] = str(tmp_path / "life-missing")
    env.pop("ARNY_GRANOLA_EXPORT_DIR", None)
    env.pop("ARNY_GRANOLA_TOKEN", None)
    if luci:
        stub = tmp_path / "luci"
        stub.write_text(FAKE_LUCI.format(python=sys.executable), encoding="utf-8")
        stub.chmod(0o755)
        env["LUCI_PATH"] = str(stub)
    if life:
        daily = tmp_path / "life" / "reflections" / "daily"
        daily.mkdir(parents=True)
        (daily / "2026-10-12.md").write_text("# Daily\n\nShipped the arny adapters.\n", encoding="utf-8")
        export = tmp_path / "export"
        export.mkdir()
        (export / "granola.csv").write_text(
            "Title,Date,Summary,Transcript\nArny planning,2026-10-11,Plan,Me: hi\n", encoding="utf-8"
        )
        env["LIFE_PATH"] = str(tmp_path / "life")
        env["ARNY_GRANOLA_EXPORT_DIR"] = str(export)
    return env


def _arny(*args: str, env: dict[str, str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(BIN / "arny"), *args], check=False, env=env, capture_output=True, text=True, timeout=60
    )


def test_help(tmp_path):
    result = _arny("--help", env=_env(tmp_path, luci=False, life=False))
    assert result.returncode == 0
    assert "serve" in result.stdout and "ask" in result.stdout


def test_question_returns_excerpts_from_all_sources(tmp_path):
    result = _arny("what did I do on arny?", env=_env(tmp_path))
    assert result.returncode == 0, result.stderr
    for heading in ("## Luci", "## Granola", "## History"):
        assert heading in result.stdout
    assert "editing the arny synthesizer" in result.stdout
    assert "Arny planning" in result.stdout
    assert "Shipped the arny adapters." in result.stdout


def test_question_with_every_source_missing_does_not_crash(tmp_path):
    result = _arny("test question", env=_env(tmp_path, luci=False, life=False))
    assert result.returncode == 0, result.stderr
    assert "No matching excerpts" in result.stdout
    assert "warning: Luci:" in result.stderr
    assert "warning: Granola:" in result.stderr


@pytest.mark.parametrize("command", [["arny", "serve"], ["arny-mcp"]])
async def test_stdio_server_lists_tools(tmp_path, command):
    transport = StdioTransport(
        command=str(BIN / command[0]), args=command[1:], env=_env(tmp_path, luci=False, life=False)
    )
    async with Client(transport) as client:
        names = {t.name for t in await client.list_tools()}
        pong = await client.call_tool("ping", {})
    assert {"ping", "search_luci", "get_granola_meetings", "search_agent_history"} <= names
    assert pong.data == "pong"
