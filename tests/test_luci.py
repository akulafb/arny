import json
import subprocess

import pytest
from fastmcp import Client

from arny.adapters.luci import LuciAdapter
from arny.server import mcp

SEARCH_FIXTURE = {
    "results": [
        {
            "captureId": 32090,
            "blockId": 2127383,
            "timestamp": 1791789802785,
            "app": "Orca",
            "windowTitle": "arny",
            "browserUrl": None,
            "text": "FastMCP … tools",
            "focusRect": "625,1272,1663,33",
            "screenshotPath": "/tmp/shot.png",
            "displayId": "1",
            "isFocused": True,
            "score": 0.83,
        }
    ]
}


class FakeRun:
    """Stands in for subprocess.run and records each call."""

    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout, self.returncode, self.stderr = stdout, returncode, stderr
        self.calls = []

    def __call__(self, args, **kwargs):
        self.calls.append(args)
        return subprocess.CompletedProcess(
            args, self.returncode, self.stdout, self.stderr
        )


@pytest.fixture
def luci_bin(tmp_path, monkeypatch):
    path = tmp_path / "luci"
    path.write_text("#!/bin/sh\nexit 0\n")
    path.chmod(0o755)
    monkeypatch.setenv("LUCI_PATH", str(path))
    return str(path)


def test_search_returns_screen_captures(luci_bin):
    run = FakeRun(stdout=json.dumps(SEARCH_FIXTURE))
    response = LuciAdapter(runner=run).search("FastMCP")

    assert response.status == "ok"
    assert response.warning is None
    assert len(response.results) == 1
    hit = response.results[0]
    assert (hit.capture_id, hit.app, hit.text, hit.timestamp) == (
        32090,
        "Orca",
        "FastMCP … tools",
        1791789802785,
    )
    assert run.calls == [
        [luci_bin, "search", "FastMCP", "--tr", "24h", "--limit", "20", "--json"]
    ]


TRANSCRIPT_FIXTURE = {
    "segments": [
        {
            "id": 9202,
            "sessionId": 217,
            "source": "screen",
            "tStart": 1791789939099,
            "tEnd": 1791789944099,
            "text": "hello",
        },
        {
            "id": 9203,
            "sessionId": 217,
            "source": "mic",
            "tStart": 1791789944133,
            "tEnd": 1791789949133,
            "text": "world",
        },
    ]
}


def test_search_passes_app_filter_and_clamps_limit(luci_bin):
    run = FakeRun(stdout='{"results": []}')
    response = LuciAdapter(runner=run).search(
        "x", app="Arc", limit=9999, time_range="7d"
    )

    assert response.status == "ok"
    assert response.results == []
    assert run.calls == [
        [
            luci_bin,
            "search",
            "x",
            "--tr",
            "7d",
            "--limit",
            "500",
            "--app",
            "Arc",
            "--json",
        ]
    ]


def test_search_accepts_bare_json_array(luci_bin):
    run = FakeRun(stdout=json.dumps(SEARCH_FIXTURE["results"]))
    response = LuciAdapter(runner=run).search("FastMCP")

    assert response.status == "ok"
    assert [r.capture_id for r in response.results] == [32090]


def test_transcripts_with_query(luci_bin):
    run = FakeRun(stdout=json.dumps(TRANSCRIPT_FIXTURE))
    response = LuciAdapter(runner=run).transcripts("standup", limit=2)

    assert response.status == "ok"
    assert [(s.id, s.session_id, s.source, s.text) for s in response.results] == [
        (9202, 217, "screen", "hello"),
        (9203, 217, "mic", "world"),
    ]
    assert run.calls == [
        [luci_bin, "transcript", "standup", "--tr", "7d", "--limit", "2", "--json"]
    ]


def test_transcripts_without_query_reads_recent_audio(luci_bin):
    run = FakeRun(stdout='{"segments": []}')
    LuciAdapter(runner=run).transcripts()

    assert run.calls == [
        [luci_bin, "transcript", "--tr", "7d", "--limit", "50", "--json"]
    ]


def test_missing_binary_is_unavailable_and_never_runs(tmp_path, monkeypatch):
    monkeypatch.setenv("LUCI_PATH", str(tmp_path / "nope"))
    run = FakeRun()
    response = LuciAdapter(runner=run).search("x")

    assert response.status == "unavailable"
    assert "not found" in response.warning
    assert response.results == []
    assert run.calls == []


@pytest.mark.parametrize(
    ("run", "warning_part"),
    [
        (FakeRun(returncode=2, stderr="Luci is not running"), "Luci is not running"),
        (FakeRun(returncode=1, stderr=""), "code 1"),
        (FakeRun(stdout="not json"), "not valid JSON"),
        (FakeRun(stdout='{"segments": [{"oops": 1}]}'), "unexpected"),
    ],
)
def test_failing_luci_is_unavailable(luci_bin, run, warning_part):
    response = LuciAdapter(runner=run).transcripts("x")

    assert response.status == "unavailable"
    assert warning_part in response.warning
    assert response.results == []


def test_bad_search_item_is_unavailable(luci_bin):
    response = LuciAdapter(runner=FakeRun(stdout='{"results": [{"oops": 1}]}')).search(
        "x"
    )

    assert response.status == "unavailable"
    assert "unexpected" in response.warning


@pytest.mark.parametrize(
    "error",
    [
        subprocess.TimeoutExpired(cmd="luci", timeout=30),
        PermissionError("operation not permitted"),
    ],
)
def test_runner_errors_are_unavailable(luci_bin, error):
    def boom(args, **kwargs):
        raise error

    response = LuciAdapter(runner=boom).search("x")

    assert response.status == "unavailable"
    assert response.warning


async def test_server_lists_luci_tools():
    async with Client(mcp) as client:
        tools = await client.list_tools()
    assert {"search_luci", "get_luci_transcripts"} <= {t.name for t in tools}


async def test_search_luci_tool_returns_results(luci_bin, monkeypatch):
    run = FakeRun(stdout=json.dumps(SEARCH_FIXTURE))
    monkeypatch.setattr("arny.adapters.luci.subprocess.run", run)

    async with Client(mcp) as client:
        result = await client.call_tool(
            "search_luci", {"query": "FastMCP", "app": "Orca", "limit": 5}
        )

    assert not result.is_error
    assert result.structured_content["status"] == "ok"
    assert result.structured_content["results"][0]["capture_id"] == 32090
    assert run.calls == [
        [
            luci_bin,
            "search",
            "FastMCP",
            "--tr",
            "24h",
            "--limit",
            "5",
            "--app",
            "Orca",
            "--json",
        ]
    ]


async def test_get_luci_transcripts_tool_returns_segments(luci_bin, monkeypatch):
    monkeypatch.setattr(
        "arny.adapters.luci.subprocess.run",
        FakeRun(stdout=json.dumps(TRANSCRIPT_FIXTURE)),
    )

    async with Client(mcp) as client:
        result = await client.call_tool("get_luci_transcripts", {})

    assert not result.is_error
    assert result.structured_content["status"] == "ok"
    assert [s["text"] for s in result.structured_content["results"]] == [
        "hello",
        "world",
    ]


async def test_tools_degrade_when_luci_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("LUCI_PATH", str(tmp_path / "nope"))

    async with Client(mcp) as client:
        search = await client.call_tool("search_luci", {"query": "x"})
        transcripts = await client.call_tool("get_luci_transcripts", {"query": "x"})

    for result in (search, transcripts):
        assert not result.is_error
        assert result.structured_content["status"] == "unavailable"
        assert result.structured_content["results"] == []
        assert "not found" in result.structured_content["warning"]


def _fake_luci(tmp_path, monkeypatch, body):
    path = tmp_path / "luci"
    path.write_text("#!/bin/sh\n" + body)
    path.chmod(0o755)
    monkeypatch.setenv("LUCI_PATH", str(path))


async def test_fixture_luci_script_end_to_end(tmp_path, monkeypatch):
    (tmp_path / "search.json").write_text(json.dumps(SEARCH_FIXTURE))
    _fake_luci(tmp_path, monkeypatch, f'cat "{tmp_path}/search.json"\n')

    async with Client(mcp) as client:
        result = await client.call_tool("search_luci", {"query": "FastMCP"})

    assert result.structured_content["status"] == "ok"
    assert result.structured_content["results"][0]["app"] == "Orca"


async def test_fixture_luci_script_not_running(tmp_path, monkeypatch):
    _fake_luci(
        tmp_path,
        monkeypatch,
        'echo "Luci is not running and could not start" >&2\nexit 2\n',
    )

    async with Client(mcp) as client:
        result = await client.call_tool("get_luci_transcripts", {})

    assert not result.is_error
    assert result.structured_content["status"] == "unavailable"
    assert "could not start" in result.structured_content["warning"]
