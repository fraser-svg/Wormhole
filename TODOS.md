# Wormhole TODOS

## Core

- [ ] **Priority: P1** Eval harness: golden transcript with precision/recall measurement (deferred from v0.2.0 plan)
- [ ] **Priority: P1** Incremental offset-based harvesting for large transcripts (deferred from v0.2.0 plan)
- [ ] **Priority: P1** README with quickstart + config reference (deferred from v0.2.0 plan)
- [ ] **Priority: P2** MCP server / Claude Code extension integration — eliminate start/end ceremony entirely
- [ ] **Priority: P2** CI/CD pipeline for PyPI publishing (GitHub Actions)
- [ ] **Priority: P2** Multi-provider LLM abstraction (OpenAI, Ollama) — v0.3.0

## CLI

- [ ] **Priority: P3** `wormhole doctor` — vault health diagnostics
- [ ] **Priority: P3** `wormhole search <query>` — grep across vault
- [ ] **Priority: P3** `wormhole migrate` — vault schema upgrades
- [ ] **Priority: P4** Auto-detect init suggestion (cd into repo → suggest init)
- [ ] **Priority: P4** Session summary injection UX

## Multi-Tool

- [ ] **Priority: P2** Aider compiler + harvester
- [ ] **Priority: P2** Copilot compiler + harvester
- [ ] **Priority: P3** Generic compiler + harvester
- [ ] **Priority: P3** Session handoff (continue last session in different tool)
- [ ] **Priority: P3** Plugin system for community adapters

## Vault Features

- [ ] **Priority: P2** Breadcrumb injection into source files
- [ ] **Priority: P2** Team vaults (shared .wormhole/ in repo)
- [ ] **Priority: P3** Vault analytics (most referenced decisions, knowledge gaps)
- [ ] **Priority: P3** Export to docs (`wormhole export`)
- [ ] **Priority: P3** User-level config (~/.wormhole/config.yaml) with merge semantics
- [ ] **Priority: P3** Content validation / prompt injection detection for team vaults

## Completed

- [x] **Completed: v0.2.0.0 (2026-04-09)** LLM-assisted extraction (Anthropic Haiku, hybrid pipeline)
- [x] **Completed: v0.2.0.0 (2026-04-09)** Passive harvesting via git hooks / filesystem watcher
- [x] **Completed: v0.2.0.0 (2026-04-09)** Transcript redaction (API keys, JWTs, private keys, env secrets)
- [x] **Completed: v0.2.0.0 (2026-04-09)** Lockfile single-writer guarantee with stale lock detection
