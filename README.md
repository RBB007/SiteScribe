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
| `app.py` | all | Phone-friendly Streamlit UI | |

## Team

| Name | GitHub | Working on |
| --- | --- | --- |
| | [@RBB007](https://github.com/RBB007) | Repo manager, integration |
| | [@tshoseints](https://github.com/tshoseints) | Merger |
| | [@allenmarden](https://github.com/allenmarden) | Merger |
| | [@Markr78-CT](https://github.com/Markr78-CT) | |
| | [@sfarbic](https://github.com/sfarbic) | |
| | [@hmmigdal](https://github.com/hmmigdal) | Merger |
| | [@trevortaGIT13](https://github.com/trevortaGIT13) | |

## Demo

_Screenshots, demo video, and sample report go here before judging._

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Short version: write your module, send it in, RBB007, tshoseints, allenmarden or hmmigdal merges.
