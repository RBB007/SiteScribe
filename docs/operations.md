# Production operations

Render runs the Flask web service and two daily jobs. Supabase hosts Auth,
PostgreSQL, and the private project-files bucket. AWS S3 is the independent,
versioned file backup target.

## Initial setup

1. Create a Supabase project and private project-files bucket.
2. Create the trial administrator in Supabase Authentication with an email
   and password matching `BOOTSTRAP_ADMIN_EMAIL`. Public signup stays disabled.
3. Create a versioned S3 bucket with default encryption and an IAM principal
   limited to that bucket.
4. Connect the repository to Render using render.yaml, then set every
   sync: false secret in the dashboard.
5. Deploy, run the migrations, sign in as BOOTSTRAP_ADMIN_EMAIL, and verify
   /health/live and /health/ready.

Production starts empty. Do not copy local demo files into the cloud stores.

## Recovery and retention

- Supabase daily database backups are the database recovery source.
- The file job copies immutable objects to versioned S3 and verifies metadata.
- Project and visit deletion is soft deletion for 30 days. The retention job
  is the only process allowed to physically remove database rows and blobs.
- A restore drill must recreate a test environment from a database backup and
  the matching S3 object versions, then verify one complete archive ZIP.

## Release gate

Before production deployment, run the full tests, migration upgrade/downgrade
test, authorization isolation suite, archive checksum round-trip, backup
reconciliation, and retention dry run.

## Environment variables beyond the contract

`docs/cloud-contracts.md` lists the core environment contract. The code also reads:

| Variable | Used by | Default / notes |
| --- | --- | --- |
| `ANTHROPIC_API_KEY` | report drafting | Admins can also store an encrypted key on the Admin settings page |
| `ANTHROPIC_MODEL` | report drafting | `claude-sonnet-5-5` (also set in `render.yaml`) |
| `RESEND_API_KEY`, `REPORT_EMAIL_FROM` | report email delivery | Email delivery is unavailable without them |
| `AUTH_COOKIE_SECURE` | auth cookies | `true`; set `false` only for local HTTP testing |
| `AZURE_TENANT_ID` | auth config | Empty; reserved for future Microsoft Entra SSO |
| `LOG_LEVEL` | JSON logging | `INFO` |

## Installable app (PWA)

The service worker, offline queue, and their limitations are covered in [pwa.md](pwa.md).
