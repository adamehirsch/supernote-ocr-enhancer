# Claude Code Instructions

## CRITICAL: This is a PUBLIC Repository

**All commits are pushed to a PUBLIC GitHub repository.** Before committing or pushing, verify that no private information is exposed:

### Never include in commits:
- **Personal file names** (e.g., "Marriage.note", "Baby Care.note", "Job Applications.note")
- **Personal names** or identifiable information
- **Passwords, API keys, or secrets**
- **File paths containing usernames** (e.g., `/Users/dhays/...`)
- **Database contents** with personal data
- **Log snippets** containing personal information

### Before every commit:
1. Review `git diff --staged` for any personal information
2. Use generic examples instead of real file names (e.g., "MyNote.note" not "Marriage.note")
3. Sanitize any paths or database queries shown in documentation

### If private data is accidentally committed:
- It remains in git history even after removal
- Requires `git filter-branch` or `git filter-repo` + force push to fully remove
- GitHub may cache old commits - contact GitHub support if needed

## Project Context

This is the Supernote OCR Enhancer — processes `.note` files with Apple Vision Framework OCR. Part of a larger pipeline; see `~/Repositories/slatesync/AGENTS.md` for system-wide context, architectural decisions, and cross-repo conventions.

- **Python 3.11**, managed by `pip` with a local `.venv/`. Do not use `uv`.
- Tests: `.venv/bin/pytest tests/ -v`
- Remote: `git@github.com:adamehirsch/supernote-ocr-enhancer.git` (fork of `liketheduck/supernote-ocr-enhancer`)

Key files:
- `app/main.py` — Entry point, env var handling
- `app/sync_handlers.py` — Sync database management (SQLCipher support for `en_supernote.db`)
- `app/note_processor.py` — `.note` file handling and OCR injection
- `app/database.py` — SQLite state tracking (processing history)
- `scripts/` — Helper scripts for OCR API and launchd management
- `tests/test_sync_handlers.py` — Sync handler tests (22 tests)
