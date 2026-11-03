const CACHE="mka-site-report-shell-v2";
const STATIC=["/static/manifest.webmanifest","/static/app-icon.svg","/static/offline.js"];
self.addEventListener("install",event=>event.waitUntil(
  caches.open(CACHE).then(cache=>cache.addAll(STATIC)).then(()=>self.skipWaiting())
));
self.addEventListener("activate",event=>event.waitUntil(
  caches.keys().then(keys=>Promise.all(keys.filter(key=>key!==CACHE).map(key=>caches.delete(key))))
    .then(()=>self.clients.claim())
));
self.addEventListener("fetch",event=>{
  const request=event.request,url=new URL(request.url);
  if(request.method!=="GET"||url.origin!==location.origin||url.pathname.startsWith("/api/")||url.pathname.startsWith("/uploads/"))return;
  const shell=url.pathname==="/capture"||url.pathname==="/overview"||url.pathname.startsWith("/static/");
  if(!shell)return;
  event.respondWith(fetch(request).then(response=>{
    if(response.ok){const copy=response.clone(),canonical=response.clone();caches.open(CACHE).then(cache=>{
      cache.put(request,copy);if(url.pathname==="/capture"||url.pathname==="/overview")cache.put(url.pathname,canonical);
    })}
    return response;
  }).catch(()=>caches.match(request).then(hit=>hit||caches.match(url.pathname))));
});
