# Integration plan: Flask app + `sitescribe/` modules

**Decision (2026-10-27):** the team builds on Hosein's Flask app (`webapp/`, branch `hosein/item-capture-app`) as the phone UI and server. The `sitescribe/` package stays the home for everyone's modules, unchanged: same files, same function signatures, same `models.py` contract. The Flask routes become the glue that calls them.

The Streamlit `app.py` is retired. Nothing a module author wrote changes; only who calls it.

## Why this split

- The Flask app already works on a real phone over HTTPS (camera, microphone, PDF plan pinning, Word export) and matches the item / photo / location / description / flag / tags layout.
- The modules are UI-independent by design (`AI_INSTRUCTIONS.md` rule 4), so swapping the frame costs module authors nothing.
- One owner per layer: Hosein owns `webapp/` (UI + routes), RBB007 owns `sitescribe/models.py`, `sitescribe/storage.py` and the adapter that joins the two, each teammate owns their module.

## How the pieces fit

```
phone browser  ──HTTPS──▶  webapp/server.py (Flask)
                                │
                                │  webapp/bridge.py  (JSON item  ⇄  models.Observation)
                                ▼
                      sitescribe/  plans · photos · voice · locate · ai_writer · plan_markup · word_report
```

`webapp/bridge.py` is new, owned by RBB007. It converts the server's JSON (`visit.json`: items, photos, plans) into `Project` / `Observation` / `PlanSheet` / `PlanPin` objects and back. Module authors never see the JSON; route authors never see the dataclasses.

Every module call is wrapped the same way the Streamlit app did it:

```python
def try_module(fn, *args, fallback=None):
    """Call a sitescribe function; if it isn't built yet, use the fallback."""
    try:
        return fn(*args)
    except NotImplementedError:
        return fallback() if callable(fallback) else fallback
```

The fallback is whatever the Flask app does today (inline Whisper call, plain python-docx report). So the demo never breaks while modules are being written, and each module replaces its fallback the moment it is merged.

## Route by route

| Route (exists today) | Today | After integration | Module |
| --- | --- | --- | --- |
| `POST /api/plan` | saves PDF, counts pages with pypdf, frontend renders with PDF.js | also `plans.load_plan_set(pdf, out_dir)` → one `PlanSheet` per page with a PNG; serve PNGs so the frontend can show sheet images and the report can use them. PDF.js stays as fallback. | `plans.py` |
| `POST /api/item/<id>/photo` | saves file | also `photos.read_photo_metadata(path)` → `taken_at`, `gps`; if no location yet, `locate.gps_to_pin(gps, sheet)` | `photos.py`, `locate.py` |
| `POST /api/item/<id>/audio` | inline Whisper HTTP call | `voice.transcribe(path)`; if no location yet, `voice.location_from_speech(text, sheets)`; fallback = today's inline call | `voice.py` |
| `GET /api/export/docx` | builds a plain docx inline | `bridge.to_project()` → `photos.embed_observation` per photo → `word_report.build_report(project, out)`; fallback = today's inline docx | `word_report.py`, `photos.py` |
| `GET /api/export/plans` (new) | – | `plan_markup.export_marked_plans(project, out_pdf)` | `plan_markup.py` |
| `POST /api/draft` (new) | – | `ai_writer.clean_up_description` per item, `ai_writer.suggest_action_item` for Major/Critical/Safety, `ai_writer.draft_summary(project)`; result stored in `visit.json` and shown before export | `ai_writer.py` |
| `GET /api/visit`, `POST/PATCH/DELETE /api/item…` | JSON CRUD | unchanged | – |

## Data model mapping (`bridge.py`)

| Flask JSON | `models.py` |
| --- | --- |
| `item_id` `I-003` | `Observation.number = 3`, `Observation.id` |
| `photos[]` (`photo_id`, `filename`, `caption`) | `Observation.photos` (list of `Path`); `photo_path = photos[0]` |
| `importance` | `Observation.severity` (`Severity`) |
| `description`, `tags` | same |
| `location {plan_id, page, x, y}` | `PlanPin(sheet_id, x, y)` where the sheet is `(plan_id, page)` |
| `audio {filename, transcript}` | `Observation.audio_path` |
| `include` | **new** `Observation.include: bool = True` |
| photo `caption` | **new** `Observation.captions: dict[str, str]` keyed by photo filename |
| `plans[]` (`plan_id`, `file`, `pages`) | one `PlanSheet` per page: `source_pdf`, `page_index`, `image_path` (from `plans.py`) |
| – | `Project.name / site_address / engineer / summary / report_options` come from a small **new** `POST /api/visit` settings form (project name, address, engineer, Word template upload) |

Two fields are added to `models.py` (RBB007 only): `Observation.include` and `Observation.captions`. Both default to harmless values, so no module needs to change.

## Repo layout after the merge

```
webapp/            Flask UI + routes             Hosein
  server.py
  bridge.py        JSON ⇄ models adapter         RBB007
  templates/index.html
sitescribe/        modules + models + storage    one owner each
tests/
run.py             `python run.py` starts the Flask app from the repo root
AI_INSTRUCTIONS.md unchanged rules; "frame" paragraph updated to Flask
```

`webapp/server.py` runs from the repo root (`python run.py`) so `import sitescribe` works without path hacks. `requirements.txt` gets the Flask lines from `webapp/requirements.txt`; Streamlit lines go.

## Order of merges

1. **Hosein opens a PR from `hosein/item-capture-app`** (nothing to change; it adds `webapp/` only). RBB007 approves and merges. Hosein deletes `app/capture-skeleton` and `scaffold/project-structure`, which this supersedes.
2. **PR #1 is re-scoped** (RBB007): keep `models.py` + `storage.py` changes (adding `include` and `captions`), `AI_INSTRUCTIONS.md`, tests; drop the Streamlit `app.py` rewrite and `.streamlit/`; delete `app.py` and the Streamlit requirements; rewrite README "Run it" and "The app" for Flask. Retitled "Shared model, AI agent instructions, docs for the Flask frame".
3. **Integration PR** (RBB007): `webapp/bridge.py`, `run.py`, the `try_module` wrapper, and the route changes in the table above with fallbacks. Hosein reviews since it touches `server.py`.
4. **Module PRs** land in any order after that. Each one replaces a fallback.

## What module authors need to know

Nothing new. The rules in `AI_INSTRUCTIONS.md` still hold exactly: one file, fixed signatures, `models.py` objects in and out, no UI code, env vars for keys, `NotImplementedError` for unfinished parts. If a module is done before step 3 lands, it is still mergeable; it just is not called until the route is wired.

## Open questions for Hosein

- OK to run the app from the repo root (`python run.py`) instead of `cd webapp && python server.py`?
- Keep the PIN login for the demo? (Fine either way; `SITESCRIBE_PIN` env var already exists.)
- Plan rendering: keep PDF.js in the browser, or switch to the PNGs from `plans.py` once that exists? Proposal: both, PNG preferred when present.
