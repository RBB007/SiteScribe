# SiteScribe cloud migration agents

This file governs the cloud migration and overrides the older one-module ownership guidance in `AI_INSTRUCTIONS.md` where they conflict.

## Shell and safety

- Use `cmd.exe` for shell operations. Do not use Bash or PowerShell.
- Never modify or discard pre-existing uncommitted work.
- Never edit production secrets, apply migrations to shared cloud environments, delete production data, push, or merge `main`.
- Treat `webapp/server.py`, dependency files, Alembic migration numbering, route registration, this file, and `IMPLEMENTATION_TASKS.md` as coordinator-owned unless a task explicitly assigns them.

## Claiming work

1. Read `IMPLEMENTATION_TASKS.md` and select one `READY` task whose dependencies are complete.
2. From the primary checkout, atomically create `.agent-claims\<TASK_ID>`. If it already exists, choose another task.
3. Work on one task at a time in branch `agent/<TASK_ID>-short-name` and an isolated worktree under `C:\tmp\sitescribe-<TASK_ID>`.
4. Edit only the task's owned paths. Ask the coordinator before changing a frozen contract or shared file.
5. Run the task's baseline and acceptance commands before handing off.
6. Commit locally and report the commit hash, changed files, migrations, environment variables, and test evidence. The coordinator integrates tasks in dependency order.
7. If abandoning a task, leave a handoff note and release its claim directory.

## Implementation rules

- Keep Flask/Jinja/JavaScript and preserve the mobile capture workflow.
- New APIs must use explicit project and visit UUIDs; do not introduce new session-selected resource state.
- Every database and file operation must enforce active workspace membership.
- Store no durable runtime state on the Render filesystem.
- Keep Supabase buckets private and never persist signed URLs.
- Archive is reversible for 30 days. Purge only through the retention job after `purge_after`.
- A complete archive export must contain structured JSON, every original asset, generated reports, a manifest, and SHA-256 checksums.
- Add tests for authorization, failure compensation, sorting, archive/restore/purge, and any changed public contract.

