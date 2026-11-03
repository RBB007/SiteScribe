# Contributing to SiteScribe

## Workflow

1. Branch from `main`. Do not push to `main` directly.
2. Keep each change focused. For cloud-migration work, claim a task in [IMPLEMENTATION_TASKS.md](IMPLEMENTATION_TASKS.md) and follow [AGENTS.md](AGENTS.md). It covers ownership of shared files (`webapp/server.py`, dependency files, migration numbering, route registration).
3. Run `python -m pytest` before opening a pull request, and say in the PR how you tested.
4. Open a pull request into `main`. The coordinator reviews and merges it.

## Rules

- **No secrets in the repository.** Keys come from environment variables (see [docs/cloud-contracts.md](docs/cloud-contracts.md)). Supabase buckets stay private, and signed URLs are never persisted.
- **No site data in git.** Do not commit plan sets, photos, audio, or reports. Local legacy data lives under `webapp/data/` and `webapp/uploads/`, which git ignores.
- **Enforce workspace membership** on every new database or file operation, and use explicit project and visit UUIDs in new APIs.
- **Add tests** for authorization, failure handling, sorting, archive/restore/purge, and any public contract you change.
- **Add packages to `requirements.txt`** in the same change that needs them.
- **Report drafting rules** live in `webapp/report_assets/AGENTS.md`. Changes there change what the AI may write in a report, so they need engineering review.
