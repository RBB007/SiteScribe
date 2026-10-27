# Contributing to SiteScribe

**Only RBB007, tshoseints and allenmarden merge into `main`.** You write your module and send it in; they make everyone's code fit together and merge it. Mergers: see [MERGING.md](MERGING.md).

## 1. Pick your module

Each file in `sitescribe/` (and `app.py`) already has its functions written out with a docstring saying what goes in and what comes out. Put your name in the **Owner** line at the top of your file and fill in the function bodies.

**Keep the function names, inputs and outputs exactly as they are.** That's what lets RBB007 drop your code in without rewriting it. You can add as many helper functions as you like inside your file.

## 2. Use the shared data model

All data moves around as the objects in `sitescribe/models.py` (`Project`, `PlanSheet`, `Observation`, `PlanPin`, `Severity`). Read that file first.

**Don't edit `models.py`.** If you need a new field, message RBB007 and it gets added for everyone.

## 3. Send your code in

Pick whichever is easier for you:

**Option A — push a branch (preferred)**

```bash
git checkout main
git pull
git checkout -b yourname/module-name          # e.g. allen/word-report
# ...write code...
git add sitescribe/word_report.py requirements.txt
git commit -m "Word report: header, observations, photo log"
git push -u origin allen/word-report
```

Then open a pull request on GitHub into `main` and tell RBB007. Don't merge it yourself.

**Option B — send the file**

Send RBB007 your finished `.py` file(s) and any packages you added. RBB007 commits it for you.

## 4. Rules that keep integration painless

- **Stay in your own file.** If you need a change in someone else's module, ask them or RBB007.
- **Add packages to `requirements.txt`** in the same change, with a comment naming your module.
- **Test your function on its own** before sending it, e.g. in a scratch script or `tests/`.
- **No API keys in code.** Read them from environment variables. The repo is public and bots scrape leaked keys within minutes.
- **No big files.** Don't commit plan sets, videos, audio, or photo dumps. Project data lives in `projects/`, which git ignores.
- **Send early, send often.** A working half-feature sent at hour 4 is easier to integrate than a perfect one sent at hour 20.
