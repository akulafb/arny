# Arny

Arny answers questions about your own activity. It reads three sources:

- **Luci**: screen captures and audio transcripts (the `luci` CLI).
- **Granola**: meeting notes and transcripts.
- **History**: `~/.Life` daily reports, meetings and profile, plus `~/.fb-mode` run notes.

Arny only reads. It never writes to these sources. When a source is missing, Arny prints a warning and keeps going.

You can use Arny two ways:

1. As a CLI: `arny "<question>"`.
2. As an MCP server over stdio, for Raycast AI Chat, Claude Code and agy.

## Install

Arny needs [uv](https://docs.astral.sh/uv/) and Python 3.12+.

```sh
uvx arny --help
uvx arny "what did I work on today?"
```

To run it from GitHub or a local checkout instead of PyPI:

```sh
uvx --from git+https://github.com/akulafb/arny arny --help
uvx --from /path/to/arny arny "what did I work on today?"
```

## Ask a question

```sh
uvx arny "what did I work on today?"
uvx arny ask what did I discuss about pricing   # same thing, explicit command
```

Arny queries Luci, Granola and History in parallel.

- **With an LLM key set**, Arny writes a short answer. Each fact cites its source: `[Luci]`, `[Granola]` or `[History]`.
- **With no key set**, Arny prints the matching excerpts, ranked and grouped by source.

If the LLM call fails, Arny falls back to the excerpts. Warnings go to stderr.

| Variable | Use |
| --- | --- |
| `GEMINI_API_KEY` | Use Gemini for answers. |
| `ANTHROPIC_API_KEY` | Use Claude for answers. |
| `OPENAI_API_KEY` | Use OpenAI for answers. |
| `ARNY_LLM_PROVIDER` | Pick one provider (`gemini`, `anthropic`, `openai`) when several keys are set. Default order is the order above. |
| `ARNY_LLM_MODEL` | Override the model name for the chosen provider. |

### Source settings

| Variable | Default | Use |
| --- | --- | --- |
| `LUCI_PATH` | `~/.local/bin/luci`, then `PATH` | Path to the `luci` binary. |
| `GRANOLA_CLI_PATH` | Granola.app's bundled CLI | Path to the Granola CLI. |
| `ARNY_GRANOLA_TOKEN` | unset | Granola public API token. |
| `ARNY_GRANOLA_EXPORT_DIR` | unset | Folder of Granola CSV / Markdown exports. |
| `LIFE_PATH` | `~/.Life` | Life folder for History. |
| `FB_MODE_PATH` | `~/.fb-mode/runs` | Run notes for History. |

## MCP server

Start the stdio server with either command:

```sh
uvx arny serve
uvx --from arny arny-mcp
```

Tools: `ping`, `status`, `search_luci`, `get_luci_transcripts`, `get_granola_meetings`, `get_granola_transcript`, `search_agent_history`.

### Raycast AI Chat

1. Open Raycast. Run the **Install Server** command (MCP extension).
2. Set **Name** to `arny`.
3. Set **Command** to `uvx`.
4. Set **Arguments** to `arny serve`.
5. Save. In AI Chat, type `@arny` to use its tools.

You can also paste this JSON into the Install Server form:

```json
{
  "mcpServers": {
    "arny": { "command": "uvx", "args": ["arny", "serve"] }
  }
}
```

### Claude Code CLI

```sh
claude mcp add arny --scope user -- uvx arny serve
claude mcp list
```

To pass a source setting, add `-e`, for example `-e LIFE_PATH=$HOME/.Life`.

### agy (Antigravity CLI)

Add Arny to the global MCP config, `~/.gemini/config/mcp_config.json`:

```json
{
  "mcpServers": {
    "arny": {
      "command": "uvx",
      "args": ["arny", "serve"]
    }
  }
}
```

Restart agy. agy caches each server's tool list under `~/.gemini/antigravity-cli/mcp/arny/`. Do not edit that folder by hand.

## Develop

```sh
uv sync
uv run pytest -q
uv run arny --help
uv run arny "test query"
```

The tests fake Luci, Granola and `~/.Life`. They do not need any of them installed.
