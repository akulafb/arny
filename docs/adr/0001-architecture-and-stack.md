# ADR 0001: Architecture and Tech Stack

## Context
We need a unified MCP server and CLI (`arny`) allowing agents to query:
1. Seen / Done (Luci): Screen memory, app usage, and audio transcripts.
2. Heard / Discussed (Granola): Meeting notes and transcripts.
3. Agent Actions / Life: Distilled reflections (`~/.Life`) and agent logs.

## Decision
1. **Language & Tooling**: Python 3.12+ managed with `uv`.
2. **Framework**: FastMCP for the Model Context Protocol stdio server, with Click/Typer for the standalone CLI.
3. **Data Access Adapters**:
   - `LuciAdapter`: Invokes `luci` CLI (`--json`) with subprocess execution.
   - `GranolaAdapter`: Bridges Granola's bundled companion CLI (`/Applications/Granola.app/Contents/Resources/bin/granola`), with fallbacks for local export folders and session tokens.
   - `AgentHistoryAdapter`: Reads and indexes `~/.Life` (`reflections/daily/`, `reflections/meetings/`, `profile.md`) and `~/.fb-mode/runs/`.
4. **Issue Tracking**: Linear project `Arny` via `orca linear`.

## Status
Accepted
