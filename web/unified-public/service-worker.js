const CACHE_NAME = "kquant-unified-static-v1";

function isStaticAsset(url) {
  return url.origin === self.location.origin && /^\/assets\/.+-[A-Za-z0-9_-]+\.(?:js|css)$/.test(url.pathname);
}

self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(keys.filter((key) => key !== CACHE_NAME && key.startsWith("kquant-unified-" )).map((key) => caches.delete(key)))).then(() => self.clients.claim()),
  );
});

self.addEventListener("fetch", (event) => {
  const request = event.request;
  const url = new URL(request.url);
  if (request.method !== "GET" || !isStaticAsset(url)) return;
  event.respondWith(
    caches.open(CACHE_NAME).then(async (cache) => {
      const cached = await cache.match(request);
      const network = fetch(request).then((response) => {
        if (response.ok) void cache.put(request, response.clone());
        return response;
      }).catch(() => cached || Response.error());
      return cached || network;
    }),
  );
});

self.addEventListener("push", (event) => {
  let payload = {};
  try { payload = event.data ? event.data.json() : {}; } catch { payload = {}; }
  event.waitUntil(self.registration.showNotification(payload.title || "KQUANT 研究提醒", {
    body: payload.body || "有新的研究状态需要查看。",
    icon: "/kq-mark.svg",
    badge: "/kq-mark.svg",
    tag: payload.tag || `kquant-${Date.now()}`,
    data: { url: payload.url || "/?view=today" },
  }));
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();
  const target = new URL(event.notification.data?.url || "/?view=today", self.location.origin).href;
  event.waitUntil(self.clients.matchAll({ type: "window", includeUncontrolled: true }).then((clients) => {
    const existing = clients.find((client) => client.url.startsWith(self.location.origin));
    if (existing) { existing.navigate(target); return existing.focus(); }
    return self.clients.openWindow(target);
  }));
});
