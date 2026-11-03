// Visit data that works offline. Items and observations get their UUIDs on the
// phone, so they can be created with no connection and synced later; the server
// treats a replayed create with the same ID as the same record. See docs/pwa.md.
(function () {
  function uuid() {
    if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
    const bytes = crypto.getRandomValues(new Uint8Array(16));
    bytes[6] = (bytes[6] & 0x0f) | 0x40;
    bytes[8] = (bytes[8] & 0x3f) | 0x80;
    const hex = [...bytes].map(value => value.toString(16).padStart(2, "0")).join("");
    return hex.slice(0, 8) + "-" + hex.slice(8, 12) + "-" + hex.slice(12, 16) + "-" + hex.slice(16, 20) + "-" + hex.slice(20);
  }

  const cacheKey = visitId => "visit:" + visitId;
  const scope = visitId => "/api/visits/" + visitId + "/";

  function blankObservation(itemId, id) {
    return {
      id: id || uuid(), item_id: itemId, sequence: 1, description: "", caption: null,
      severity: null, tags: [], action: null, include_in_report: true,
      plan_page: null, plan_x: null, plan_y: null, files: [],
    };
  }

  function restat(data) {
    const observations = data.items.flatMap(item => item.observations);
    data.stats = {
      items: data.items.length,
      included: observations.filter(value => value.include_in_report).length,
      critical: observations.filter(value => String(value.severity || "").toLowerCase() === "critical").length,
    };
  }

  async function save(visitId, data) {
    restat(data);
    if (window.OfflineStore) await OfflineStore.cacheSet(cacheKey(visitId), data);
  }

  // Server copy when every local change for this visit has synced; otherwise
  // the local copy, so nothing the user captured disappears from the screen.
  async function load(visitId, api) {
    if (!window.OfflineStore) return {data: await api("/api/visits/" + visitId + "/overview"), source: "server", pending: 0};
    await OfflineStore.flush();
    const cached = await OfflineStore.cacheGet(cacheKey(visitId));
    const pending = await OfflineStore.pendingFor(scope(visitId));
    let server;
    try { server = await api("/api/visits/" + visitId + "/overview"); }
    catch (error) { if (!cached) throw error; return {data: cached, source: "offline", pending}; }
    if (pending && cached) return {data: cached, source: "local", pending};
    // Items whose create was rejected stay visible until the user deals with them.
    const known = new Set(server.items.map(item => item.id));
    (cached?.items || []).filter(item => item.pending && !known.has(item.id)).forEach(item => server.items.push(item));
    await save(visitId, server);
    return {data: server, source: "server", pending: 0};
  }

  // Create an item (with its first observation) locally, then send it.
  async function newItem(visitId, data, api) {
    const last = data.items.reduce((max, item) => Math.max(max, item.number || 0, item.position || 0), 0);
    const id = uuid(), first = blankObservation(id);
    const item = {id, number: last + 1, position: last + 1, pending: true, observations: [first]};
    data.items.push(item);
    await save(visitId, data);
    const saved = await api("/api/visits/" + visitId + "/items", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({id, observation_id: first.id, create_observation: true}),
    });
    if (saved && !saved.queued) {
      data.items[data.items.indexOf(item)] = saved;
      await save(visitId, data);
      return saved;
    }
    return item;
  }

  async function newObservation(visitId, data, item, api) {
    const observation = blankObservation(item.id);
    item.observations = [observation];
    await save(visitId, data);
    const saved = await api("/api/visits/" + visitId + "/items/" + item.id + "/observations", {
      method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({id: observation.id}),
    });
    if (saved && !saved.queued) { item.observations = [saved]; await save(visitId, data); return saved; }
    return observation;
  }

  // A report built while changes are still on this phone would leave them out.
  async function readyForReport(visitId) {
    if (!window.OfflineStore) return true;
    await OfflineStore.flush();
    const pending = await OfflineStore.pendingFor(scope(visitId));
    if (pending) {
      const error = new Error(pending + " change(s) to this visit are still on this phone. Connect and wait for them to sync before generating the report.");
      error.pending = pending;
      throw error;
    }
    const failed = await OfflineStore.failedFor(scope(visitId));
    return !failed || confirm(failed + " change(s) to this visit could not sync and are not on the server. Generate the report without them?");
  }

  // Photos still waiting to upload are kept as blobs in the local copy.
  const blobUrls = new WeakMap();
  function fileUrl(file) {
    if (file.download_url) return file.download_url;
    if (!file.blob) return "";
    if (!blobUrls.has(file.blob)) blobUrls.set(file.blob, URL.createObjectURL(file.blob));
    return blobUrls.get(file.blob);
  }

  window.CloudVisit = {uuid, load, save, newItem, newObservation, readyForReport, fileUrl, cacheKey};
})();
