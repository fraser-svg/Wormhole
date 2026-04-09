# Wormhole

Universal project intelligence for AI coding agents.

Wormhole gives your AI tools persistent memory across sessions. It harvests knowledge from your coding sessions (decisions, corrections, discoveries, architecture notes, failures, context), scores it by relevance, and compiles it into the context format your AI tool expects.

**The loop:** You code with an AI tool. Wormhole watches the session transcript. When you're done, it extracts what the AI learned, stores it in a local vault, and injects the most relevant knowledge into your next session's context.

## Install

```bash
pip install -e .
```

Requires Python 3.10+.

## Quick Start

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

## How It Works

### Vault

Knowledge lives in `.wormhole/` as structured markdown blocks with YAML frontmatter, organized into 6 categories: **decisions**, **corrections**, **discoveries**, **architecture**, **failures**, and **context**.

### Harvesting

The harvester reads AI session transcripts (currently Claude Code JSONL), extracts knowledge using trigger-phrase detection with structural context validation, and scores confidence. Low-confidence blocks go to a staging directory for manual review.

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
