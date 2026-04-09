# Wormhole

Universal project intelligence for AI coding agents.

Wormhole gives your AI tools persistent memory across sessions. It harvests knowledge from your coding sessions (decisions, corrections, discoveries, architecture notes, failures, context), scores it by relevance, and compiles it into the context format your AI tool expects.

**The loop:** You code with an AI tool. Wormhole watches the session transcript. When you're done, it extracts what the AI learned, stores it in a local vault, and injects the most relevant knowledge into your next session's context.

## Install

```bash
pip install -e .
```

Optional extras:

```bash
pip install -e ".[llm]"   # LLM-assisted extraction (Anthropic Haiku)
pip install -e ".[mcp]"   # MCP server for Claude Code live queries
```

Requires Python 3.10+.

## Quick Start

### Daemon mode (recommended)

Install once, forget about it. Wormhole discovers your projects, watches for new sessions, and auto-harvests knowledge in the background.

```bash
# Start the background daemon
wormhole up

# Register MCP server so Claude Code can query your vault mid-session
wormhole mcp install

# That's it. Wormhole auto-discovers projects from ~/.claude/projects/,
# creates .wormhole/ vaults, and harvests knowledge as you work.

# Check what's running
wormhole daemon-status

# Stop the daemon
wormhole down
```

### Manual mode

For per-project, per-session control:

```bash
# Initialize a vault in your project
wormhole init

# Start a session (compiles context + launches your AI tool)
wormhole start

# ... do your work ...

# End the session (harvests knowledge + rebuilds manifest)
wormhole end
```

## CLI Commands

| Command | What it does |
|---------|-------------|
| `wormhole up` | Start background daemon (multi-project watching + auto-harvest) |
| `wormhole down` | Stop the background daemon |
| `wormhole daemon-status` | Show daemon state and tracked project count |
| `wormhole mcp` | Start MCP server on stdio (called by Claude Code) |
| `wormhole mcp install` | Register Wormhole as MCP server in `~/.claude.json` |
| `wormhole init` | Initialize a `.wormhole/` vault in the current project |
| `wormhole start` | Compile context and launch an AI tool session |
| `wormhole end` | Harvest knowledge and rebuild manifest after a session |
| `wormhole boot` | Compile and write context without launching the tool |
| `wormhole harvest` | Extract knowledge blocks from the latest session transcript |
| `wormhole status` | Show vault statistics and configuration summary |
| `wormhole manifest` | Rebuild and display the vault manifest |
| `wormhole config` | View or modify vault configuration (show, set, edit) |
| `wormhole new` | Create a new knowledge block with scaffolded frontmatter |
| `wormhole review` | Review staged blocks (low-confidence harvested blocks) |
| `wormhole watch` | Passively watch for transcript changes and auto-harvest |
| `wormhole install-hooks` | Install git post-commit hook for automatic harvesting |
| `wormhole uninstall-hooks` | Remove wormhole git hooks and restore originals |

## How It Works

### Vault

Knowledge lives in `.wormhole/` as structured markdown blocks with YAML frontmatter, organized into 6 categories: **decisions**, **corrections**, **discoveries**, **architecture**, **failures**, and **context**.

### Harvesting

The harvester reads AI session transcripts (currently Claude Code JSONL) and extracts knowledge using a hybrid pipeline:

1. **Trigger phrases** ... regex patterns detect decisions, corrections, discoveries, architecture notes, and failures
2. **LLM extraction** (optional) ... Anthropic Haiku runs as a second pass to catch implicit knowledge that triggers miss

Transcripts are redacted (API keys, JWTs, private keys stripped) before any LLM API call. Low-confidence blocks go to staging for manual review.

**Passive mode:** `wormhole watch`, `wormhole install-hooks claude`, or the background daemon (`wormhole up`) auto-harvest without manual `wormhole end`.

To enable LLM extraction: `pip install wormhole-ai[llm]` and `wormhole config set llm.enabled true`.

### MCP Server

The MCP server lets Claude Code query your vault live, mid-session. Run `wormhole mcp install` to register it. Claude Code spawns the server as a subprocess and gets 4 tools:

- **query_vault** ... list blocks, optionally filtered by category or keyword
- **get_block** ... full content of a specific block by title
- **search_vault** ... regex search across all blocks
- **list_projects** ... all projects tracked by the daemon

### Global Config

Daemon and discovery settings live in `~/.wormhole/config.yaml`. Per-project settings in `.wormhole/config.yaml` override global defaults. Three-level merge: hardcoded defaults < global `project_defaults` < per-project config.

### Scoring

When compiling context, each block gets a relevance score from 4 weighted factors:

- **Recency** ... newer knowledge ranks higher (exponential decay)
- **File proximity** ... blocks referencing files you're working on rank higher
- **Dependency depth** ... blocks referenced by other blocks rank higher
- **Category weight** ... configurable per-category importance

### Compilers

Compilers take scored vault blocks and write them into the format your AI tool reads:

- **Claude Code** ... compiles into `CLAUDE.md` with sentinel markers (preserves existing content)
- **Cursor** ... compiles into `.cursorrules` format

## Supported Tools

| Tool | Harvester | Compiler |
|------|-----------|----------|
| Claude Code | Yes | Yes |
| Cursor | — | Yes |
| Aider | Planned | Planned |
| Copilot | Planned | Planned |

## License

MIT

## Links

- [Changelog](CHANGELOG.md)
- [Roadmap](TODOS.md)
