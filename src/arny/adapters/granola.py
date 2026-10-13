"""Read-only Granola adapter.

Sources, tried in order until one answers:
1. Granola's bundled Companion CLI (talks to the running desktop app).
2. The public API, when `ARNY_GRANOLA_TOKEN` is set.
3. An export folder (`ARNY_GRANOLA_EXPORT_DIR`) of CSV / Markdown files.

When no source answers, results carry `status="unavailable"` and a warning
instead of raising.
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

DEFAULT_CLI_PATH = "/Applications/Granola.app/Contents/Resources/bin/granola"
API_BASE = "https://public-api.granola.ai/v1"
CLI_TIMEOUT_S = 15
API_TIMEOUT_S = 15

Source = Literal["cli", "api", "export"]
Runner = Callable[..., subprocess.CompletedProcess]
Fetch = Callable[[str, dict[str, str]], Any]


class GranolaMeeting(BaseModel):
    id: str
    title: str
    date: str | None = None
    source: Source


class GranolaMeetingsResult(BaseModel):
    status: Literal["ok", "unavailable"]
    source: Source | None = None
    warning: str | None = None
    meetings: list[GranolaMeeting] = []


class GranolaTranscriptResult(BaseModel):
    status: Literal["ok", "not_found", "unavailable"]
    source: Source | None = None
    warning: str | None = None
    meeting_id: str
    title: str | None = None
    transcript: str = ""


class SourceError(Exception):
    """A source could not answer; the message becomes a warning."""


@dataclass
class _ExportNote:
    meeting: GranolaMeeting
    transcript: str


def _default_fetch(url: str, headers: dict[str, str]) -> Any:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=API_TIMEOUT_S) as resp:
        return json.load(resp)


def _note_date(note: dict) -> str | None:
    for key in ("created_at", "date", "start_time", "updated_at"):
        if note.get(key):
            return str(note[key])
    return None


def _note_title(note: dict) -> str:
    return str(note.get("title") or note.get("name") or "Untitled")


def _chunks_to_text(chunks: Any) -> str:
    if isinstance(chunks, str):
        return chunks.strip()
    lines = []
    for chunk in chunks or []:
        if isinstance(chunk, str):
            lines.append(chunk)
            continue
        text = str(chunk.get("text") or "").strip()
        speaker = chunk.get("speaker") or chunk.get("source")
        if isinstance(speaker, dict):
            speaker = speaker.get("name") or speaker.get("source")
        lines.append(f"{speaker}: {text}" if speaker else text)
    return "\n".join(lines)


def _transcript_payload(data: Any) -> tuple[str | None, str]:
    """Pull (title, transcript text) out of a tolerant CLI/API response."""
    if isinstance(data, list):
        return None, _chunks_to_text(data)
    note = data.get("note") or {}
    chunks = data.get("transcript", data.get("chunks", note.get("transcript")))
    title = note.get("title") or data.get("title")
    return title, _chunks_to_text(chunks)


class GranolaAdapter:
    def __init__(
        self,
        cli_path: str | None = DEFAULT_CLI_PATH,
        export_dir: str | None = None,
        token: str | None = None,
        runner: Runner = subprocess.run,
        fetch: Fetch = _default_fetch,
    ):
        self.cli_path = cli_path
        self.export_dir = export_dir
        self.token = token
        self._runner = runner
        self._fetch = fetch

    @classmethod
    def from_env(cls) -> GranolaAdapter:
        return cls(
            cli_path=os.environ.get("GRANOLA_CLI_PATH") or DEFAULT_CLI_PATH,
            export_dir=os.environ.get("ARNY_GRANOLA_EXPORT_DIR") or None,
            token=os.environ.get("ARNY_GRANOLA_TOKEN") or None,
        )


    def get_meetings(self, limit: int = 20) -> GranolaMeetingsResult:
        warnings: list[str] = []
        for source, fn in self._sources(self._cli_meetings, self._api_meetings, self._export_meetings):
            try:
                meetings = fn(limit)
            except SourceError as e:
                warnings.append(f"{source}: {e}")
                continue
            return GranolaMeetingsResult(
                status="ok", source=source, warning="; ".join(warnings) or None, meetings=meetings
            )
        return GranolaMeetingsResult(status="unavailable", warning=self._unavailable(warnings))

    def get_transcript(self, meeting_id: str) -> GranolaTranscriptResult:
        warnings: list[str] = []
        for source, fn in self._sources(
            self._cli_transcript, self._api_transcript, self._export_transcript
        ):
            try:
                found = fn(meeting_id)
            except SourceError as e:
                warnings.append(f"{source}: {e}")
                continue
            warning = "; ".join(warnings) or None
            if found is None:
                return GranolaTranscriptResult(
                    status="not_found", source=source, warning=warning, meeting_id=meeting_id
                )
            title, text = found
            return GranolaTranscriptResult(
                status="ok", source=source, warning=warning, meeting_id=meeting_id,
                title=title, transcript=text,
            )
        return GranolaTranscriptResult(
            status="unavailable", warning=self._unavailable(warnings), meeting_id=meeting_id
        )


    def _sources(self, cli, api, export):
        if self.cli_path and Path(self.cli_path).is_file():
            yield "cli", cli
        if self.token:
            yield "api", api
        if self.export_dir and Path(self.export_dir).is_dir():
            yield "export", export

    def _unavailable(self, warnings: list[str]) -> str:
        reasons = "; ".join(warnings) if warnings else "no source configured"
        return (
            f"Granola is unavailable ({reasons}). Start the Granola app, set "
            "ARNY_GRANOLA_TOKEN, or point ARNY_GRANOLA_EXPORT_DIR at an export folder."
        )


    def _run_cli(self, *args: str) -> Any:
        try:
            proc = self._runner(
                [self.cli_path, *args], capture_output=True, text=True, timeout=CLI_TIMEOUT_S
            )
        except (OSError, subprocess.SubprocessError) as e:
            raise SourceError(f"could not run Granola CLI: {e}") from e
        if proc.returncode != 0:
            raise SourceError(self._cli_error(proc.stderr) or f"Granola CLI exited {proc.returncode}")
        try:
            return json.loads(proc.stdout)
        except ValueError as e:
            raise SourceError("Granola CLI returned invalid JSON") from e

    @staticmethod
    def _cli_error(stderr: str) -> str:
        stderr = (stderr or "").strip()
        try:
            err = json.loads(stderr)["error"]
            return f"{err.get('code', 'ERROR')}: {err.get('message', '')}".strip()
        except (ValueError, KeyError, TypeError, AttributeError):
            return stderr

    def _cli_meetings(self, limit: int) -> list[GranolaMeeting]:
        data = self._run_cli("notes", "list", "--limit", str(limit))
        return [
            GranolaMeeting(id=str(n.get("id")), title=_note_title(n), date=_note_date(n), source="cli")
            for n in data.get("notes", [])
        ]

    def _cli_transcript(self, meeting_id: str) -> tuple[str | None, str]:
        return _transcript_payload(self._run_cli("notes", "transcript", "get", "--id", meeting_id))


    def _api_get(self, path: str, **params: Any) -> Any:
        url = f"{API_BASE}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        try:
            return self._fetch(url, {"Authorization": f"Bearer {self.token}"})
        except Exception as e:
            raise SourceError(f"Granola API request failed: {e}") from e

    def _api_meetings(self, limit: int) -> list[GranolaMeeting]:
        data = self._api_get("/notes", page_size=limit)
        notes = data.get("notes", data.get("data", [])) if isinstance(data, dict) else data
        return [
            GranolaMeeting(id=str(n.get("id")), title=_note_title(n), date=_note_date(n), source="api")
            for n in notes[:limit]
        ]

    def _api_transcript(self, meeting_id: str) -> tuple[str | None, str]:
        path = f"/notes/{urllib.parse.quote(meeting_id, safe='')}/transcript"
        return _transcript_payload(self._api_get(path))


    def _export_notes(self) -> list[_ExportNote]:
        root = Path(self.export_dir)
        notes: list[_ExportNote] = []
        try:
            for path in sorted(root.iterdir()):
                if path.suffix.lower() == ".csv":
                    notes.extend(self._read_csv(path))
                elif path.suffix.lower() in (".md", ".markdown"):
                    notes.append(self._read_markdown(path))
        except (OSError, UnicodeDecodeError, csv.Error) as e:
            raise SourceError(f"could not read export folder: {e}") from e
        notes.sort(key=lambda n: n.meeting.date or "", reverse=True)
        return notes

    def _read_csv(self, path: Path) -> list[_ExportNote]:
        notes = []
        with path.open(newline="", encoding="utf-8-sig") as f:
            for i, row in enumerate(csv.DictReader(f), start=1):
                row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
                meeting = GranolaMeeting(
                    id=row.get("id") or f"csv:{path.stem}:{i}",
                    title=row.get("title") or "Untitled",
                    date=row.get("date") or row.get("created_at") or None,
                    source="export",
                )
                notes.append(_ExportNote(meeting, row.get("transcript", "")))
        return notes

    def _read_markdown(self, path: Path) -> _ExportNote:
        text = path.read_text(encoding="utf-8")
        meta: dict[str, str] = {}
        if text.startswith("---\n"):
            head, sep, body = text[4:].partition("\n---")
            if sep:
                text = body.lstrip("-\n")
                for line in head.splitlines():
                    key, colon, value = line.partition(":")
                    if colon:
                        meta[key.strip().lower()] = value.strip().strip("\"'")
        heading = re.search(r"^# (.+)$", text, re.MULTILINE)
        file_date = re.match(r"(\d{4}-\d{2}-\d{2})", path.stem)
        title = meta.get("title") or (heading.group(1).strip() if heading else None)
        if not title:
            title = path.stem
        date = meta.get("date") or (file_date.group(1) if file_date else None)
        if not date:
            date = datetime.fromtimestamp(path.stat().st_mtime).date().isoformat()
        section = re.search(r"^##+ Transcript\s*$(.*?)(?=^##? |\Z)", text, re.MULTILINE | re.DOTALL | re.IGNORECASE)
        transcript = section.group(1).strip() if section else ""
        return _ExportNote(
            GranolaMeeting(id=f"md:{path.stem}", title=title, date=date, source="export"), transcript
        )

    def _export_meetings(self, limit: int) -> list[GranolaMeeting]:
        return [n.meeting for n in self._export_notes()[:limit]]

    def _export_transcript(self, meeting_id: str) -> tuple[str | None, str] | None:
        for note in self._export_notes():
            if note.meeting.id == meeting_id:
                return note.meeting.title, note.transcript
        return None
