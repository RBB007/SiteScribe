const CACHE="mka-site-visit-buddy-v3";
const STATIC=["/static/manifest.webmanifest","/static/app-icon.svg","/static/offline.js","/static/cloud_pwa.js","/static/cloud_mobile.css","/static/cloud_mobile_components.css","/static/cloud_capture.js","/static/cloud_capture_media.js","/static/cloud_overview.js"];
self.addEventListener("install",event=>event.waitUntil(caches.open(CACHE).then(cache=>cache.addAll(STATIC)).then(()=>self.skipWaiting())));
self.addEventListener("activate",event=>event.waitUntil(caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key)))).then(()=>self.clients.claim())));
self.addEventListener("fetch",event=>{const request=event.request,url=new URL(request.url);if(request.method!=="GET"||url.origin!==location.origin||url.pathname.startsWith("/api/")||url.pathname.startsWith("/auth/")||url.pathname.startsWith("/uploads/"))return;
  if(request.mode==="navigate"){event.respondWith(fetch(request).then(response=>{if(response.ok)caches.open(CACHE).then(cache=>cache.put(request,response.clone()));return response}).catch(()=>caches.match(request).then(hit=>hit||caches.match("/").then(home=>home||new Response("MKA Site Visit Buddy is offline. Reconnect once to open this screen.",{status:503,headers:{"Content-Type":"text/plain"}})))));return}
  if(url.pathname.startsWith("/static/")){event.respondWith(caches.match(request).then(hit=>{const network=fetch(request).then(response=>{if(response.ok)caches.open(CACHE).then(cache=>cache.put(request,response.clone()));return response});return hit||network}));}
});
