from arny.adapters.granola import GranolaMeeting, GranolaMeetingsResult
from arny.adapters.history import HistoryEntry, HistoryResult
from arny.adapters.luci import LuciSearchResponse, ScreenCapture
from arny.synthesizer import (
    Excerpt,
    answer,
    format_excerpts,
    gather,
    keywords,
    pick_provider,
    rank,
)


class FakeLuci:
    def __init__(self, response):
        self.response = response
        self.queries = []

    def search(self, query, limit=20, **_):
        self.queries.append(query)
        return self.response


class FakeGranola:
    def __init__(self, response):
        self.response = response

    def get_meetings(self, limit=20):
        return self.response


class FakeHistory:
    def __init__(self, entries):
        self.entries = entries
        self.queries = []

    def search(self, query="", limit=20, **_):
        self.queries.append(query)
        hits = [e for e in self.entries if query in (e.title + e.snippet).lower()]
        return HistoryResult(status="ok", results=hits)


def capture(text, score=0.9, ts=1_760_000_000_000):
    return ScreenCapture.model_validate(
        {"captureId": 1, "timestamp": ts, "app": "Code", "windowTitle": "arny", "text": text, "score": score}
    )


def entry(title, snippet, path="/x.md", date="2026-10-12"):
    return HistoryEntry(source="daily", path=path, date=date, title=title, snippet=snippet)


def ex(source, title, text, date=None):
    return Excerpt(source=source, title=title, text=text, date=date)


def test_keywords_drop_stopwords_and_short_words():
    assert keywords("What did I do on the Arny MCP server?") == ["arny", "mcp", "server"]


def test_rank_puts_most_keyword_hits_first():
    ranked = rank(
        "arny server",
        [ex("History", "lunch", "ate food"), ex("Luci", "arny", "the arny server ran"), ex("Granola", "arny sync", "")],
    )
    assert [e.title for e in ranked] == ["arny", "arny sync", "lunch"]


def test_gather_collects_excerpts_from_all_three_sources():
    luci = FakeLuci(LuciSearchResponse(status="ok", results=[capture("worked on arny server")]))
    granola = FakeGranola(
        GranolaMeetingsResult(
            status="ok",
            source="cli",
            meetings=[
                GranolaMeeting(id="m1", title="Arny planning", date="2026-10-11", source="cli"),
                GranolaMeeting(id="m2", title="Dentist", date="2026-10-10", source="cli"),
            ],
        )
    )
    history = FakeHistory([entry("Daily 2026-10-12", "Shipped arny adapters")])

    result = gather("what about arny?", luci=luci, granola=granola, history=history)

    sources = {e.source for e in result.excerpts}
    assert sources == {"Luci", "Granola", "History"}
    assert [e.title for e in result.excerpts if e.source == "Granola"] == ["Arny planning"]
    assert luci.queries == ["what about arny?"]
    assert "arny" in history.queries
    assert result.warnings == []


def test_gather_reports_unavailable_sources_as_warnings():
    luci = FakeLuci(LuciSearchResponse(status="unavailable", warning="Luci CLI not found."))
    granola = FakeGranola(GranolaMeetingsResult(status="unavailable", warning="no Granola source"))
    history = FakeHistory([])

    result = gather("anything", luci=luci, granola=granola, history=history)

    assert result.excerpts == []
    assert "Luci: Luci CLI not found." in result.warnings
    assert "Granola: no Granola source" in result.warnings


def test_gather_survives_an_adapter_that_raises():
    class Boom:
        def search(self, *a, **k):
            raise RuntimeError("kaboom")

    result = gather(
        "arny",
        luci=Boom(),
        granola=FakeGranola(GranolaMeetingsResult(status="ok", meetings=[])),
        history=FakeHistory([entry("Daily", "arny notes")]),
    )
    assert [e.source for e in result.excerpts] == ["History"]
    assert any(w.startswith("Luci:") and "kaboom" in w for w in result.warnings)


def test_format_excerpts_groups_by_source():
    out = format_excerpts([ex("Luci", "Code — arny", "server work", "2026-10-12"), ex("History", "Daily", "notes")])
    assert "## Luci" in out and "## History" in out
    assert out.index("## Luci") < out.index("## History")
    assert "server work" in out


def test_format_excerpts_with_nothing_found():
    assert "No matching excerpts" in format_excerpts([])


def test_pick_provider_follows_env_order():
    assert pick_provider({}) is None
    assert pick_provider({"OPENAI_API_KEY": "o"}) == "openai"
    assert pick_provider({"OPENAI_API_KEY": "o", "ANTHROPIC_API_KEY": "a"}) == "anthropic"
    assert pick_provider({"OPENAI_API_KEY": "o", "GEMINI_API_KEY": "g", "ANTHROPIC_API_KEY": "a"}) == "gemini"
    assert pick_provider({"GEMINI_API_KEY": "g", "ARNY_LLM_PROVIDER": "openai", "OPENAI_API_KEY": "o"}) == "openai"


def test_answer_without_key_returns_ranked_excerpts():
    result = answer("arny", [ex("History", "Daily", "arny notes")], env={})
    assert result.provider is None
    assert "## History" in result.text


def test_answer_with_key_calls_llm_with_sourced_prompt():
    calls = []

    def caller(provider, prompt, env):
        calls.append((provider, prompt))
        return "You worked on Arny [Luci]."

    result = answer(
        "what did I do?",
        [ex("Luci", "Code", "arny server")],
        env={"ANTHROPIC_API_KEY": "k"},
        caller=caller,
    )
    assert result.provider == "anthropic"
    assert result.text == "You worked on Arny [Luci]."
    provider, prompt = calls[0]
    assert provider == "anthropic"
    assert "what did I do?" in prompt and "[Luci]" in prompt and "arny server" in prompt


def test_answer_falls_back_to_excerpts_when_llm_fails():
    def caller(provider, prompt, env):
        raise OSError("network down")

    result = answer("arny", [ex("History", "Daily", "arny notes")], env={"OPENAI_API_KEY": "k"}, caller=caller)
    assert result.provider is None
    assert "## History" in result.text
    assert any("openai" in w and "network down" in w for w in result.warnings)


def test_default_caller_builds_provider_requests():
    from arny import synthesizer

    seen = []

    def fake_post(url, headers, body):
        seen.append((url, headers, body))
        if "anthropic" in url:
            return {"content": [{"type": "text", "text": "A"}]}
        if "openai" in url:
            return {"choices": [{"message": {"content": "O"}}]}
        return {"candidates": [{"content": {"parts": [{"text": "G"}]}}]}

    env = {"ANTHROPIC_API_KEY": "a", "OPENAI_API_KEY": "o", "GEMINI_API_KEY": "g"}
    assert synthesizer.call_llm("anthropic", "p", env, post=fake_post) == "A"
    assert synthesizer.call_llm("openai", "p", env, post=fake_post) == "O"
    assert synthesizer.call_llm("gemini", "p", env, post=fake_post) == "G"
    assert seen[0][1]["x-api-key"] == "a"
    assert seen[1][1]["Authorization"] == "Bearer o"
    assert seen[2][1]["x-goog-api-key"] == "g"


def test_gather_drops_duplicate_luci_text():
    luci = FakeLuci(LuciSearchResponse(status="ok", results=[capture("same arny text"), capture("same  arny text")]))
    result = gather(
        "arny",
        luci=luci,
        granola=FakeGranola(GranolaMeetingsResult(status="ok", meetings=[])),
        history=FakeHistory([]),
    )
    assert len(result.excerpts) == 1
