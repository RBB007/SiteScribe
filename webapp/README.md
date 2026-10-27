# SiteScribe — item capture web app (Flask)

A phone-first capture UI built to the **App Workflow** slide and the notebook
sketch: an Item navigator over a photo, a Photo navigator under it.

> **Note for the team:** `main` is a Streamlit app. This is a standalone Flask
> implementation of the capture dialog. It is NOT a drop-in replacement — it is
> here so the UI behaviour, the data model and the Word export are visible and
> reusable. Take the parts that help.

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

## Report template (formatting only)

Upload your firm's Word template with the **Template** button and the export
inherits its styles, fonts, margins, header/footer and logo. **No AI involved** —
python-docx opens the template as the base document and writes content using its
named styles (`Title`, `Heading 1`, `Body Text`, `Caption`), falling back to
`Normal` for any the template lacks.

You can upload a filled-in past report, not just a blank template: the body
content is stripped while styles, section setup and the letterhead are kept.

A missing or corrupt template never blocks a report — it logs and falls back to
the plain format.

| Route | Does |
|---|---|
| `GET /api/template` | the record, or null |
| `POST /api/template` | multipart `template` (.docx only) |
| `DELETE /api/template` | revert to plain formatting |

## Data model

```
Item   I-001          include · description · importance · tags · location? · audio?
  └ Photo  I-001-P-01   caption
  └ Photo  I-001-P-02
  └ Audio  I-001-A-01   kept whether or not it was transcribed
Item   I-002
```

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

## Severity

`Info · Minor · Major · Critical · Safety` — from the Summary slide.

## API

| Route | Does |
|---|---|
| `GET /api/visit` | all items + plans |
| `POST /api/item` | new item |
| `PATCH /api/item/<id>` | description, importance, tags, include, location |
| `DELETE /api/item/<id>` | remove item + its uploads |
| `POST /api/item/<id>/photo` | multipart `photo` |
| `PATCH/DELETE /api/item/<id>/photo/<pid>` | caption / remove |
| `POST /api/item/<id>/audio` | multipart `audio` + `transcribe=true\|false`; always stores the clip, returns it; fills description **only if empty** |
| `DELETE /api/item/<id>/audio/<clip_id>` | delete one recording |
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
