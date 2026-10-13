import os
from datetime import datetime

import pytest
from fastmcp import Client

from arny.adapters.history import HistoryAdapter
from arny.server import mcp


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


@pytest.fixture
def life(tmp_path):
    root = tmp_path / "Life"
    write(
        root / "reflections/daily/2026-10-01.md",
        "---\ndate: 2026-10-01\n---\n# 2026-10-01 (Thursday)\n\n## 09:00–10:00 — Wrote the Arny spec\n",
    )
    write(
        root / "reflections/daily/2026-10-05.md",
        "---\ndate: 2026-10-05\n---\n# 2026-10-05 (Monday)\n\n## 11:00–12:00 — Reviewed Osra paper\n",
    )
    write(
        root / "reflections/meetings/2026-10-03-arny-kickoff.md",
        "---\ntitle: Arny kickoff\ndate: 2026-10-03\n---\n# Arny kickoff\n\n## Discussion\nPlanned history search.\n",
    )
    write(
        root / "profile.md",
        "---\nname: FB\nupdated: 2026-10-10\n---\n## Summary\nBuilds Arny and Osra.\n",
    )
    write(root / "reflections/daily/notes.txt", "arny but not markdown\n")
    return root


@pytest.fixture
def runs(tmp_path):
    root = tmp_path / "runs"
    run = root / "arny/lin-171"
    write(run / "lessons.md", "- fastmcp takes instructions=, not description=\n")
    write(run / "standing-orders.md", "1. Never write to ~/.Life.\n")
    write(run / "decisions.tsv", "when\tdecision\n2026-10-13\tuse fastmcp for arny\n")
    write(run / "reports/lin-172.md", "PASS\nScaffolded arny package.\n")
    write(run / "notes/history.md", "# History notes\nDaily reports live in reflections.\n")
    return root


def paths(result):
    return sorted(r.path for r in result.results)


def test_missing_directories_return_ok_with_warnings(tmp_path):
    adapter = HistoryAdapter(life_path=tmp_path / "nope", runs_path=tmp_path / "nada")
    result = adapter.search("arny")
    assert result.status == "ok"
    assert result.results == []
    assert len(result.warnings) == 2


def test_empty_directories_return_ok_without_results(tmp_path):
    (tmp_path / "Life").mkdir()
    (tmp_path / "runs").mkdir()
    result = HistoryAdapter(life_path=tmp_path / "Life", runs_path=tmp_path / "runs").search("arny")
    assert result.status == "ok"
    assert result.results == []


def test_env_vars_override_default_paths(life, runs, monkeypatch):
    monkeypatch.setenv("LIFE_PATH", str(life))
    monkeypatch.setenv("FB_MODE_PATH", str(runs))
    adapter = HistoryAdapter()
    assert adapter.life_path == life
    assert adapter.runs_path == runs


def test_keyword_search_is_case_insensitive_across_sources(life, runs):
    result = HistoryAdapter(life_path=life, runs_path=runs).search("ARNY")
    sources = {r.source for r in result.results}
    assert sources == {"daily", "meeting", "profile", "run"}
    assert not any(p.endswith(".txt") for p in paths(result))


def test_keyword_search_reads_run_notes_reports_and_tsv(life, runs):
    adapter = HistoryAdapter(life_path=life, runs_path=runs)
    assert [r.path for r in adapter.search("reflections").results] == [
        str(runs / "arny/lin-171/notes/history.md")
    ]
    assert [r.path for r in adapter.search("scaffolded").results] == [
        str(runs / "arny/lin-171/reports/lin-172.md")
    ]
    assert [r.path for r in adapter.search("use fastmcp").results] == [
        str(runs / "arny/lin-171/decisions.tsv")
    ]


def test_results_carry_parsed_date_title_and_snippet(life, runs):
    result = HistoryAdapter(life_path=life, runs_path=runs).search("history search")
    [entry] = result.results
    assert entry.source == "meeting"
    assert entry.date == "2026-10-03"
    assert entry.title == "Arny kickoff"
    assert entry.snippet == "Planned history search."


def test_daily_title_comes_from_heading_and_profile_date_from_frontmatter(life, runs):
    adapter = HistoryAdapter(life_path=life, runs_path=runs)
    [daily] = adapter.search("arny spec").results
    assert daily.title == "2026-10-01 (Thursday)"
    assert daily.date == "2026-10-01"
    [profile] = adapter.search("builds arny").results
    assert profile.source == "profile"
    assert profile.date == "2026-10-10"


def test_run_files_use_modification_date(life, runs):
    lessons = runs / "arny/lin-171/lessons.md"
    stamp = datetime(2025, 10, 9, 12).timestamp()
    os.utime(lessons, (stamp, stamp))
    [entry] = HistoryAdapter(life_path=life, runs_path=runs).search("instructions=").results
    assert entry.source == "run"
    assert entry.date == "2025-10-09"
    assert entry.title == "arny/lin-171/lessons.md"


def test_since_and_until_filter_by_date(life, runs):
    adapter = HistoryAdapter(life_path=life, runs_path=runs)
    result = adapter.search("", since="2026-10-02", until="2026-10-05")
    dates = [r.date for r in result.results]
    assert dates == ["2026-10-05", "2026-10-03"]


def test_since_alone_and_until_alone(life, runs):
    adapter = HistoryAdapter(life_path=life, runs_path=runs)
    old = {r.date for r in adapter.search("", until="2026-10-01").results}
    assert old == {"2026-10-01"}
    new = {r.date for r in adapter.search("arny", since="2026-10-10").results}
    assert "2026-10-01" not in new and "2026-10-10" in new


def test_results_are_newest_first_and_limited(life, runs):
    adapter = HistoryAdapter(life_path=life, runs_path=runs)
    result = adapter.search("", until="2026-10-10", limit=2)
    assert [r.date for r in result.results] == ["2026-10-10", "2026-10-05"]


def test_bad_date_returns_error_without_crashing(life, runs):
    result = HistoryAdapter(life_path=life, runs_path=runs).search("arny", since="13/10/2026")
    assert result.status == "error"
    assert result.results == []
    assert "since" in result.warnings[0]


def test_unreadable_file_is_skipped_with_warning(life, runs):
    (life / "reflections/daily/2026-10-02.md").write_bytes(b"\xff\xfe arny \xff")
    result = HistoryAdapter(life_path=life, runs_path=runs).search("arny")
    assert result.status == "ok"
    assert any("2026-10-02.md" in w for w in result.warnings)


async def test_search_agent_history_tool_is_registered():
    async with Client(mcp) as client:
        tools = await client.list_tools()
    assert "search_agent_history" in {t.name for t in tools}


async def test_search_agent_history_tool_returns_structured_results(life, runs, monkeypatch):
    monkeypatch.setenv("LIFE_PATH", str(life))
    monkeypatch.setenv("FB_MODE_PATH", str(runs))
    async with Client(mcp) as client:
        result = await client.call_tool(
            "search_agent_history",
            {"query": "kickoff", "since": "2026-10-01", "until": "2026-10-31"},
        )
    assert not result.is_error
    content = result.structured_content
    assert content["status"] == "ok"
    assert [r["path"] for r in content["results"]] == [
        str(life / "reflections/meetings/2026-10-03-arny-kickoff.md")
    ]


async def test_search_agent_history_tool_degrades_when_paths_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_PATH", str(tmp_path / "missing-life"))
    monkeypatch.setenv("FB_MODE_PATH", str(tmp_path / "missing-runs"))
    async with Client(mcp) as client:
        result = await client.call_tool("search_agent_history", {"query": "arny"})
    assert not result.is_error
    assert result.structured_content["status"] == "ok"
    assert result.structured_content["results"] == []
