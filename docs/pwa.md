# Installable app and offline capture

The cloud app is a Progressive Web App (PWA). Field staff install it to the home screen and keep capturing observations with no connection. Everything captured offline is stored on the phone and synced, in order, when a connection returns.

## Components

| Piece | File | Notes |
| --- | --- | --- |
| Manifest | `webapp/static/manifest.webmanifest` | Name "MKA Site Visit Buddy", `display: standalone`, scope `/`, one SVG icon |
| Service worker | `webapp/static/service-worker.js` | Served at `/service-worker.js` with `Service-Worker-Allowed: /` and `Cache-Control: no-cache` (`webapp/cloud_app.py`). Caches pages and static files, never `/api/`, `/auth/` or `/uploads/`. |
| Offline queue | `webapp/static/offline.js` | IndexedDB on the phone: a copy of each opened visit, the queue of unsent changes, and changes the server rejected |
| Offline visit data | `webapp/static/cloud_sync.js` | Creates items and observations locally and decides whether to show the server's copy or the phone's copy |
| Status messages | `webapp/static/cloud_pwa.js` | Service worker registration and the sync banner in `#message` |

## What works offline

After a visit has been opened once while connected:

- Open the visit overview and the capture page, including items created offline.
- **Create new items.** Each gets its observation automatically. The item number shown is provisional; the server assigns the final number when it syncs, in sync order.
- Edit description, severity, tags, and include-in-report.
- Attach photos and record audio. Queued photos stay visible after a reload.

## Sync rules

1. **IDs come from the phone.** Items and observations get a UUID when they are created on the phone. The server stores that ID, and a replayed create with the same ID returns the existing record (`200`) instead of making a second one. A replayed upload of the same file (same SHA-256 and kind) to the same observation returns the existing file. A request that reached the server but whose response was lost therefore never duplicates anything.
2. **Order is preserved.** Changes replay oldest first. While anything is queued, new changes join the end of the queue, even when online, so an edit never reaches the server before the item it belongs to.
3. **Each failure is sorted:**

   | Response | What happens |
   | --- | --- |
   | No network, `408`, `425`, `429`, `5xx` | Stop and retry after 5 s, doubling to a 5 min maximum. A live request that hits a server error is queued, not lost. |
   | `401`, `403`, or a redirect to the login page | Pause the queue and show "Sign in again". Nothing is discarded. Syncing resumes on the next page load or when the app returns to the foreground. |
   | Any other `4xx` (e.g. `404` after the item was deleted or the visit archived, `400`/`413` invalid file) | Move the change to the **failed** store, keep syncing the rest, and show "N change(s) could not sync" with a **Retry** button. |

4. **Which copy is shown.** If this visit has changes still queued, the page shows the phone's copy. Otherwise it shows the server's copy, plus any items whose create was rejected (marked "[Not synced]").
5. **Reports wait for sync.** Export is blocked while this visit has queued changes. If some changes were rejected, the user must confirm before generating a report without them. A report built while observations are still on the phone would silently leave them out.

## What requires a connection

- Signing in, and opening a visit for the first time on this phone.
- Deleting items.
- Report generation, exports, and admin settings.
- Viewing photos already stored in the cloud. Signed URLs and API responses are not cached.

## Known limitations

- **Rejected changes have only Retry.** There is no screen yet to view a rejected change, save its photo to the phone, or discard it. The data stays in IndexedDB (the `failed` store) until retried. Needed before wide field use.
- **The queue is not tied to a user.** On a shared phone, changes queued by one person replay under whoever signs in next. Signing out does not warn about pending changes.
- **Last write wins.** An offline edit replayed later overwrites any newer value another member saved for the same field. There is no conflict check yet.
- **Sync only runs while the app is open.** iOS has no Background Sync. Users need to open the app after reconnecting.
- **Storage can be cleared.** The app asks the browser to keep its data (`navigator.storage.persist()`), but clearing site data or uninstalling before sync loses queued changes.
- **Icons.** The only icon is an SVG. iOS ignores SVG for `apple-touch-icon`, and some Android/Chrome versions want 192 px and 512 px PNG icons before they offer installation.
- **Cache version is manual.** Bump `CACHE` in `service-worker.js` when the pre-cached file list changes.

## Tests

- `tests/test_cloud_capture.py`: replayed item/observation creates are idempotent, numbers follow sync order, invalid or reused IDs are rejected, and duplicate uploads are not stored twice.
- `tests/test_cloud_pwa.py`: manifest, worker registration, no caching of `/api/` or `/auth/`, responses cloned before caching, offline navigation ignores the query string, and rejected changes are kept.
- `tests/browser/`: end-to-end in Chromium (see its README). Covers offline create, reload, sync with no duplicates, 404 parking and retry, 401 pause, 503 retry, and export blocking.

Still required by hand before release: on a real iPhone and Android phone, install the app, open a visit, switch to airplane mode, create two items with photos, force-quit and reopen, reconnect, and confirm everything synced once.
