"""FastMCP tool: search_agent_history."""

from fastmcp import FastMCP

from arny.adapters.history import HistoryAdapter, HistoryResult


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def search_agent_history(
        query: str = "",
        since: str | None = None,
        until: str | None = None,
        limit: int = 20,
    ) -> HistoryResult:
        """Search ~/.Life daily reports, meetings, profile and ~/.fb-mode run notes.

        `query` is a case-insensitive keyword (empty matches all). `since` and
        `until` are inclusive YYYY-MM-DD bounds. Results are newest first.
        """
        return HistoryAdapter().search(query, since=since, until=until, limit=limit)
