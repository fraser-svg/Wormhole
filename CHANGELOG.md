# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0.0] - 2026-04-09

### Added
- Store project knowledge in a structured vault with 6 categories: decisions, corrections, discoveries, architecture, failures, context
- Relevance scoring picks the right knowledge for each session using 4 factors: recency, file proximity, dependency depth, and category weight
- Compile your vault into Claude Code (`CLAUDE.md` with sentinel markers) or Cursor (`.cursorrules`) format
- Harvest knowledge automatically from Claude Code JSONL session transcripts
- Trigger-phrase extraction with structural context validation and confidence scoring
- Low-confidence blocks go to staging for your review before entering the vault
- Deduplication with contradiction detection, so opposing decisions don't silently merge
- Full CLI with 10 commands: `init`, `start`, `end`, `boot`, `harvest`, `status`, `manifest`, `config`, `new`, `review`
- Rich colored terminal output
- Vault versioning (`.version` file) for future schema migrations
- Index cache (`.index.json`) for fast boot with large vaults
- Path traversal prevention on all file writes
- Harvest idempotency (tracks last-harvested session ID so you don't re-process)
- First-run experience: example blocks and project-goal stub on `wormhole init`
- 82 tests covering all modules

### Fixed
- Negation detection in deduplication now uses whole-word matching (previously "knowledge" falsely matched "no")
- `list_blocks` no longer leaks staged (unreviewed) blocks into compiled context
- `$EDITOR` values with flags (e.g., `code --wait`) now handled correctly via `shlex.split`
- `end` command wraps manifest/index rebuild in error handling
- Removed unused `Config` imports from compiler subclasses
