# Live app, and how to change it

## The running app

**https://planning-matrix-bacteria-occupation.trycloudflare.com**

PIN: ask in the team deck or at table 24 — deliberately not written here, because
this repo is public.

It is always on. It survives laptops closing and reboots.

## How to change it — you never need server access

```
  your branch  ──PR──▶  hosein/item-capture-app  ──≤2 min──▶  live URL
```

1. Branch, change code under `webapp/`, push, open a PR (see `MERGING.md`)
2. A code owner approves and merges
3. **The server pulls and restarts itself within 2 minutes.** Nothing else to do.

No SSH keys, no credentials, no deploy step. If your change is merged and the
site has not changed after ~2 minutes, it failed a check — see below.

## Deploy safety

Before anything is swapped in, the deploy script:

- `git fetch` + hard checkout of the tracked branch, so the repo is the single
  source of truth (do not hand-edit files on the server; they get overwritten)
- **syntax-checks `webapp/server.py`** and refuses to deploy if it fails, so a
  broken commit cannot take the demo down
- installs `webapp/requirements.txt` as an unprivileged user
- restarts the service and reports whether it came back up

Log: `/opt/sitescribe/deploy.log` — every run appends `deployed <sha>`,
`no change`, or `SYNTAX ERROR in <sha> - not deploying`.

## Export timeouts

Building an export renders every pinned plan page and re-encodes every photo,
which takes a minute or more on a big visit. Gunicorn kills a worker after 30 s
by default, and the phone then sees "Export failed: Bad Gateway". The repo's
`gunicorn.conf.py` sets `timeout = 300` (and 4 threads, so an export does not
stall other phones); gunicorn reads it on its own when started from the repo
root, otherwise start it with `-c /opt/sitescribe/app/gunicorn.conf.py` or
`--timeout 300`.

## What is NOT in the repo

`data/` and `uploads/` live outside the repo on the server and are never touched
by a deploy. Your reports, photos, audio and plans survive every deploy.

API keys go in `/opt/sitescribe/.env` on the server only. **Never commit a key** —
this repo is public.

## If the site breaks after a merge

Revert the PR on GitHub (there is a **Revert** button at the bottom of a merged
PR). The next deploy cycle picks it up within 2 minutes.

## Notes

- The tracked branch is `hosein/item-capture-app` until PR #5 merges, then it
  switches to `main`.
- The URL is a Cloudflare quick tunnel, so the hostname changes if the tunnel
  service restarts. Current one is always recoverable from the server with:
  `grep -ohE 'https://[a-z0-9-]+\.trycloudflare\.com' /opt/sitescribe/tunnel.log | tail -1`
- The app runs as an unprivileged `sitescribe` user with `ProtectSystem=strict`,
  so merged code cannot read anything else on that machine.
