# SiteScribe

**Structural observation reports, pinned to the plan.**

SiteScribe turns field observations — photos, videos, audio memos, and text notes — into a structured site observation report. Every observation is linked to a location on a plan sheet, so the report reads like a marked-up drawing instead of a pile of attachments.

Built at the NCSEA Hackathon 2026.

## How it works

```
 photos / video / audio / text
              │
              ▼
   ingest/  ──►  Observation  ◄──  plan/  (x, y location on a plan sheet)
                     │
                     ▼
                 report/  ──►  observation report (PDF / HTML)
```

Everything flows through one shared data model, `Observation`, defined in [`src/sitescribe/models.py`](src/sitescribe/models.py). Each module reads or produces `Observation` objects, which is what lets the pieces be built separately and stitched together.

## Repo layout

| Path | Owner | What goes here |
| --- | --- | --- |
| `src/sitescribe/models.py` | Integration lead | Shared `Observation` model. Change only via PR + discussion. |
| `src/sitescribe/ingest/` | Ingest team | Photo, video, audio (transcription), and text intake |
| `src/sitescribe/plan/` | Plan team | Loading plan sheets, pinning observations to x/y locations |
| `src/sitescribe/report/` | Report team | Generating the final observation report |
| `tests/` | Everyone | Tests for your module |
| `notebooks/` | Everyone | Experiments and prototypes |
| `data/sample_plans/` | Everyone | Small sample plan sheets for demos (no large media) |

## Getting started

```bash
git clone https://github.com/RBB007/SiteScribe.git
cd SiteScribe
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Team

| Name | GitHub | Role |
| --- | --- | --- |
| | [@RBB007](https://github.com/RBB007) | Integration lead / repo owner |
| | | |

## Demo

_Screenshots, demo video link, and how to run the demo go here before judging._

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
