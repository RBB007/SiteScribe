# Offline sync browser test

Drives the real capture pages in Chromium: installs the service worker, goes
offline, creates items, types descriptions and attaches photos, reloads while
offline, reconnects, and checks the server ended up with exactly one copy of
everything. Then it checks rejected changes (404), an expired session (401), a
server outage (503), and that report export is blocked while changes are pending.

```bash
python tests/browser/harness.py &          # local server on :5055, SQLite, fake auth
NODE_PATH=$(npm root -g) node tests/browser/offline_sync.js
```

Needs Node and Playwright with Chromium. Restart the harness before each run;
it keeps its data in memory for the life of the process. The script prints
PASS/FAIL per check and exits non-zero on any failure.

This does not replace a check on real phones (iOS Safari storage and install
behaviour differ from desktop Chromium). See docs/pwa.md.
