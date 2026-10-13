"""Adapter around the `luci` CLI (screen memory and audio transcripts)."""

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

DEFAULT_LUCI_PATH = Path.home() / ".local" / "bin" / "luci"
MIN_LIMIT, MAX_LIMIT = 1, 500
TIMEOUT_SECONDS = 30.0  # non-status commands may start Luci and wait ~20s

Status = Literal["ok", "unavailable"]


class ScreenCapture(BaseModel):
    """One matched screen capture from `luci search`."""

    model_config = ConfigDict(populate_by_name=True)

    capture_id: int = Field(alias="captureId")
    timestamp: int
    app: str | None = None
    window_title: str | None = Field(default=None, alias="windowTitle")
    browser_url: str | None = Field(default=None, alias="browserUrl")
    text: str = ""
    score: float | None = None
    screenshot_path: str | None = Field(default=None, alias="screenshotPath")


class TranscriptSegment(BaseModel):
    """One audio transcript segment from `luci transcript`."""

    model_config = ConfigDict(populate_by_name=True)

    id: int
    session_id: int | None = Field(default=None, alias="sessionId")
    source: str | None = None
    t_start: int = Field(alias="tStart")
    t_end: int = Field(alias="tEnd")
    text: str = ""


class LuciSearchResponse(BaseModel):
    status: Status
    warning: str | None = None
    results: list[ScreenCapture] = []


class LuciTranscriptResponse(BaseModel):
    status: Status
    warning: str | None = None
    results: list[TranscriptSegment] = []


class LuciUnavailable(Exception):
    """Luci is not installed, not running, or its call failed."""


def resolve_luci_path() -> str | None:
    """Find the luci binary: LUCI_PATH, then ~/.local/bin/luci, then PATH."""
    override = os.environ.get("LUCI_PATH")
    if override:
        return override if Path(override).is_file() else None
    if DEFAULT_LUCI_PATH.is_file():
        return str(DEFAULT_LUCI_PATH)
    return shutil.which("luci")


def _clamp_limit(limit: int) -> int:
    return max(MIN_LIMIT, min(MAX_LIMIT, limit))


class LuciAdapter:
    """Runs `luci ... --json` and turns its output into typed responses.

    Never raises for a missing or failing Luci: it returns status
    "unavailable" with a warning and no results.
    """

    def __init__(
        self,
        path: str | None = None,
        runner: Callable[..., subprocess.CompletedProcess] | None = None,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        self._path = path
        self._run = runner
        self._timeout = timeout

    def search(
        self,
        query: str,
        app: str | None = None,
        limit: int = 20,
        time_range: str = "24h",
    ) -> LuciSearchResponse:
        args = [
            "search",
            query,
            "--tr",
            time_range,
            "--limit",
            str(_clamp_limit(limit)),
        ]
        if app:
            args += ["--app", app]
        try:
            results = self._items(args, "results", ScreenCapture)
        except LuciUnavailable as exc:
            return LuciSearchResponse(status="unavailable", warning=str(exc))
        return LuciSearchResponse(status="ok", results=results)

    def transcripts(
        self,
        query: str | None = None,
        limit: int = 50,
        time_range: str = "7d",
    ) -> LuciTranscriptResponse:
        args = ["transcript", *([query] if query else [])]
        args += ["--tr", time_range, "--limit", str(_clamp_limit(limit))]
        try:
            results = self._items(args, "segments", TranscriptSegment)
        except LuciUnavailable as exc:
            return LuciTranscriptResponse(status="unavailable", warning=str(exc))
        return LuciTranscriptResponse(status="ok", results=results)

    def _items(self, args: list[str], key: str, model: type[BaseModel]) -> list:
        payload = self._call(args)
        items = payload if isinstance(payload, list) else payload.get(key, [])
        try:
            return [model.model_validate(item) for item in items]
        except ValidationError:
            raise LuciUnavailable("Luci returned results in an unexpected shape.")

    def _call(self, args: list[str]) -> dict | list:
        path = self._path or resolve_luci_path()
        if not path:
            raise LuciUnavailable(
                "Luci CLI not found. Install Luci or set LUCI_PATH to the luci binary."
            )
        try:
            run = self._run or subprocess.run
            proc = run(
                [path, *args, "--json"],
                capture_output=True,
                text=True,
                timeout=self._timeout,
            )
        except subprocess.TimeoutExpired:
            raise LuciUnavailable(f"Luci did not respond within {self._timeout:g}s.")
        except OSError as exc:
            raise LuciUnavailable(f"Could not run Luci CLI at {path}: {exc}")
        if proc.returncode != 0:
            detail = (proc.stderr or "").strip() or "no error output"
            raise LuciUnavailable(f"Luci exited with code {proc.returncode}: {detail}")
        try:
            payload = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            raise LuciUnavailable("Luci returned output that is not valid JSON.")
        if not isinstance(payload, (dict, list)):
            raise LuciUnavailable("Luci returned an unexpected JSON shape.")
        return payload
