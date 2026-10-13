import json
import subprocess

import pytest
from fastmcp import Client

from arny.adapters.granola import GranolaAdapter
from arny.server import mcp

APP_NOT_RUNNING = json.dumps(
    {"error": {"code": "APP_NOT_RUNNING", "message": "Granola does not appear to be running"}}
)


class FakeRunner:
    """Stands in for subprocess.run; records argv and replays one result."""

    def __init__(self, stdout="", stderr="", returncode=0, exc=None):
        self.stdout, self.stderr, self.returncode, self.exc = stdout, stderr, returncode, exc
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append(argv)
        if self.exc:
            raise self.exc
        return subprocess.CompletedProcess(argv, self.returncode, self.stdout, self.stderr)


@pytest.fixture
def cli(tmp_path):
    path = tmp_path / "granola"
    path.write_text("#!/bin/sh\n")
    return str(path)


@pytest.fixture
def export_dir(tmp_path):
    d = tmp_path / "export"
    d.mkdir()
    (d / "granola.csv").write_text(
        "Title,Date,Summary,Transcript\n"
        "Weekly sync,2026-10-01,Talked roadmap,Me: hi\n",
        encoding="utf-8",
    )
    (d / "2026-10-02_Design review.md").write_text(
        "---\ntitle: Design review\ndate: 2026-10-02\n---\n\n"
        "## Summary\nGood review.\n\n## Transcript\nThem: looks fine\nMe: thanks\n",
        encoding="utf-8",
    )
    (d / "2026-10-03_standup.md").write_text("# Standup\n\nShort.\n", encoding="utf-8")
    return d




def test_meetings_from_cli(cli):
    runner = FakeRunner(
        stdout=json.dumps(
            {
                "notes": [
                    {"id": "n1", "title": "Kickoff", "created_at": "2026-10-01T09:00:00Z"},
                    {"id": "n2", "title": "Retro", "created_at": "2026-10-02T09:00:00Z"},
                ],
                "has_more": False,
                "next_offset": 0,
            }
        )
    )
    result = GranolaAdapter(cli_path=cli, runner=runner).get_meetings(limit=5)

    assert runner.calls == [[cli, "notes", "list", "--limit", "5"]]
    assert result.status == "ok"
    assert result.source == "cli"
    assert [(m.id, m.title, m.date) for m in result.meetings] == [
        ("n1", "Kickoff", "2026-10-01T09:00:00Z"),
        ("n2", "Retro", "2026-10-02T09:00:00Z"),
    ]


def test_transcript_from_cli(cli):
    runner = FakeRunner(
        stdout=json.dumps(
            {
                "note": {"id": "n1", "title": "Kickoff"},
                "transcript": [
                    {"speaker": "me", "text": "Hello"},
                    {"speaker": "them", "text": "Hi"},
                ],
            }
        )
    )
    result = GranolaAdapter(cli_path=cli, runner=runner).get_transcript("n1")

    assert runner.calls == [[cli, "notes", "transcript", "get", "--id", "n1"]]
    assert result.status == "ok"
    assert result.source == "cli"
    assert result.title == "Kickoff"
    assert result.transcript == "me: Hello\nthem: Hi"


def test_cli_app_not_running_falls_back_to_export(cli, export_dir):
    runner = FakeRunner(stderr=APP_NOT_RUNNING, returncode=1)
    result = GranolaAdapter(cli_path=cli, export_dir=str(export_dir), runner=runner).get_meetings()

    assert result.status == "ok"
    assert result.source == "export"
    assert "APP_NOT_RUNNING" in result.warning


def test_cli_plain_text_error_and_crash_are_unavailable(cli):
    for runner in (
        FakeRunner(stderr="socket not configured", returncode=2),
        FakeRunner(exc=OSError("exec format error")),
        FakeRunner(stdout="not json"),
    ):
        result = GranolaAdapter(cli_path=cli, runner=runner).get_meetings()
        assert result.status == "unavailable"
        assert result.meetings == []
        assert result.warning


def test_missing_cli_is_not_run(tmp_path):
    runner = FakeRunner()
    result = GranolaAdapter(cli_path=str(tmp_path / "nope"), runner=runner).get_meetings()

    assert runner.calls == []
    assert result.status == "unavailable"




def test_meetings_from_export_dir(tmp_path, export_dir):
    result = GranolaAdapter(cli_path=str(tmp_path / "nope"), export_dir=str(export_dir)).get_meetings()

    assert result.status == "ok"
    assert result.source == "export"
    assert [(m.title, m.date) for m in result.meetings] == [
        ("Standup", "2026-10-03"),
        ("Design review", "2026-10-02"),
        ("Weekly sync", "2026-10-01"),
    ]


def test_export_meetings_respect_limit(tmp_path, export_dir):
    result = GranolaAdapter(cli_path=str(tmp_path / "nope"), export_dir=str(export_dir)).get_meetings(
        limit=1
    )
    assert [m.title for m in result.meetings] == ["Standup"]


def test_transcript_from_export_markdown_and_csv(tmp_path, export_dir):
    adapter = GranolaAdapter(cli_path=str(tmp_path / "nope"), export_dir=str(export_dir))
    ids = {m.title: m.id for m in adapter.get_meetings().meetings}

    md = adapter.get_transcript(ids["Design review"])
    assert md.status == "ok"
    assert md.transcript == "Them: looks fine\nMe: thanks"

    csv_row = adapter.get_transcript(ids["Weekly sync"])
    assert csv_row.status == "ok"
    assert csv_row.transcript == "Me: hi"


def test_unknown_transcript_id_is_not_found(tmp_path, export_dir):
    adapter = GranolaAdapter(cli_path=str(tmp_path / "nope"), export_dir=str(export_dir))
    result = adapter.get_transcript("missing")
    assert result.status == "not_found"
    assert result.transcript == ""




def test_token_uses_public_api_with_bearer_header(tmp_path):
    seen = []

    def fetch(url, headers):
        seen.append((url, headers))
        return {"notes": [{"id": "a1", "title": "API note", "created_at": "2026-10-05T10:00:00Z"}]}

    result = GranolaAdapter(cli_path=str(tmp_path / "nope"), token="sekret", fetch=fetch).get_meetings()

    assert result.status == "ok"
    assert result.source == "api"
    assert [m.id for m in result.meetings] == ["a1"]
    assert seen[0][1]["Authorization"] == "Bearer sekret"
    assert seen[0][0].startswith("https://public-api.granola.ai/v1/notes")


def test_api_failure_falls_through_to_unavailable(tmp_path):
    def fetch(url, headers):
        raise OSError("network down")

    result = GranolaAdapter(cli_path=str(tmp_path / "nope"), token="t", fetch=fetch).get_meetings()
    assert result.status == "unavailable"
    assert "network down" in result.warning




def test_nothing_available_returns_structured_unavailable(tmp_path):
    result = GranolaAdapter(
        cli_path=str(tmp_path / "nope"), export_dir=str(tmp_path / "missing")
    ).get_meetings()
    assert result.model_dump() == {
        "status": "unavailable",
        "source": None,
        "warning": result.warning,
        "meetings": [],
    }
    assert result.warning


def test_from_env_reads_variables(monkeypatch, tmp_path):
    monkeypatch.setenv("GRANOLA_CLI_PATH", "/x/granola")
    monkeypatch.setenv("ARNY_GRANOLA_EXPORT_DIR", str(tmp_path))
    monkeypatch.setenv("ARNY_GRANOLA_TOKEN", "tok")
    adapter = GranolaAdapter.from_env()
    assert (adapter.cli_path, adapter.export_dir, adapter.token) == ("/x/granola", str(tmp_path), "tok")


def test_from_env_defaults_to_bundled_cli(monkeypatch):
    for var in ("GRANOLA_CLI_PATH", "ARNY_GRANOLA_EXPORT_DIR", "ARNY_GRANOLA_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    adapter = GranolaAdapter.from_env()
    assert adapter.cli_path == "/Applications/Granola.app/Contents/Resources/bin/granola"
    assert adapter.export_dir is None
    assert adapter.token is None




@pytest.fixture
def export_env(monkeypatch, tmp_path, export_dir):
    monkeypatch.setenv("GRANOLA_CLI_PATH", str(tmp_path / "nope"))
    monkeypatch.setenv("ARNY_GRANOLA_EXPORT_DIR", str(export_dir))
    monkeypatch.delenv("ARNY_GRANOLA_TOKEN", raising=False)


async def test_tools_are_registered():
    async with Client(mcp) as client:
        names = {t.name for t in await client.list_tools()}
    assert {"get_granola_meetings", "get_granola_transcript"} <= names


async def test_get_granola_meetings_tool(export_env):
    async with Client(mcp) as client:
        result = await client.call_tool("get_granola_meetings", {"limit": 2})
    assert not result.is_error
    content = result.structured_content
    assert content["status"] == "ok"
    assert [m["title"] for m in content["meetings"]] == ["Standup", "Design review"]


async def test_get_granola_transcript_tool(export_env):
    async with Client(mcp) as client:
        meetings = await client.call_tool("get_granola_meetings", {})
        md_id = next(
            m["id"] for m in meetings.structured_content["meetings"] if m["title"] == "Design review"
        )
        result = await client.call_tool("get_granola_transcript", {"meeting_id": md_id})
    assert not result.is_error
    assert result.structured_content["transcript"] == "Them: looks fine\nMe: thanks"


async def test_tools_degrade_when_granola_unreachable(monkeypatch, tmp_path):
    monkeypatch.setenv("GRANOLA_CLI_PATH", str(tmp_path / "nope"))
    monkeypatch.delenv("ARNY_GRANOLA_EXPORT_DIR", raising=False)
    monkeypatch.delenv("ARNY_GRANOLA_TOKEN", raising=False)
    async with Client(mcp) as client:
        meetings = await client.call_tool("get_granola_meetings", {})
        transcript = await client.call_tool("get_granola_transcript", {"meeting_id": "x"})
    assert not meetings.is_error and not transcript.is_error
    assert meetings.structured_content["status"] == "unavailable"
    assert meetings.structured_content["meetings"] == []
    assert transcript.structured_content["status"] == "unavailable"
