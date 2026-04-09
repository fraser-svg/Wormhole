# Changelog

All notable changes to this project will be documented in this file.

## [0.1.0.0] - 2026-04-09

### Added
- Core vault system: structured markdown blocks with YAML frontmatter across 6 categories (decisions, corrections, discoveries, architecture, failures, context)
- Relevance scoring engine with 4 weighted factors (recency, file proximity, dependency depth, category weight)
- Claude Code compiler: compiles vault into CLAUDE.md with sentinel markers preserving existing content
- Cursor compiler: compiles vault into .cursorrules format
- Claude Code harvester: extracts knowledge blocks from JSONL session transcripts
- Trigger-phrase extraction with structural context validation and confidence scoring
- Staging directory for low-confidence blocks with interactive review workflow
- Block deduplication with contradiction detection (won't auto-merge opposing decisions)
- Click CLI with 10 commands: init, start, end, boot, harvest, status, manifest, config, new, review
- Rich colored terminal output
- Vault versioning (.version file) for future schema migrations
- Index cache (.index.json) for fast boot with large vaults
- Path traversal prevention on all file writes
- Harvest idempotency (tracks last-harvested session ID)
- First-run experience: example blocks and project-goal stub on init
- 53 tests covering all modules
