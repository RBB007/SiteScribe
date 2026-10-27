# SiteScribe — item capture web app (Flask)

A phone-first capture UI built to the **App Workflow** slide and the notebook
sketch: an Item navigator over a photo, a Photo navigator under it.

> **Note for the team:** this Flask app is the main SiteScribe app. The
> Streamlit app that used to live on `main` is retired. The `sitescribe/`
> modules plug in behind these routes; see [INTEGRATION_PLAN.md](../INTEGRATION_PLAN.md).
> From the repo root, `python run.py` starts this same server.

## Live

**https://planning-matrix-bacteria-occupation.trycloudflare.com** (PIN: ask the team)

Merges to the tracked branch deploy themselves within 2 minutes — see
[DEPLOY.md](../DEPLOY.md). You do not need server access to change it.

## Run locally

```bash
pip install -r requirements.txt
python server.py            # http://localhost:5000   PIN 2424
```

`localhost` is a secure context, so camera and mic work with no HTTPS.
For a phone you need a public HTTPS URL:

```bash
cloudflared tunnel --url http://localhost:5000
```

Plain HTTP on a LAN IP **silently** blocks the microphone.

## Reports (projects)

The landing page at `/` lists every report and creates new ones. Opening one
stores it in the session and sends you to `/capture`.

```
data/projects.json            the index
data/P-001/visit.json         that report's items + plans
uploads/P-001/I-001/...       its photos and audio
uploads/P-001/plans/...
```

Leaving the name blank auto-names it `Site Visit <YYYY-MM-DD HH:MM>` (UTC).
Reports are listed newest-edited first with item / photo / included counts.

A legacy single-visit `data/visit.json` is migrated into `P-001` on first
start — files moved, stored URLs re-prefixed, original mtime preserved. It is
idempotent.

## Word export

`GET /api/export/docx` converts the visit with `webapp/bridge.py` (`to_project`)
and hands it to `sitescribe.word_report.build_report`: header, summary, pinned
plan sheets, one ITEM block per included entry with its photo and caption,
action items, photo log. Only plans with a pin are rendered. If the module
raises, the traceback is logged to stderr and the built-in python-docx report
below ships instead, so the user always gets a file; the response then carries
an `X-SiteScribe-Report-Notice` header saying why.

The **Export** button uses two requests so a phone sees progress and a real
error instead of a blank tab: `POST /api/export/build` builds the bundle zip
(report, EXIF-tagged photos, pinned plan pages), keeps it as
`data/<pid>/export.zip` and answers `{url, name, bytes, seconds, notice}`; the
page then navigates to `GET /api/export/download`, which serves that file.
`GET /api/export/bundle` still builds and streams the same zip in one request.
The report is built outside the global lock, so a long export does not stall
other requests.

Keeping the export small enough to build and download on site:

- The visit is converted and its plan pages rendered **once** per export
  (`webapp/export_bundle.py` takes the same `Project` the report was built
  from) and the zip is written straight to disk, not held in memory.
- Photos in the zip are downscaled to 2560 px on the long side (JPEG q88,
  HEIC converted to JPEG) with the entry written into their EXIF; a
  3-12 MB phone original becomes well under 1 MB. The originals stay in
  `uploads/`. Photos in the Word file are 1600 px, plan sheets 2400 px as
  256-colour PNGs.
- Under gunicorn use the repo's `gunicorn.conf.py` (`timeout = 300`): the
  default 30 s kills the worker mid-build on a big visit and the phone sees
  "Export failed: Bad Gateway".

## Report template

Upload your firm's Word template with the **Template** button. **No AI is
involved anywhere in the export**: every word in the report is either typed or
dictated in the app, or comes from the template file itself. The upload reply
(and the template bar) says which of three ways `sitescribe/word_report.py`
will use the file (`layout`):

- **`report`** — a past report, e.g. a GFDS *Structural Observation Record*
  (anything with `ITEM n` paragraphs; a form with the headings but no items
  is `styles`, since the ITEM blocks are cloned from those paragraphs).
  The document is kept as the form it is: title, header table, section labels
  and the firm's closing paragraphs stay. The date, project name and the
  other header fields are filled from the app and left **blank** when the app
  has no value (never the old report's job number or observer); the old
  report's items, photos, prose and "Previous Action Items" are removed; this
  visit's `ITEM` blocks are cloned from the template's own paragraphs (same
  font, indent and tab stops), followed by the pinned plan sheets. Dates in
  the running header become the visit date and the header's project line
  becomes the project name.
- **`tagged`** — a template with `{{ }}` / `{%p %}` tags, rendered with
  docxtpl; the template decides the layout.
- **`styles`** — any other `.docx` (a letterhead, a blank shell): the body is
  replaced by the app's own layout using the template's page setup, header,
  footer and styles.

A missing or corrupt template never blocks a report — it logs and falls back to
the plain format, and the response carries a notice saying so.

| Route | Does |
|---|---|
| `GET /api/template` | the record, or null |
| `POST /api/template` | multipart `template` (.docx only) |
| `DELETE /api/template` | revert to plain formatting |

## Data model

```
Item   001                     a numbering group only
  └ Photo 001_01   THE INCIDENT: photo? · description · location ·
  │                importance · tags · include · audio_clips[]
  └ Photo 001_02
  └ Audio 001_01_A01
Item   002
```

999 items x 99 photos per item. **The incident is the photo entry, not the
item** - an item is just a container. A photo entry may have no image yet
(`filename: null`), so a voice note or a plan pin can be recorded before the
picture is taken; the export skips the image for those.

Photo IDs are scoped to their item, so `I-001-P-02` identifies both at once —
useful when embedding the ID into the photo and when placing it in the report.

`location` is `{plan_id, page, x, y}` where **x and y are normalized 0.0–1.0
fractions, never pixels**. A marker placed on a phone then renders correctly at
any other size in the Word report.

## Voice to text

Two independent paths, so the app never depends on a paid key:

1. **Dictate** (primary) — Web Speech API, runs in the browser, **free, no key**.
   Works in Chrome/Android and Safari/iOS 14.5+. Live interim text appears as you
   speak; only finalized text is persisted. Needs HTTPS, which the tunnel provides.
2. **Record audio** (optional) — uploads and **keeps** the clip on the server.
   A per-item checkbox decides whether it is also transcribed:
   - unchecked (default) → audio is stored and nothing is sent anywhere
   - checked → Whisper transcribes it, if `OPENAI_API_KEY` is set
     (~$0.006/min, noticeably better on structural jargon)

   Every recording is kept — `I-001-A-01`, `I-001-A-02`, … — playable inline and
   individually deletable. Useful when you would rather re-listen on site than
   trust a transcript.

If neither is available, the phone keyboard's own mic key dictates into the
description box with no code at all.

## Adding a photo

`POST /api/item/<id>/photo` with `inherit`:

- `keep` - copies `description`, `location`, `importance` and `tags` from the
  previous entry. The photo and the audio are never copied.
- `clear` (or `new`) - a blank entry.

An upload should send `photo_id` naming the entry it belongs to. Without it the
server picks the **newest** imageless entry.

## Severity

`Info · Minor · Major · Critical · Safety` — from the Summary slide.

## API

| Route | Does |
|---|---|
| `GET /api/visit` | all items + plans |
| `POST /api/item` | new item |
| `PATCH /api/item/<id>` | nothing editable (the fields moved to the entry) |
| `DELETE /api/item/<id>` | remove item + its uploads |
| `POST /api/item/<id>/photo` | multipart `photo` (+ `photo_id` to name the target entry), or `inherit=keep\|clear` to add an entry |
| `PATCH /api/item/<id>/photo/<pid>` | `caption, description, importance, tags, include, location` |
| `DELETE /api/item/<id>/photo/<pid>` | remove the entry and its files |
| `POST /api/item/<id>/photo/<pid>/audio` | multipart `audio` + `transcribe=true\|false` |
| `DELETE /api/item/<id>/photo/<pid>/audio/<clip_id>` | remove one recording |
| `POST /api/plan` | multipart `plan` (pdf/image) |
| `GET /api/export/docx` | Word report of **included** items only |
| `GET /health` | public, no PIN |

### Reports

| Route | Does |
|---|---|
| `GET /` | landing page |
| `GET /capture` | the capture UI (302 to `/` if no report is open) |
| `GET /api/projects` | all reports + `current` |
| `POST /api/projects` | create (blank name → auto date/time name) |
| `POST /api/projects/<pid>/open` | open it for this session |
| `PATCH /api/projects/<pid>` | rename |
| `DELETE /api/projects/<pid>` | delete it and all its files |
| `POST /api/projects/close` | close without opening another |

Data routes return **409 `no project open`** when none is selected; the UI
redirects to `/` on a 409.

## Config

| Env var | Default |
|---|---|
| `SITESCRIBE_PIN` | `2424` |
| `SITESCRIBE_SECRET` | random per start |
| `OPENAI_API_KEY` | optional. Unset → the **Dictate** button still works (browser speech recognition, free); only the server-side Whisper transcription of recorded audio is skipped |

**Never commit a key.** Put it in a `.env` on the server only.

## Notes

- `data/visit.json` writes are atomic (temp + rename) — an interrupted save
  cannot corrupt the visit.
- Transcription runs outside the write lock, so a slow Whisper call does not
  block other requests.
- Uploads are `secure_filename`'d and prefixed with the photo id.
