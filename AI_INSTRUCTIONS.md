# SiteScribe: instructions for your AI coding agent

Copy everything below the line into Claude Code, Cursor, ChatGPT, Copilot or whatever you use, then tell it which module you own. Your code only has to do one thing to be merged: **fit the frame without changes to anything else.** How you build it inside your file is up to you.

Repo: https://github.com/RBB007/SiteScribe · Questions: RBB007

---

## Paste this into your AI agent

You are helping me build **one module** of SiteScribe, a hackathon app for structural engineers. The engineer walks a job site with a phone, takes photos, describes them by voice or text, flags importance, pins them on the plan, and the app writes a Word site-visit report. The app is Python + Streamlit. Several people write modules in parallel and one person (RBB007) merges them, so **compatibility matters more than cleverness.**

Repo: https://github.com/RBB007/SiteScribe
My module: `sitescribe/<MODULE>.py` (I will tell you which one.)

### The contract

1. **Stay inside your one file.** Edit only `sitescribe/<MODULE>.py`, plus `requirements.txt` (add a line per package you need, with a comment naming the module) and an optional `tests/test_<MODULE>.py`. Do not touch `app.py`, `sitescribe/models.py`, or any other module. If you think another file needs a change, write down what and why so I can ask RBB007.
2. **Keep every function signature exactly as it is in the file.** Same function names, same parameter names and order, same return type. The docstring on each function says what goes in and what comes out; that is the spec. You may add as many private helpers (`_name`) as you like. You may not rename, remove, or add required parameters.
3. **Use the shared data model as-is.** All data moves around as the dataclasses in `sitescribe/models.py`: `Project`, `PlanSheet`, `Observation`, `PlanPin`, `GeoPoint`, `Severity`, plus `SEVERITY_COLORS`. Read that file first. Import from `.models`. Never add fields to those classes or define your own copies of them. If a field you need is missing, say so in a comment and work around it.
4. **No UI in the module.** Do not import `streamlit`. No `print`, no `input()`. Functions take values and return values. Use `logging` if you want to log.
5. **Files go where you are told.** When a function receives an output path or directory, write there and return that path. Never write into the repo folder, the current directory, or a temp file that outlives the call. Accept and return `pathlib.Path`, not strings.
6. **Secrets come from environment variables only.** `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, etc. via `os.environ`. Never put a key in code, comments, tests, or committed `.env` files. The repo is public.
7. **Fail loudly and clearly.** If a required package or key is missing, raise an exception with a one-line message that says what to install or set. Do not catch-and-ignore errors. The app shows exceptions to the user and keeps running; a silent wrong result is worse than an error.
8. **Pure and stateless.** No module-level state that changes between calls, no caching to disk unless the docstring asks for it, no threads or background work. Each call should give the same answer for the same input.
9. **Work with what the app provides.** Photos are JPEG/PNG/HEIC from phones. Voice notes are WAV from the browser microphone (also accept m4a/webm). Plan sets are multi-page PDFs. Plan pin coordinates are fractions 0.0 to 1.0 of the sheet, origin top-left.
10. **Python 3.11+, type hints on every public function, `from __future__ import annotations` at the top.** Keep dependencies common and pip-installable on Mac and Windows (no system packages, no GPU requirements). Prefer well-known libraries (Pillow, PyMuPDF, python-docx, piexif, anthropic, openai).
11. **Test it on its own.** Give me a small `tests/test_<MODULE>.py` or a scratch script that calls each function with sample input and checks the output, so I can prove it works before it is merged. If a test needs an API key, skip it when the key is not set (`pytest.skip`).
12. **Leave the stubs for anything you do not finish.** An unfinished function should still `raise NotImplementedError`; the app then shows "not built yet" instead of crashing. A half-finished module that imports cleanly is mergeable; one that errors on import is not.
13. **Put your name in the `Owner:` line** at the top of the module docstring.

### Quick reference: the data model

```
Project         name, site_address, engineer, visit_date,
                plans: [PlanSheet], template_path, observations: [Observation],
                summary, report_options: dict
PlanSheet       name, source_pdf, page_index, image_path, width_px, height_px,
                calibration: [((px_x, px_y), GeoPoint)], id
Observation     photo_path (main photo), photos: [Path], audio_path,
                description, severity: Severity, tags: [str], action_item,
                pin: PlanPin | None, gps: GeoPoint | None, taken_at, number, id
PlanPin         sheet_id, x (0-1), y (0-1), source: "manual" | "gps" | "voice"
GeoPoint        lat, lon
Severity        Info, Minor, Major, Critical, Safety   (SEVERITY_COLORS has the hex color)
```

### When you are done

Tell me:
- which packages you added to `requirements.txt`,
- which environment variables the module reads,
- how to run your test,
- anything in the contract you could not keep and why.

---

## Sending your code in (for the human)

Preferred: branch + pull request.

```bash
git checkout main
git pull
git checkout -b yourname/module-name
git add sitescribe/<MODULE>.py requirements.txt tests/test_<MODULE>.py
git commit -m "<MODULE>: what it does"
git push -u origin yourname/module-name
```

Then open the pull request on GitHub and tell RBB007. If git is a hassle, send RBB007 the `.py` file and your `requirements.txt` lines instead.

Full rules: [CONTRIBUTING.md](CONTRIBUTING.md). For mergers: [MERGING.md](MERGING.md).

## Pre-merge checklist (RBB007 / mergers)

- [ ] Only `sitescribe/<MODULE>.py`, `requirements.txt`, `tests/` changed
- [ ] Function names, parameters and return types unchanged
- [ ] No `import streamlit` in the module, no `print`
- [ ] No API keys, no large files
- [ ] `pip install -r requirements.txt` works
- [ ] `pytest` passes (or skips cleanly without keys)
- [ ] `streamlit run app.py` still opens and the feature shows up
