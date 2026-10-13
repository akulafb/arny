"""FastMCP tools for Granola meetings."""

from fastmcp import FastMCP

from arny.adapters.granola import (
    GranolaAdapter,
    GranolaMeetingsResult,
    GranolaTranscriptResult,
)


def register(mcp: FastMCP) -> None:
    @mcp.tool()
    def get_granola_meetings(limit: int = 20) -> GranolaMeetingsResult:
        """List recent Granola meetings, newest first."""
        return GranolaAdapter.from_env().get_meetings(limit=limit)

    @mcp.tool()
    def get_granola_transcript(meeting_id: str) -> GranolaTranscriptResult:
        """Get the transcript of one Granola meeting by its id."""
        return GranolaAdapter.from_env().get_transcript(meeting_id)
