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
streamlit run app.py
```

To use it on a phone, connect the phone to the same Wi-Fi and open the **Network URL** Streamlit prints.

API keys go in a `.env` file or environment variables (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`), never in code.

## Using an AI coding agent?

Give it [AI_INSTRUCTIONS.md](AI_INSTRUCTIONS.md). It explains the one rule that matters (keep the function signatures and the data model exactly as they are) so your code drops into the app without rework.

## The app (`app.py`)

Three screens, picked at the top: **Setup**, **Capture**, **Report**.

Capture is the phone screen. Big buttons start an entry (take/select photo, pick a location on the plan, or a text/voice note), then the entry editor shows:

```
<prev>  Item #  <next>
photo(s)                 take/select photo button if none
<prev>  Photo #  <next>
location                 pick-on-plan button if none
description              typed, and/or a voice note
importance flag          Info / Minor / Major / Critical / Safety
tags, action item
```

Report has the AI draft button, the summary, an export options dialog, and the export button. The Word report and marked-up plan set come from `word_report.py` and `plan_markup.py`; photo info is embedded by `photos.py`.

Every module call goes through `try_step()`, so a module that isn't written yet shows "not built yet" instead of breaking the app. A sample grid plan sheet is built in (Setup tab) so the location picker can be tried before `plans.py` exists.

## Code layout

The app (`app.py`) only calls functions in the `sitescribe/` package. Each module has its functions already defined with a docstring saying exactly what goes in and what comes out — fill in the body. Until a module is written the app says "not built yet" instead of crashing, so the app runs from day one.

| File | Stage | What it does | Owner |
| --- | --- | --- | --- |
| `sitescribe/models.py` | all | Shared data: `Project`, `PlanSheet`, `Observation`, `PlanPin`, `Severity` | RBB007 |
| `sitescribe/storage.py` | all | Saves/loads a project folder | RBB007 |
| `sitescribe/plans.py` | before | Plan PDF → one image per sheet | |
| `sitescribe/photos.py` | on site | Read photo GPS/time; write caption/severity into the photo file | |
| `sitescribe/voice.py` | on site | Voice memo → text; spoken location → pin | |
| `sitescribe/locate.py` | on site | GPS → pin on the plan | |
| `sitescribe/ai_writer.py` | after | AI summary, cleaned-up captions, action items | |
| `sitescribe/plan_markup.py` | after | Plan set PDF with color-coded numbered pins | |
| `sitescribe/word_report.py` | after | The Word report | |
| `app.py` | all | Phone-friendly Streamlit UI | RBB007 |

## Team

| Name | GitHub | Working on |
| --- | --- | --- |
| | [@RBB007](https://github.com/RBB007) | Repo manager, integration, app UI |
| | [@tshoseints](https://github.com/tshoseints) | Merger |
| | [@allenmarden](https://github.com/allenmarden) | Merger |
| | [@Markr78-CT](https://github.com/Markr78-CT) | |
| | [@sfarbic](https://github.com/sfarbic) | |
| | [@hmmigdal](https://github.com/hmmigdal) | |
| | [@trevortaGIT13](https://github.com/trevortaGIT13) | |

## Demo

_Screenshots, demo video, and sample report go here before judging._

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Short version: write your module, send it in, RBB007, tshoseints or allenmarden merges.
