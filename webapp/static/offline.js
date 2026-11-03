// Offline store: a cache of visit data and an ordered queue of write requests,
// both in IndexedDB on this device. Queued requests replay in order when the
// device is online. See docs/pwa.md for the sync rules.
const DB_NAME = "mka-site-report-offline", VERSION = 2;
const RETRY_MIN_MS = 5000, RETRY_MAX_MS = 300000;

const openDB = () => new Promise((resolve, reject) => {
  const request = indexedDB.open(DB_NAME, VERSION);
  request.onupgradeneeded = () => {
    const db = request.result;
    if (!db.objectStoreNames.contains("queue")) db.createObjectStore("queue", {keyPath: "id", autoIncrement: true});
    if (!db.objectStoreNames.contains("cache")) db.createObjectStore("cache");
    // Requests the server rejected for good (e.g. 404, 400). Kept, never dropped silently.
    if (!db.objectStoreNames.contains("failed")) db.createObjectStore("failed", {keyPath: "id", autoIncrement: true});
  };
  request.onsuccess = () => resolve(request.result);
  request.onerror = () => reject(request.error);
});

async function store(name, mode, fn) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction(name, mode), result = fn(tx.objectStore(name));
    tx.oncomplete = () => resolve(result?.result);
    tx.onerror = () => reject(tx.error);
    tx.onabort = () => reject(tx.error);
  });
}

const getAll = () => store("queue", "readonly", s => s.getAll());
const failedJobs = () => store("failed", "readonly", s => s.getAll());
const pendingCount = async () => (await getAll()).length;
const failedCount = async () => (await failedJobs()).length;
const matching = (jobs, text) => jobs.filter(job => job.url.includes(text)).length;
// Counts for one visit: pass "/api/visits/<id>/".
const pendingFor = async text => matching(await getAll(), text);
const failedFor = async text => matching(await failedJobs(), text);

let state = "idle";  // idle | saving | offline | retrying | auth
async function notify(mode) {
  if (mode) state = mode;
  const [count, failed] = [await pendingCount(), await failedCount()];
  window.dispatchEvent(new CustomEvent("offline-status", {
    detail: {mode: state, count, failed, online: navigator.onLine},
  }));
}

async function cacheSet(key, value) { await store("cache", "readwrite", s => s.put(value, key)); }
async function cacheGet(key) { return store("cache", "readonly", s => s.get(key)); }

function packBody(body) {
  if (body instanceof FormData) return {type: "form", value: [...body.entries()]};
  if (typeof body === "string") return {type: "text", value: body};
  return {type: "none", value: null};
}
function unpackBody(body) {
  if (!body || body.type === "none") return undefined;
  if (body.type === "text") return body.value;
  const form = new FormData();
  body.value.forEach(([key, value]) => form.append(key, value));
  return form;
}

async function enqueue(url, options = {}) {
  const headers = {};
  new Headers(options.headers || {}).forEach((v, k) => headers[k] = v);
  await store("queue", "readwrite", s => s.add({
    url, method: options.method || "POST", headers, body: packBody(options.body), created: Date.now(),
  }));
  await notify(navigator.onLine ? state : "offline");
  return {queued: true};
}

async function request(url, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const canQueue = !["GET", "HEAD"].includes(method) && options.queue !== false;
  // Writes must reach the server in the order they were made. While older
  // changes are still queued, a new one joins the end of the queue.
  if (canQueue && (!navigator.onLine || await pendingCount())) {
    const queued = await enqueue(url, options);
    flush();
    return queued;
  }
  let response;
  try { response = await fetch(url, options); }
  catch (error) { if (canQueue) return enqueue(url, options); throw error; }
  // A server hiccup should not lose a field change: queue it and retry later.
  if (canQueue && isTransient(response.status)) { const queued = await enqueue(url, options); scheduleRetry(); return queued; }
  return response;
}

// Retry later: no network, server error, timeout, rate limit.
const isTransient = status => status === 408 || status === 425 || status === 429 || status >= 500;
// Sign-in needed: pause everything, keep the queue, resume after sign-in.
const isAuth = status => status === 401 || status === 403;

let running = null, retryTimer = null, retryDelay = RETRY_MIN_MS;
function scheduleRetry() {
  clearTimeout(retryTimer);
  retryTimer = setTimeout(flush, retryDelay);
  retryDelay = Math.min(retryDelay * 2, RETRY_MAX_MS);
}

async function park(job, status, detail) {
  const {id, ...rest} = job;
  await store("failed", "readwrite", s => s.add({...rest, queueId: id, status, detail, failedAt: Date.now()}));
  await store("queue", "readwrite", s => s.delete(job.id));
}

async function replay() {
  if (!navigator.onLine) { await notify("offline"); return; }
  await notify("saving");
  for (const job of await getAll()) {
    let response;
    try {
      response = await fetch(job.url, {method: job.method, headers: job.headers, body: unpackBody(job.body)});
    } catch (error) {
      scheduleRetry(); await notify(navigator.onLine ? "retrying" : "offline"); return;
    }
    // A redirect means the session ended and the login page answered: not saved.
    if (response.redirected || isAuth(response.status)) { await notify("auth"); return; }
    if (response.ok) { await store("queue", "readwrite", s => s.delete(job.id)); continue; }
    if (isTransient(response.status)) { scheduleRetry(); await notify("retrying"); return; }
    let detail = "";
    try { detail = (await response.json()).error || ""; } catch (_) { /* not JSON */ }
    console.warn("[offline queue] kept rejected change", response.status, job.url, detail);
    await park(job, response.status, detail);
  }
  retryDelay = RETRY_MIN_MS;
  await notify("idle");
}

// One replay at a time; callers can await the replay already running.
function flush() {
  if (!running) running = replay().catch(error => console.warn("[offline queue]", error)).finally(() => { running = null; });
  return running;
}

// Put rejected changes back on the queue (e.g. after an admin restores a visit).
async function retryFailed() {
  for (const job of await failedJobs()) {
    const {queueId, status, detail, failedAt, id, ...rest} = job;
    await store("queue", "readwrite", s => s.add(rest));
    await store("failed", "readwrite", s => s.delete(id));
  }
  return flush();
}

// Ask the browser not to evict this data when the device is low on space.
if (navigator.storage && navigator.storage.persist) navigator.storage.persist().catch(() => {});

window.OfflineStore = {
  request, enqueue, flush, pendingCount, failedCount, pendingFor, failedFor,
  failedJobs, retryFailed, cacheSet, cacheGet, notify,
};
window.addEventListener("online", () => { retryDelay = RETRY_MIN_MS; flush(); });
window.addEventListener("offline", () => notify("offline"));
document.addEventListener("visibilitychange", () => { if (!document.hidden) flush(); });
flush();
