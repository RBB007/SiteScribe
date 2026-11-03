# Cloud migration contracts

## Locked product decisions

- One company workspace. The trial uses Supabase email/password accounts;
  Microsoft Entra SSO can be enabled later without changing application profiles.
- Roles are `admin` and `member`; all active members access all projects.
- Projects sort by `lower(name), id`; visits sort by `visit_date DESC, created_at DESC, id`.
- Production starts empty. Existing demo data is not imported.
- Archive/restore lasts 30 days, followed by automatic purge.
- Supabase provides Auth, PostgreSQL, and private primary Storage; Render hosts Flask and scheduled jobs; versioned AWS S3 backs up files.

## HTTP surface

- Auth: `GET/POST /auth/login`, `POST /auth/logout`, `GET /api/me`.
- Members: `GET /api/members`, `PATCH /api/members/{member_id}` (admin only).
- Projects: `GET/POST /api/projects`, `GET/PATCH/DELETE /api/projects/{project_id}`, `POST /api/projects/{project_id}/restore`.
- Visits: `GET/POST /api/projects/{project_id}/visits`, `GET/PATCH/DELETE /api/projects/{project_id}/visits/{visit_id}`, `POST /api/projects/{project_id}/visits/{visit_id}/restore`.
- Capture resources live below `/api/visits/{visit_id}` and never infer a visit from session state.
- Capture item, observation, and validated private-file routes always carry an explicit visit ID.
- Files: `GET /api/files/{file_id}` authorizes then redirects to a 60-second signed URL.
- Archives: `POST /api/visits/{visit_id}/exports/archive` and `POST /api/projects/{project_id}/exports/archive`.
- Use UUIDs, ISO dates, UTC timestamps, and JSON errors. Return 401 unsigned, 403 inactive, 404 absent/inaccessible, and 409 conflict.

## Environment contract

- `DATABASE_URL`
- `SUPABASE_URL`
- `SUPABASE_PUBLISHABLE_KEY`
- `SUPABASE_SECRET_KEY`
- `SUPABASE_STORAGE_BUCKET=project-files`
- `BOOTSTRAP_ADMIN_EMAIL`
- `APP_BASE_URL`
- `FLASK_SECRET_KEY`
- `AUTH_TOKEN_ENCRYPTION_KEYS` (comma-separated Fernet keys, newest first)
- `AWS_BACKUP_BUCKET`, `AWS_BACKUP_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`

## Storage and archive contract

- Blob API: `put`, `download_to`, `stat`, `signed_url`, `delete`.
- Key: `workspace/{workspace_id}/project/{project_id}/visit/{visit_id}/{file_id}/{sanitized_name}`.
- Never expose secret credentials or persist public/signed URLs.
- Archive ZIP schema version 1 includes project/visit JSON, all included and excluded photos, audio/transcripts, original and marked plans, templates, generated reports, `archive_manifest.json`, `README.txt`, and `checksums.sha256`.
- Archiving sets `purge_after = archived_at + 30 days`; restore clears both fields; only the scheduled retention job physically deletes data.
