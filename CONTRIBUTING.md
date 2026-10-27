# Contributing to SiteScribe

One person (the integration lead) merges everything into `main`. Everyone else works on branches and opens pull requests. Nobody pushes directly to `main`.

## Workflow

1. **Get the latest code**
   ```bash
   git checkout main
   git pull
   ```
2. **Make a branch** named for your module and feature:
   ```bash
   git checkout -b ingest/audio-transcription
   ```
   Prefixes: `ingest/`, `plan/`, `report/`, `app/`, `docs/`, `fix/`.
3. **Commit often** with clear messages:
   ```bash
   git add .
   git commit -m "Add Whisper transcription for audio memos"
   ```
4. **Push your branch**:
   ```bash
   git push -u origin ingest/audio-transcription
   ```
5. **Open a pull request** on GitHub into `main`. Fill in the template. The integration lead reviews and merges.
6. **Before starting the next piece**, go back to step 1 so you're building on the latest `main`.

## Rules that keep merging painless

- **Stay in your folder.** Work inside your module (`ingest/`, `plan/`, or `report/`). If you need to touch another team's folder, say so in the PR.
- **Talk in `Observation` objects.** Your module's inputs and outputs should be `Observation` objects from `src/sitescribe/models.py`. Need a new field? Open an issue or ask the integration lead — don't edit `models.py` in a feature PR.
- **Small PRs, early.** A working half-feature merged at hour 6 beats a perfect feature that conflicts at hour 23.
- **No big media files.** Don't commit videos, audio, or large photo sets. Use a few small samples in `data/sample_plans/` or share large files through the team drive.
- **No secrets.** API keys go in a local `.env` file (already ignored by git), never in code.
- **Add dependencies to `requirements.txt`** in the same PR that needs them.

## Getting access

Send your GitHub username to the integration lead. You'll get an invite email from GitHub — accept it, then clone the repo.
