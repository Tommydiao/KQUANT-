const STATIC_CACHE = "kquant-static-realtime-options-v1";

function isStaticAsset(url) {
  if (url.origin !== self.location.origin) return false;
  return url.pathname === "/" ||
    url.pathname === "/index.html" ||
    url.pathname === "/manifest.webmanifest" ||
    url.pathname === "/kquant-mark.svg" ||
    url.pathname.startsWith("/assets/");
}

self.addEventListener("install", () => {
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((names) => Promise.all(
      names.filter((name) => name.startsWith("kquant-static-") && name !== STATIC_CACHE).map((name) => caches.delete(name)),
    )).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || !isStaticAsset(url)) return;
  event.respondWith(
    caches.open(STATIC_CACHE).then(async (cache) => {
      const cached = await cache.match(request);
      const network = fetch(request)
        .then((response) => {
          if (response.ok && url.origin === self.location.origin) cache.put(request, response.clone());
          return response;
        })
        .catch(() => cached || Response.error());
      const isAppShell = url.pathname === "/" || url.pathname === "/index.html" || url.pathname === "/manifest.webmanifest";
      return isAppShell ? network : cached || network;
    }),
  );
});
