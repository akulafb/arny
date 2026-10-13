"""Answer a natural-language question from Luci, Granola and History.

`gather` queries the three adapters in parallel and turns their results into
`Excerpt`s. `answer` asks an LLM for a short cited answer when an API key is
set (GEMINI_API_KEY, ANTHROPIC_API_KEY or OPENAI_API_KEY), and otherwise, or
when the LLM call fails, returns the excerpts ranked and grouped by source.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

SourceName = Literal["Luci", "Granola", "History"]
SOURCE_ORDER: tuple[SourceName, ...] = ("Luci", "Granola", "History")

Provider = Literal["openrouter", "gemini", "anthropic", "openai"]
PROVIDER_KEYS: dict[Provider, str] = {
    "openrouter": "OPENROUTER_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}
DEFAULT_MODELS: dict[Provider, str] = {
    "openrouter": "anthropic/claude-3.5-sonnet",
    "gemini": "gemini-2.5-flash",
    "anthropic": "claude-sonnet-5-5",
    "openai": "gpt-5-mini",
}
LLM_TIMEOUT_S = 60
EXCERPT_CHARS = 300
PER_SOURCE_LIMIT = 10
MAX_EXCERPTS = 20
MAX_HISTORY_KEYWORDS = 5

STOPWORDS = frozenset(
    """a about after all also am an and any are as at be been before but by can could
    did do does doing for from get got had has have how i if in into is it its just
    last me my of on or our out over so some than that the their them then there these
    they this those to up us was we were what when where which who why will with
    would you your yesterday today week month day ago recently lately""".split()  # noqa: SIM905
)

Post = Callable[[str, dict[str, str], dict], Any]
Caller = Callable[[Provider, str, Mapping[str, str]], str]


class Excerpt(BaseModel):
    source: SourceName
    title: str
    text: str = ""
    date: str | None = None
    ref: str | None = None


class Gathered(BaseModel):
    excerpts: list[Excerpt] = []
    warnings: list[str] = []


class Answer(BaseModel):
    text: str
    provider: Provider | None = None
    excerpts: list[Excerpt] = []
    warnings: list[str] = []


def keywords(question: str) -> list[str]:
    seen: list[str] = []
    for word in re.findall(r"[a-z0-9][a-z0-9_-]*", question.lower()):
        if len(word) >= 3 and word not in STOPWORDS and word not in seen:
            seen.append(word)
    return seen


def _hits(words: list[str], excerpt: Excerpt) -> int:
    haystack = f"{excerpt.title} {excerpt.text}".lower()
    return sum(1 for w in words if w in haystack)


def rank(question: str, excerpts: list[Excerpt]) -> list[Excerpt]:
    """Most keyword hits first; ties keep source order, then newest first."""
    words = keywords(question)
    by_date = sorted(excerpts, key=lambda e: e.date or "", reverse=True)
    return sorted(by_date, key=lambda e: (-_hits(words, e), SOURCE_ORDER.index(e.source)))


def _luci(question: str, adapter: Any) -> tuple[list[Excerpt], list[str]]:
    res = adapter.search(question, limit=PER_SOURCE_LIMIT)
    if res.status != "ok":
        return [], [res.warning or "unavailable"]
    out: list[Excerpt] = []
    seen: set[str] = set()
    for c in res.results:
        key = " ".join(c.text.split())
        if key in seen:
            continue
        seen.add(key)
        when = datetime.fromtimestamp(c.timestamp / 1000).isoformat(timespec="minutes")
        title = " — ".join(p for p in (c.app, c.window_title) if p) or "Screen capture"
        out.append(Excerpt(source="Luci", title=title, text=c.text, date=when, ref=c.browser_url))
    return out, []


def _granola(question: str, adapter: Any) -> tuple[list[Excerpt], list[str]]:
    res = adapter.get_meetings(limit=50)
    if res.status != "ok":
        return [], [res.warning or "unavailable"]
    words = keywords(question)
    out = [
        Excerpt(source="Granola", title=m.title, date=m.date, ref=m.id)
        for m in res.meetings
        if any(w in m.title.lower() for w in words)
    ]
    return out[:PER_SOURCE_LIMIT], [res.warning] if res.warning else []


def _history(question: str, adapter: Any) -> tuple[list[Excerpt], list[str]]:
    seen: dict[str, Excerpt] = {}
    warnings: list[str] = []
    for word in keywords(question)[:MAX_HISTORY_KEYWORDS]:
        res = adapter.search(word, limit=PER_SOURCE_LIMIT)
        warnings += [w for w in res.warnings if w not in warnings]
        for e in res.results:
            seen.setdefault(e.path, Excerpt(source="History", title=e.title, text=e.snippet, date=e.date, ref=e.path))
    return list(seen.values()), warnings


def gather(question: str, *, luci: Any, granola: Any, history: Any) -> Gathered:
    """Query all three adapters in parallel. A failing adapter becomes a warning."""
    jobs = {"Luci": (_luci, luci), "Granola": (_granola, granola), "History": (_history, history)}
    excerpts: list[Excerpt] = []
    warnings: list[str] = []
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {name: pool.submit(fn, question, adapter) for name, (fn, adapter) in jobs.items()}
        for name, future in futures.items():
            try:
                found, warns = future.result()
            except Exception as exc:  # noqa: BLE001
                found, warns = [], [f"{exc.__class__.__name__}: {exc}"]
            excerpts += found
            warnings += [f"{name}: {w}" for w in warns]
    return Gathered(excerpts=rank(question, excerpts)[:MAX_EXCERPTS], warnings=warnings)


def format_excerpts(excerpts: list[Excerpt]) -> str:
    if not excerpts:
        return "No matching excerpts found in Luci, Granola or History."
    blocks = []
    for source in sorted({e.source for e in excerpts}, key=SOURCE_ORDER.index):
        lines = [f"## {source}"]
        for e in (e for e in excerpts if e.source == source):
            head = f"- {e.title}" + (f" ({e.date})" if e.date else "")
            lines.append(head)
            if e.text:
                lines.append(f"  {' '.join(e.text.split())[:EXCERPT_CHARS]}")
            if e.ref and source != "Granola":
                lines.append(f"  {e.ref}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def pick_provider(env: Mapping[str, str]) -> Provider | None:
    forced = env.get("ARNY_LLM_PROVIDER", "").lower()
    order = sorted(PROVIDER_KEYS, key=lambda p: p != forced)
    return next((p for p in order if env.get(PROVIDER_KEYS[p])), None)


def build_prompt(question: str, excerpts: list[Excerpt]) -> str:
    sources = "\n".join(
        f"[{e.source}] {e.title}" + (f" ({e.date})" if e.date else "") + (f": {e.text[:EXCERPT_CHARS]}" if e.text else "")
        for e in excerpts
    )
    return (
        "Answer the user's question about their own activity using only the excerpts below.\n"
        "Be concise. Cite each fact with its source tag: [Luci], [Granola] or [History].\n"
        "If the excerpts do not answer the question, say so.\n\n"
        f"Question: {question}\n\nExcerpts:\n{sources or '(none)'}"
    )


def _default_post(url: str, headers: dict[str, str], body: dict) -> Any:
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(), headers={"content-type": "application/json", **headers}
    )
    with urllib.request.urlopen(req, timeout=LLM_TIMEOUT_S) as resp:
        return json.load(resp)


def call_llm(provider: Provider, prompt: str, env: Mapping[str, str], post: Post = _default_post) -> str:
    key = env[PROVIDER_KEYS[provider]]
    model = env.get("ARNY_LLM_MODEL") or DEFAULT_MODELS[provider]
    if provider == "anthropic":
        data = post(
            "https://api.anthropic.com/v1/messages",
            {"x-api-key": key, "anthropic-version": "2023-06-01"},
            {"model": model, "max_tokens": 1024, "messages": [{"role": "user", "content": prompt}]},
        )
        return "".join(b.get("text", "") for b in data["content"] if b.get("type") == "text").strip()
    if provider == "openrouter":
        data = post(
            "https://openrouter.ai/api/v1/chat/completions",
            {"Authorization": f"Bearer {key}", "HTTP-Referer": "https://github.com/akulafb/arny"},
            {"model": model, "messages": [{"role": "user", "content": prompt}]},
        )
        return data["choices"][0]["message"]["content"].strip()
    if provider == "openai":
        data = post(
            "https://api.openai.com/v1/chat/completions",
            {"Authorization": f"Bearer {key}"},
            {"model": model, "messages": [{"role": "user", "content": prompt}]},
        )
        return data["choices"][0]["message"]["content"].strip()
    data = post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        {"x-goog-api-key": key},
        {"contents": [{"parts": [{"text": prompt}]}]},
    )
    return "".join(p.get("text", "") for p in data["candidates"][0]["content"]["parts"]).strip()


def answer(
    question: str,
    excerpts: list[Excerpt],
    env: Mapping[str, str] | None = None,
    caller: Caller = call_llm,
) -> Answer:
    env = os.environ if env is None else env
    provider = pick_provider(env)
    if provider and excerpts:
        try:
            text = caller(provider, build_prompt(question, excerpts), env)
            if text:
                return Answer(text=text, provider=provider, excerpts=excerpts)
            warning = f"{provider}: empty answer"
        except Exception as exc:  # noqa: BLE001
            warning = f"{provider}: {exc.__class__.__name__}: {exc}"
        return Answer(text=format_excerpts(excerpts), excerpts=excerpts, warnings=[warning])
    return Answer(text=format_excerpts(excerpts), excerpts=excerpts)
