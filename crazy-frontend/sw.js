// VoiceBite service worker. Network first, so a new deploy always shows up; the cache only covers a dropped connection.
const CACHE = "voicebite-v5";
const SHELL = ["./", "manifest.json", "icon-192.png", "icon-512.png"];

self.addEventListener("install", event => {
  self.skipWaiting();
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(SHELL)).catch(() => {}));
});

self.addEventListener("activate", event => {
  event.waitUntil(Promise.all([
    self.clients.claim(),
    caches.keys().then(keys => Promise.all(keys.filter(k => k !== CACHE).map(k => caches.delete(k))))
  ]));
});

self.addEventListener("fetch", event => {
  const request = event.request;
  if (request.method !== "GET") return;
  const url = new URL(request.url);
  // photos, icons and Google Fonts rarely change: serve from cache at once, refresh in the background
  if (/\.(jpg|jpeg|png|webp|svg|woff2?)$/i.test(url.pathname) || /fonts\.(googleapis|gstatic)\.com$/.test(url.hostname)) {
    event.respondWith(caches.open(CACHE).then(cache => cache.match(request).then(hit => {
      const fresh = fetch(request).then(r => { if (r.ok || r.type === "opaque") cache.put(request, r.clone()); return r; }).catch(() => hit);
      return hit || fresh;
    })));
    return;
  }
  if (url.origin !== self.location.origin) return;
  event.respondWith(
    fetch(request).then(response => {
      const copy = response.clone();
      caches.open(CACHE).then(cache => cache.put(request, copy)).catch(() => {});
      return response;
    }).catch(() => caches.match(request, { ignoreSearch: true }).then(hit => hit || caches.match("./")))
  );
});
