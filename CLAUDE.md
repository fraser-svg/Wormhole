# Project Rules

Caveman mode always on (full intensity). Use /caveman skill in every response.

## Skill routing

When the user's request matches an available skill, ALWAYS invoke it using the Skill
tool as your FIRST action. Do NOT answer directly, do NOT use other tools first.
The skill has specialized workflows that produce better results than ad-hoc answers.

Key routing rules:
- Product ideas, "is this worth building", brainstorming → invoke office-hours
- Bugs, errors, "why is this broken", 500 errors → invoke investigate
- Ship, deploy, push, create PR → invoke ship
- QA, test the site, find bugs → invoke qa
- Code review, check my diff → invoke review
- Update docs after shipping → invoke document-release
- Weekly retro → invoke retro
- Design system, brand → invoke design-consultation
- Visual audit, design polish → invoke design-review
- Architecture review → invoke plan-eng-review
- Save progress, checkpoint, resume → invoke checkpoint
- Code quality, health check → invoke health

## Project Structure

```
wormhole/                # Main package
  __init__.py            # Version export
  cli.py                 # Click CLI (10 commands)
  vault.py               # Vault storage + block management
  scoring.py             # Relevance scoring (4 weighted factors)
  config.py              # YAML config handling
  manifest.py            # Vault manifest builder
  compiler_base.py       # Base compiler class
  compiler_claude.py     # Claude Code compiler (CLAUDE.md output)
  compiler_cursor.py     # Cursor compiler (.cursorrules output)
  harvester_base.py      # Base harvester + trigger extraction
  harvester_claude.py    # Claude JSONL transcript harvester
  utils.py               # Shared utilities
tests/
  test_wormhole.py       # 53 tests
```

## Development

```bash
pip install -e .         # Install in dev mode
pytest                   # Run tests
wormhole --help          # CLI usage
```
