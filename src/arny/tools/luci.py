"""FastMCP tools backed by Luci (screen memory and audio transcripts)."""

from fastmcp import FastMCP

from arny.adapters.luci import LuciAdapter, LuciSearchResponse, LuciTranscriptResponse


def register(mcp: FastMCP) -> None:
    """Add the Luci tools to the server."""

    @mcp.tool()
    def search_luci(
        query: str,
        app: str | None = None,
        limit: int = 20,
        time_range: str = "24h",
    ) -> LuciSearchResponse:
        """Search text Luci captured from the screen.

        `app` filters by exact app name as Luci records it (e.g. "Orca", "Arc").
        `time_range` is relative (30m, 24h, 7d, 2w) or "<fromMs>:<toMs>".
        `limit` is clamped to 1..500. When Luci is missing or not running,
        status is "unavailable" with a warning and no results.
        """
        return LuciAdapter().search(query, app=app, limit=limit, time_range=time_range)

    @mcp.tool()
    def get_luci_transcripts(
        query: str | None = None,
        limit: int = 50,
        time_range: str = "7d",
    ) -> LuciTranscriptResponse:
        """Search audio transcripts Luci recorded (mic and screen audio).

        Without `query`, returns all recent segments in `time_range`.
        Group segments by `session_id` to rebuild one meeting. When Luci is
        missing or not running, status is "unavailable" with a warning.
        """
        return LuciAdapter().transcripts(query, limit=limit, time_range=time_range)
