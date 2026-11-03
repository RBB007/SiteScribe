if ("serviceWorker" in navigator) window.addEventListener("load", () => navigator.serviceWorker.register("/service-worker.js").catch(error => console.warn("PWA registration failed", error)));

// Sync status from offline.js. Field changes are never dropped silently: the
// user always sees how many are waiting and how many need attention.
window.addEventListener("offline-status", event => {
  const message = document.querySelector("#message");
  if (!message) return;
  const {mode, count, failed, online} = event.detail;
  const plural = n => n + " change" + (n === 1 ? "" : "s");
  const show = (error, ...parts) => {
    message.className = "status" + (error ? " error" : "");
    message.replaceChildren(...parts);
  };
  if (mode === "auth") {
    const link = document.createElement("a");
    link.href = "/auth/login";
    link.textContent = "Sign in again";
    show(true, link, " to sync " + plural(count) + " saved on this phone.");
  } else if (failed) {
    const retry = document.createElement("button");
    retry.type = "button";
    retry.className = "pill";
    retry.textContent = "Retry";
    retry.onclick = () => window.OfflineStore && OfflineStore.retryFailed();
    show(true, plural(failed) + " could not sync. Kept on this phone. ", retry);
  } else if (!online || mode === "offline") {
    show(false, count ? plural(count) + " saved offline. They will sync when connected." : "Offline. Previously opened visits remain available.");
  } else if (mode === "retrying") {
    show(false, plural(count) + " waiting to sync. Retrying shortly.");
  } else if (mode === "saving" && count) {
    show(false, "Syncing " + plural(count) + "...");
  } else if (mode === "idle" && !count && message.dataset.hadPending) {
    show(false, "All offline changes synced.");
  }
  message.dataset.hadPending = count || failed ? "1" : "";
});
