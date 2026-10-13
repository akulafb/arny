"""Read-only search over ~/.Life reflections and ~/.fb-mode run artifacts."""

import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

Source = Literal["daily", "meeting", "profile", "run"]

DATE_PREFIX = re.compile(r"^(\d{4}-\d{2}-\d{2})")
RUN_SUFFIXES = {".md", ".tsv"}
SNIPPET_LENGTH = 200


class HistoryEntry(BaseModel):
    source: Source
    path: str
    date: str | None
    title: str
    snippet: str


class HistoryResult(BaseModel):
    status: Literal["ok", "error"]
    results: list[HistoryEntry]
    warnings: list[str] = []


def _split_frontmatter(text: str) -> tuple[dict[str, str], list[str]]:
    """Return flat `key: value` frontmatter pairs and the body lines."""
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, lines
    for end, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            meta = {}
            for raw in lines[1:end]:
                key, sep, value = raw.partition(":")
                if sep and not raw.startswith((" ", "\t", "-")):
                    meta[key.strip()] = value.strip().strip("\"'")
            return meta, lines[end + 1 :]
    return {}, lines


def _parse_date(value: str | None, name: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{name} must be YYYY-MM-DD, got {value!r}") from None


def _iso_or_none(value: str | None) -> str | None:
    try:
        return date.fromisoformat(value).isoformat() if value else None
    except ValueError:
        return None


class HistoryAdapter:
    """Keyword and date-range search over daily reports, meetings, profile and runs."""

    def __init__(self, life_path: Path | None = None, runs_path: Path | None = None):
        self.life_path = Path(life_path or os.environ.get("LIFE_PATH") or Path.home() / ".Life")
        self.runs_path = Path(
            runs_path or os.environ.get("FB_MODE_PATH") or Path.home() / ".fb-mode" / "runs"
        )

    def _candidates(self, warnings: list[str]) -> list[tuple[Source, Path]]:
        found: list[tuple[Source, Path]] = []
        if self.life_path.is_dir():
            found += [("daily", p) for p in sorted((self.life_path / "reflections/daily").glob("*.md"))]
            found += [
                ("meeting", p) for p in sorted((self.life_path / "reflections/meetings").glob("*.md"))
            ]
            if (self.life_path / "profile.md").is_file():
                found.append(("profile", self.life_path / "profile.md"))
        else:
            warnings.append(f"Life directory not found: {self.life_path}")
        if self.runs_path.is_dir():
            found += [
                ("run", p)
                for p in sorted(self.runs_path.rglob("*"))
                if p.is_file() and p.suffix in RUN_SUFFIXES
            ]
        else:
            warnings.append(f"Runs directory not found: {self.runs_path}")
        return found

    def _entry_date(self, source: Source, path: Path, meta: dict[str, str]) -> str | None:
        if source in ("daily", "meeting"):
            match = DATE_PREFIX.match(path.name)
            if match and _iso_or_none(match.group(1)):
                return match.group(1)
            if found := _iso_or_none(meta.get("date")):
                return found
        if source == "profile" and (found := _iso_or_none(meta.get("updated"))):
            return found
        return datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()

    def _title(self, source: Source, path: Path, meta: dict[str, str], body: list[str]) -> str:
        if source == "run":
            return path.relative_to(self.runs_path).as_posix()
        if meta.get("title"):
            return meta["title"]
        heading = next((line[2:].strip() for line in body if line.startswith("# ")), None)
        return heading or path.stem

    def search(
        self,
        query: str = "",
        since: str | None = None,
        until: str | None = None,
        limit: int = 20,
    ) -> HistoryResult:
        try:
            start = _parse_date(since, "since")
            end = _parse_date(until, "until")
        except ValueError as exc:
            return HistoryResult(status="error", results=[], warnings=[str(exc)])

        needle = query.strip().lower()
        warnings: list[str] = []
        entries: list[HistoryEntry] = []
        for source, path in self._candidates(warnings):
            try:
                text = path.read_text(encoding="utf-8")
                meta, body = _split_frontmatter(text)
                when = self._entry_date(source, path, meta)
            except (OSError, UnicodeDecodeError) as exc:
                warnings.append(f"Skipped unreadable file {path}: {exc.__class__.__name__}")
                continue
            if needle and needle not in text.lower():
                continue
            day = date.fromisoformat(when) if when else None
            if day and ((start and day < start) or (end and day > end)):
                continue
            body_lines = [line.strip() for line in body if line.strip()]
            all_lines = [line.strip() for line in text.splitlines() if line.strip()]
            snippet = next(
                (line for line in body_lines + all_lines if needle in line.lower()),
                "",
            )
            entries.append(
                HistoryEntry(
                    source=source,
                    path=str(path),
                    date=when,
                    title=self._title(source, path, meta, body),
                    snippet=snippet[:SNIPPET_LENGTH],
                )
            )

        entries.sort(key=lambda e: (e.date or "", e.path), reverse=True)
        return HistoryResult(status="ok", results=entries[: max(limit, 0)], warnings=warnings)
