# SiteScribe cloud migration task ledger

Statuses are coordinator-maintained: `BLOCKED`, `READY`, `CLAIMED`, `DONE`.

| ID | Wave | Status | Dependencies | Owned paths / responsibility | Acceptance |
|---|---:|---|---|---|---|
| T-000 | 0 | DONE | - | `AGENTS.md`, this ledger, `docs/cloud-contracts.md`, `.gitignore` claim entry | Contracts and claim protocol exist |
| T-010 | 0 | DONE | T-000 | Flask app-factory/blueprint refactor; preserve user-owned PWA changes | Existing test suite passes |
| T-101 | 1 | DONE | T-000 | `webapp/cloud/db/**`, `migrations/**`, DB tests | Schema migrates up/down; repository tests pass |
| T-102 | 1 | DONE | T-000 | `webapp/cloud/auth/**`, auth tests/templates | Tenant, pending, admin/member flows pass |
| T-103 | 1 | DONE | T-000 | `webapp/cloud/storage/**`, storage tests | Local/Supabase contract and failure tests pass |
| T-104 | 1 | READY | T-000 | New cloud dashboard assets using fixture contracts; do not edit current dirty templates | Sorting/archive UI tests pass |
| T-105 | 1 | DONE | T-000 | `render.yaml`, operations modules/docs, health/log tests | Blueprint validates; health tests pass |
| T-106 | 1 | DONE | T-000 | `webapp/cloud/archive/**`, archive tests | Full manifest/checksum round-trip passes |
| T-107 | 1 | READY | T-101,T-103 | Backup and 30-day retention services/tests | Backup, restore, purge safety tests pass |
| T-201 | 2 | DONE | T-010,T-101,T-102 | Project/visit/member API integration | CRUD, sorting, archive/restore tests pass |
| T-202 | 2 | READY | T-010,T-101,T-102,T-103 | Explicit visit-scoped capture backend | Multi-tab/concurrency tests pass |
| T-203 | 2 | READY | T-010,T-104 | Capture frontend visit context | Browser contract tests pass |
| T-204 | 2 | READY | T-101,T-103 | Cloud materialization and report exports | Existing report/export parity passes |
| T-205 | 2 | READY | T-103,T-106,T-204 | Complete project/visit ZIP integration | Raw-data ZIP round-trip passes |
| T-206 | 2 | READY | T-101,T-102,T-103 | Security regression suite | Cross-resource access is denied |
| T-207 | 2 | READY | T-105,T-107 | Scheduled backup/purge integration | Job, alert, restore drill tests pass |
| T-301 | 3 | BLOCKED | T-201..T-207 | Coordinator integration and staging rehearsal | Full suite and recovery drills pass |
