# SiteScribe

**Walk the site with a phone, capture observations, get a finished site visit report at the end of the day.**

Built at the NCSEA Hackathon 2026.

## How it works

| Stage | What happens |
| --- | --- |
| **Before the visit** | Upload the plan set (required) and, optionally, the firm's Word report template. |
| **Capture** | Take a photo, describe it by voice or text, mark importance, add tags and an action item. |
| **Locate** | Tap the spot on the plan, or let GPS (or your voice: "grid C-4") place the pin; drag to adjust. |
| **Classify** | Every observation gets a severity: Info / Minor / Major / Critical / Safety. |
| **Generate** | AI transcribes voice notes, cleans up captions, and drafts the summary and action items. |
| **Export** | A Word report in your template, plus the plan set with a numbered, color-coded pin for every photo. |

**The report includes:** summary, plan sheets with color-coded pins, observations with photos and captions, action items, and a photo log.

Pin colors: Info blue · Minor green · Major orange · Critical red · Safety purple.

## Run it

```bash
git clone https://github.com/RBB007/SiteScribe.git
cd SiteScribe
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

Open http://localhost:5000 and enter the PIN (default `2424`; set `SITESCRIBE_PIN` to change it). Run it from the repo root, not from inside `webapp/`. For auto-reload and Flask's debug error pages while developing, set `FLASK_DEBUG=1`.

To use it on a phone, the camera and microphone need HTTPS, so a LAN address is not enough. Open a tunnel and use the URL it prints:

```bash
cloudflared tunnel --url http://localhost:5000
```

The tunnel URL is public, so run the app **without** `FLASK_DEBUG` when tunnelling (debug error pages show stack traces to anyone who opens them) and set `SITESCRIBE_PIN` to something other than the default.

There is also an always-on shared instance for the team; see [DEPLOY.md](DEPLOY.md).

API keys go in a `.env` file or environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`), never in code.

## Using an AI coding agent?

Give it [AI_INSTRUCTIONS.md](AI_INSTRUCTIONS.md). It explains the one rule that matters (keep the function signatures and the data model exactly as they are) so your code drops into the app without rework.

## The app (`webapp/`)

A Flask web app, phone-first. The landing page lists reports and opens one; the capture page is the screen you use on site:

```
<prev>  Item #  <next>
photo(s)                 take/select photo
<prev>  Photo #  <next>
location                 tap the spot on the plan (PDF or image)
description              typed, dictated (browser speech, no key) or recorded
importance flag          Info / Minor / Major / Critical / Safety
tags, include-in-report
```

Export gives a Word report of the included items, in the firm's template if one was uploaded for that report. Details of the data model, routes and config are in [webapp/README.md](webapp/README.md).

Today the routes do their work inline (Whisper call, plain python-docx report). The integration step wires each route to its `sitescribe/` module through a small adapter, `webapp/bridge.py`, keeping the inline code as the fallback, so a module that is not written yet never breaks the app. The route-by-route map is in [INTEGRATION_PLAN.md](INTEGRATION_PLAN.md).

## Code layout

The web app only calls functions in the `sitescribe/` package. Each module has its functions already defined with a docstring saying exactly what goes in and what comes out — fill in the body. Until a module is written the app falls back to its built-in behaviour instead of crashing, so the app runs from day one.

| File | Stage | What it does | Owner |
| --- | --- | --- | --- |
| `sitescribe/models.py` | all | Shared data: `Project`, `PlanSheet`, `Observation`, `PlanPin`, `Severity` | RBB007 |
| `sitescribe/storage.py` | all | Saves/loads a project folder | RBB007 |
| `sitescribe/plans.py` | before | Plan PDF → one image per sheet | |
| `sitescribe/photos.py` | on site | Read photo GPS/time; write caption/severity into the photo file | allenmarden |
| `sitescribe/voice.py` | on site | Voice memo → text; spoken location → pin | |
| `sitescribe/locate.py` | on site | GPS → pin on the plan | |
| `sitescribe/ai_writer.py` | after | AI summary, cleaned-up captions, action items | |
| `sitescribe/plan_markup.py` | after | Plan set PDF with color-coded numbered pins | |
| `sitescribe/word_report.py` | after | The Word report | |
| `webapp/server.py` | all | Flask routes, PIN login, storage, Word export fallback | tshoseints |
| `webapp/templates/` | all | Landing page and capture UI | tshoseints |
| `webapp/bridge.py` | all | JSON ⇄ `models.py` adapter (coming with the integration PR) | RBB007 |
| `run.py` | all | Starts the web app from the repo root | RBB007 |

## Team

| Name | GitHub | Working on |
| --- | --- | --- |
|  | [@RBB007](https://github.com/RBB007) | Repo manager, integration, `bridge.py` |
| Hosein Kerdar | [@tshoseints](https://github.com/tshoseints) | Merger, web app (`webapp/`) |
| Allen Marden | [@allenmarden](https://github.com/allenmarden) | Merger, `photos.py` |
| Heather Migdal | [@hmmigdal](https://github.com/hmmigdal) | Merger |
| Mark Rodriguez | [@Markr78-CT](https://github.com/Markr78-CT) |  |
| Sean Arbic (GFDS Engineers) | [@sfarbic](https://github.com/sfarbic) |  |
| Anthony Giammona | [@Nyaagwork](https://github.com/Nyaagwork) |  |
| Trevor Taylor | [@trevortaGIT13](https://github.com/trevortaGIT13) |  |
| David Goldson | [@DavidG66-max](https://github.com/DavidG66-max) |  |
| Pengyu Chen | [@GFDS-PC](https://github.com/GFDS-PC) |  |

## Demo

_Screenshots, demo video, and sample report go here before judging._

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Short version: write your module, send it in, RBB007, tshoseints, allenmarden or hmmigdal merges.
