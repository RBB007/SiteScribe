# SiteScribe: How to merge into `main`

**For:** tshoseints, allenmarden and hmmigdal
**Repo:** https://github.com/RBB007/SiteScribe

You three, plus RBB007, are the only people who can approve code going into `main`. Everyone else sends their code in as a pull request (PR), and one of you reviews and merges it.

**One rule GitHub enforces:** you can't approve your own PR. When *you* write code, one of the other mergers (RBB007, tshoseints, allenmarden, hmmigdal) has to approve it.

---

## Merging a teammate's pull request

1. Open https://github.com/RBB007/SiteScribe/pulls and click the PR.
2. **Check what it touches.** Click the **Files changed** tab.
   - It should only change that person's own module (for example `sitescribe/word_report.py`), plus `requirements.txt` if they added a package.
   - If it edits `sitescribe/models.py` or someone else's file, check with RBB007 before merging. Changes under `webapp/` need a review from tshoseints, who owns the web app.
   - Make sure there are no API keys, passwords, or large files (plans, videos, audio).
3. **Try it** (recommended):
   ```bash
   git fetch origin
   git checkout their-branch-name        # shown at the top of the PR
   pip install -r requirements.txt
   python run.py
   ```
   Open http://localhost:5000, enter the PIN, and check that the app still opens and their feature works. Then switch back with `git checkout main`.
4. **Approve.** On the **Files changed** tab, click **Review changes**, choose **Approve**, and click **Submit review**.
5. **Merge.** Go back to the **Conversation** tab, scroll down, and click **Merge pull request**, then **Confirm merge**.
6. Click **Delete branch** to keep the repo tidy.
7. Tell the team: "Merged X, pull `main`."

## Merging your own code

1. Work on a branch, never directly on `main`:
   ```bash
   git checkout main
   git pull
   git checkout -b yourname/what-you-did
   # ...make changes...
   git add <files>
   git commit -m "Describe the change"
   git push -u origin yourname/what-you-did
   ```
2. Open a pull request on GitHub (the yellow **Compare & pull request** banner appears after you push).
3. Ask one of the other mergers to approve it.
4. Once it's approved, click **Merge pull request** yourself.

## If someone sends you a file instead of a PR

```bash
git checkout main
git pull
git checkout -b add-teammate-module
# copy their file into the right place, e.g. sitescribe/voice.py
git add sitescribe/voice.py
git commit -m "Add voice module from <teammate>"
git push -u origin add-teammate-module
```

Then open a PR and have another merger approve it, as above.

## If GitHub says "This branch has conflicts"

This means two people changed the same lines. Click **Resolve conflicts** on the PR. GitHub shows both versions between `<<<<<<<` and `>>>>>>>` markers:

1. Keep the right code.
2. Delete the marker lines.
3. Click **Mark as resolved**, then **Commit merge**.

If you're not sure which version is right, ask the person who wrote it, or ask RBB007.

## If a merge breaks the app

Open the merged PR and click **Revert** near the bottom. This creates a new PR that undoes it. Approve and merge that PR, and `main` is back to working.

## What the merge rules protect

- `models.py` is the shared contract between everyone's code. Only change it with RBB007's agreement.
- Keep `main` runnable at all times, because that's what gets demoed.
- About an hour before judging, RBB007 freezes `main`. Don't merge anything after that unless RBB007 says so.
