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
Item   I-002
```

Photo IDs are scoped to their item, so `I-001-P-02` identifies both at once —
useful when embedding the ID into the photo and when placing it in the report.

`location` is `{plan_id, page, x, y}` where **x and y are normalized 0.0–1.0
fractions, never pixels**. A marker placed on a phone then renders correctly at
any other size in the Word report.

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
| `POST /api/item/<id>/audio` | multipart `audio` → transcribes, fills description **only if empty** |
| `POST /api/plan` | multipart `plan` (pdf/image) |
| `GET /api/export/docx` | Word report of **included** items only |
| `GET /health` | public, no PIN |

## Config

| Env var | Default |
|---|---|
| `SITESCRIBE_PIN` | `2424` |
| `SITESCRIBE_SECRET` | random per start |
| `OPENAI_API_KEY` | unset → audio saves, transcript is empty, UI tells the user to type |

**Never commit a key.** Put it in a `.env` on the server only.

## Notes

- `data/visit.json` writes are atomic (temp + rename) — an interrupted save
  cannot corrupt the visit.
- Transcription runs outside the write lock, so a slow Whisper call does not
  block other requests.
- Uploads are `secure_filename`'d and prefixed with the photo id.
