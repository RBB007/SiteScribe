// Offline capture end to end. See tests/browser/README.md.
const {chromium} = require("playwright");
const BASE = "http://localhost:5055";
const path = require("path");
const photo = name => path.join(__dirname, name);
const sleep = ms => new Promise(r => setTimeout(r, ms));
let failures = 0;
const check = (ok, label) => { console.log((ok ? "PASS " : "FAIL ") + label); if (!ok) failures++; };
(async () => {
  const browser = await chromium.launch();
  const context = await browser.newContext();
  const page = await context.newPage();
  page.on("pageerror", e => console.log("PAGEERROR", e.message));
  const visit = await (await fetch(BASE + "/visit-id")).text();
  const items = async () => (await (await fetch(`${BASE}/api/visits/${visit}/items`)).json());
  const msg = () => page.textContent("#message");
  const queue = () => page.evaluate(async () => [await OfflineStore.pendingCount(), await OfflineStore.failedCount()]);

  // 1. Online once: install the service worker and cache both pages.
  await page.goto(`${BASE}/visits/${visit}/overview`);
  await page.evaluate(() => navigator.serviceWorker.ready);
  await page.reload(); await sleep(500);
  await page.goto(`${BASE}/visits/${visit}`); await sleep(1000);   // creates item 1 online
  check((await items()).length === 1, "online: first item created on server");
  await page.goto(`${BASE}/visits/${visit}/overview`); await sleep(500);

  // 2. Offline: create items, type, attach photos.
  await context.setOffline(true);
  await page.click("#new-item"); await page.waitForURL(/item=/); await sleep(800);
  check(await page.isVisible("#description"), "offline: capture page opens for a new item (SW ignoreSearch)");
  await page.fill("#description", "Crack at grid C-4 offline");
  await sleep(700);
  await page.setInputFiles("#library-input", photo("photo1.jpg")); await sleep(500);
  await page.click("#new-item"); await sleep(800);
  await page.fill("#description", "Second offline item");
  await sleep(700);
  await page.setInputFiles("#library-input", photo("photo2.jpg")); await sleep(500);
  const [pending] = await queue();
  check(pending >= 6, "offline: changes queued on the phone (" + pending + ")");
  check((await items()).length === 1, "offline: nothing reached the server yet");

  // 3. Reload while offline: everything still on screen.
  await page.goto(`${BASE}/visits/${visit}/overview`); await sleep(800);
  const cards = await page.$$eval(".item-card .summary", els => els.map(e => e.textContent));
  check(cards.length === 3 && cards.some(c => c.includes("Crack at grid C-4")), "offline reload: overview shows local items " + JSON.stringify(cards));
  const thumbs = await page.$$eval(".item-card img", els => els.map(e => e.src.slice(0, 5)));
  check(thumbs.filter(s => s === "blob:").length === 2, "offline reload: queued photos still shown " + JSON.stringify(thumbs));

  // 4. Reconnect: everything syncs once, in order.
  await context.setOffline(false); await sleep(3000);
  const [left, failedNow] = await queue();
  const server = await items();
  check(left === 0 && failedNow === 0, "online: queue drained");
  check(server.length === 3, "server has 3 items, no duplicates");
  check(server.map(i => i.number).join() === "1,2,3", "server numbers in order");
  check(server[1].observations[0].description === "Crack at grid C-4 offline", "description synced");
  check(server.every(i => i.observations.length === 1), "one observation per item");
  check(server[1].observations[0].files.length === 1 && server[2].observations[0].files.length === 1, "photos synced once each");
  await page.reload(); await sleep(800);
  check(!(await page.textContent("#item-list")).includes("[Not synced]"), "overview shows server copy after sync");

  // 5. Server rejects a change (e.g. item deleted): kept, others continue, retry works.
  await page.goto(`${BASE}/visits/${visit}?item=${server[1].id}`); await sleep(800);
  await context.setOffline(true);
  await page.fill("#description", "Edited offline, server will reject");
  await sleep(700);
  await fetch(BASE + "/test/fail/404", {method: "POST"});
  await context.setOffline(false); await sleep(2000);
  let [p5, f5] = await queue();
  check(p5 === 0 && f5 === 1, "rejected change parked, queue not blocked");
  check((await msg()).includes("could not sync"), "user told: " + (await msg()).trim());
  await fetch(BASE + "/test/fail/0", {method: "POST"});
  await page.click("#message button"); await sleep(1500);
  [p5, f5] = await queue();
  check(p5 === 0 && f5 === 0, "retry succeeded");
  check((await items())[1].observations[0].description === "Edited offline, server will reject", "retried change on server");

  // 6. Session expired: queue pauses, nothing lost.
  await context.setOffline(true);
  await page.fill("#description", "Edited while signed out");
  await sleep(700);
  await fetch(BASE + "/test/fail/401", {method: "POST"});
  await context.setOffline(false); await sleep(1500);
  const [p6, f6] = await queue();
  check(p6 === 1 && f6 === 0, "401: change kept in queue");
  check((await msg()).includes("Sign in again"), "user told: " + (await msg()).trim());
  await fetch(BASE + "/test/fail/0", {method: "POST"});
  await page.reload(); await sleep(1500);
  check((await queue())[0] === 0 && (await items())[1].observations[0].description === "Edited while signed out", "after sign-in: synced");

  // 7. Server error: retried automatically with backoff.
  await fetch(BASE + "/test/fail/503", {method: "POST"});
  await page.fill("#description", "Edited during outage"); await sleep(1200);
  check((await queue())[0] === 1, "503: change queued for retry");
  await fetch(BASE + "/test/fail/0", {method: "POST"});
  await sleep(6500);
  check((await queue())[0] === 0 && (await items())[1].observations[0].description === "Edited during outage", "503: retried and synced");

  // 8. Report blocked while changes are pending.
  await context.setOffline(true);
  await page.fill("#description", "Pending at export"); await sleep(700);
  await page.click("#export"); await sleep(500);
  check((await msg()).includes("still on this phone"), "export blocked: " + (await msg()).trim());
  await context.setOffline(false); await sleep(2000);

  await browser.close();
  console.log(failures ? failures + " FAILED" : "ALL PASSED");
  process.exit(failures ? 1 : 0);
})();
