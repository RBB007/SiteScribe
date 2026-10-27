# SiteScribe — item capture web app (Flask)

A phone-first capture UI built to the **App Workflow** slide and the notebook
sketch: an Item navigator over a photo, a Photo navigator under it.

> **Note for the team:** `main` is a Streamlit app. This is a standalone Flask
> implementation of the capture dialog. It is NOT a drop-in replacement — it is
> here so the UI behaviour, the data model and the Word export are visible and
> reusable. Take the parts that help.

## Run

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
