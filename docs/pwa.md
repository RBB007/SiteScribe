# Installable app and offline capture

The cloud app is a Progressive Web App (PWA). Field staff can install it to their phone's home screen and keep capturing observations when the connection drops.

## Components

| Piece | File | Notes |
| --- | --- | --- |
| Manifest | `webapp/static/manifest.webmanifest` | Name "MKA Site Visit Buddy", `display: standalone`, scope `/`, one SVG icon |
| Service worker | `webapp/static/service-worker.js` | Served at `/service-worker.js` with `Service-Worker-Allowed: /` and `Cache-Control: no-cache` (`webapp/cloud_app.py`) |
| Registration | `webapp/static/cloud_pwa.js` | Included on the dashboard, visit capture, visit overview, and admin pages. It also shows offline and sync messages. |
| Offline store | `webapp/static/offline.js` | IndexedDB holds a cached copy of each visit (`visit:<id>`) and a queue of pending write requests |

## What works offline

- Pages you have opened while online load from the cache. Static assets are pre-cached on install.
- A visit you have opened before loads from its cached copy.
- Edits to existing observations and photo/audio uploads to existing observations are queued. They are replayed in order when the device comes back online or the app returns to the foreground.

## What requires a connection

- Signing in and first opening of any page or visit.
- Creating or deleting items, and creating observations.
- Report generation, exports, and admin settings.
- Viewing files stored in the cloud. `/api/`, `/auth/`, and `/uploads/` responses are never cached by the service worker, so private data and signed URLs are not written to the cache.

## Known limitations

- **A rejected queued request blocks the queue.** If a replayed request gets a 4xx response (for example 401 after the session expires, or 404 because the item was deleted), `flush()` stops and leaves that job at the head of the queue. Every later change then stays pending. Users will see "N change(s) saved offline" indefinitely. Needs a fix (drop or park the failing job and tell the user) before relying on offline capture in the field.
- **Icons.** The only icon is an SVG. iOS ignores SVG for `apple-touch-icon` and uses a screenshot instead. Some Android/Chrome versions want PNG icons at 192 px and 512 px before they offer installation. Adding PNG icons is a low-risk fix.
- **Cache version is manual.** Bump `CACHE` in `service-worker.js` when the pre-cached file list changes. Static files are served cache-first and refreshed in the background, so a deploy reaches users on their second load.
- Queued data lives in the browser's IndexedDB on that device only. Clearing site data or uninstalling the app before it syncs loses those changes.

## Tests

`tests/test_cloud_pwa.py` checks the manifest fields, that the cloud pages link the manifest and register the worker, that `/api/` and `/auth/` are excluded from caching, and the service-worker route headers. Install prompts and offline replay are not covered by automated tests. Check them manually on a real iPhone and Android device: install the app, open a visit, go to airplane mode, edit and add a photo, reconnect, and confirm the changes sync.
