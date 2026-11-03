# SiteScribe (MKA Site Visit Buddy)

Walk a site with a phone, capture observations, and generate a draft site visit report for engineer review.

Every generated report is a draft. The engineer of record reviews and approves it before it is issued.

## What it does

| Stage | What happens |
| --- | --- |
| **Organize** | Projects contain site visits. All active workspace members can see all projects. |
| **Capture** | Per observation: photos, typed or dictated description, audio, a severity, tags, an action item, and a pin on the plan. |
| **Work offline** | The app installs to the home screen. Visits you have opened stay viewable offline, and edits and photo uploads are queued until you reconnect. See [docs/pwa.md](docs/pwa.md). |
| **Report** | The AI drafts report text from the field record only (rules in [webapp/report_assets/AGENTS.md](webapp/report_assets/AGENTS.md)). The Word report uses the MKA template. |
| **Archive** | Archived projects and visits can be restored for 30 days and are then purged. A full archive export is a ZIP containing JSON, every original file, the generated reports, a manifest, and SHA-256 checksums. |

## Architecture

```
phone / browser (PWA)  ──HTTPS──▶  Render: gunicorn webapp.cloud_app:app (Flask)
                                     │  Supabase Auth      (email/password sign-in)
                                     │  Supabase Postgres  (Alembic migrations)
                                     │  Supabase Storage   (private bucket, 60 s signed URLs)
                                     │  Anthropic API      (report drafting)
                                     │  Resend             (report email delivery)
Render cron jobs:  daily file backup to versioned S3 · daily retention purge
```

The app is configured in [render.yaml](render.yaml). The HTTP, environment, and storage contracts are in [docs/cloud-contracts.md](docs/cloud-contracts.md). Setup, recovery, and the release gate are in [docs/operations.md](docs/operations.md).

## Repository layout

| Path | Contents |
| --- | --- |
| `webapp/cloud_app.py` | Production app factory (Render entry point) |
| `webapp/cloud/` | Auth, DB, storage, capture API, reports, archive, ops jobs |
| `webapp/templates/cloud_*.html`, `webapp/static/` | Mobile UI, PWA manifest, service worker, offline queue |
| `webapp/report_assets/` | Versioned report instructions and the MKA Word template |
| `sitescribe/` | Report data model and Word report builder used by the cloud app |
| `migrations/` | Alembic migrations (see [migrations/README](migrations/README)) |
| `supabase/` | Supabase config and SQL migrations |
| `webapp/server.py`, `run.py` | Legacy single-user local app (PIN login, files on disk); see [docs/legacy-local-app.md](docs/legacy-local-app.md) |
| `tests/` | pytest suite |

## Development

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m pytest
```

The tests use SQLite and local fakes, so they need no cloud credentials. Running the cloud app itself requires the environment variables listed in [docs/cloud-contracts.md](docs/cloud-contracts.md). Never commit secrets: set them in the Render dashboard or in an untracked `.env` file.

To try the capture UI without cloud services, run the legacy local app with `python run.py`. See [docs/legacy-local-app.md](docs/legacy-local-app.md).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Agents working on the cloud migration follow [AGENTS.md](AGENTS.md) and the task ledger in [IMPLEMENTATION_TASKS.md](IMPLEMENTATION_TASKS.md).

## History

SiteScribe started at the NCSEA Hackathon 2026. The hackathon-era module contract, integration plan, merge process, and tunnel deployment notes are kept in [docs/archive/hackathon/](docs/archive/hackathon/) for reference. They no longer describe how this repository is built or deployed.
