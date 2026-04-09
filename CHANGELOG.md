# Changelog

All notable changes to this project will be documented in this file.

## [0.2.0.0] - 2026-04-09

### Added
- LLM-assisted block extraction using Anthropic Haiku API (optional: `pip install wormhole-ai[llm]`)
- Hybrid extraction pipeline: regex trigger phrases + LLM second pass
- Transcript redaction: strips API keys, JWTs, private keys, env secrets, and home paths before LLM calls
- `extraction_method` field on blocks tracks "trigger" vs "llm" extraction source
- Passive filesystem watcher: `wormhole watch` polls for transcript changes and auto-harvests
- Git hooks: `wormhole install-hooks` / `wormhole uninstall-hooks` for post-commit auto-harvest
- Lockfile-based single-writer guarantee prevents concurrent harvest races
- Stale lock detection (auto-breaks locks older than 5 minutes)
- LLM config section: model, chunk_size, max_chunks, temperature, api_key_env
- Watcher config section: poll_interval, auto_manifest
- Content-hash change detection in watcher (not just mtime)
- Loud LLM failure warnings with actionable fix suggestions
- 90 new tests (143 total) covering LLM extraction, redaction, watcher, hooks, lock/state

### Fixed
- Idempotency bug: harvest state check now runs after read_transcript() sets session_id
- Git hook now uses correct Click group option ordering (`wormhole --quiet end` not `wormhole end --quiet`)
- Git hook includes explicit tool argument (was silently failing with empty default_tool)
- `config set` boolean coercion: `"false"`/`"true"` stored as actual bools, not truthy strings
- File descriptor leak in lock acquisition on contention
- `_has_negation` restored to whole-word matching (was regressed to substring)
- `list_blocks` restored VALID_CATEGORIES filter (was scanning .git, __pycache__)
- `shlex.split` restored for `$EDITOR` values with flags (e.g., "code --wait")
- Error handling restored in `end` command for manifest/index rebuild failures
- Unused imports removed from compiler modules

### Changed
- `anthropic` is now an optional dependency under `[llm]` extras

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
